"""Serial bounded HTTP/RSS collection with durable host pacing and conditional caching."""

import asyncio
import inspect
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx
from pydantic import AnyHttpUrl

from motorsport_research import __version__
from motorsport_research.sources.catalogue import Catalogue, SourceDefinition, endpoint
from motorsport_research.sources.parsers import CollectionError, parse_document
from motorsport_research.sources.store import CollectionStore
from motorsport_research.storage.models import canonical_url, timestamp
from motorsport_research.storage.repository import identifier

SUCCESS = {"success", "not_modified", "not_due", "disabled"}
RETRYABLE = {408, 429, 500, 502, 503, 504}
REDIRECTS = {301, 302, 303, 307, 308}


def _header(response: httpx.Response, name: str) -> str | None:
    value = response.headers.get(name)
    return value if value and len(value) <= 1024 and not any(ord(c) < 32 for c in value) else None


def _retry_delay(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        delay = (
            float(value)
            if value.isdigit()
            else (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
        )
        return min(max(delay, 0), 604800)
    except (ValueError, TypeError, OverflowError):
        return None


class Collector:
    def __init__(
        self,
        data_dir: Path,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable = asyncio.sleep,
    ):
        self.store = CollectionStore(data_dir)
        self.client = client
        self.sleep = sleep

    def collect(
        self, catalogue: Catalogue, keys: list[str] | None = None, *, force: bool = False
    ) -> list[dict]:
        return asyncio.run(self.collect_async(catalogue, keys, force=force))

    async def collect_async(
        self, catalogue: Catalogue, keys: list[str] | None = None, *, force: bool = False
    ) -> list[dict]:
        catalogue = Catalogue.model_validate(catalogue)
        selected = catalogue.select(keys)
        identities = self.store.register(catalogue)
        if self.client is not None:
            return [
                await self._source(source, *identities[source.key], force=force)
                for source in selected
            ]
        # Standard TLS verification and environment proxies remain enabled.
        async with httpx.AsyncClient(follow_redirects=False) as client:
            self.client = client
            try:
                return [
                    await self._source(source, *identities[source.key], force=force)
                    for source in selected
                ]
            finally:
                self.client = None

    async def _pause(self, seconds: float) -> None:
        result = self.sleep(seconds)
        if inspect.isawaitable(result):
            await result

    async def _source(
        self, source: SourceDefinition, source_id: str, config_id: str, *, force: bool
    ) -> dict:
        if not source.enabled:
            return {"source": source.key, "outcome": "disabled"}
        latest, cache = self.store.state(source_id, source)
        if (
            not force
            and latest
            and datetime.fromisoformat(latest["next_due_at"]) > datetime.now(UTC)
        ):
            return {
                "source": source.key,
                "outcome": "not_due",
                "next_due_at": latest["next_due_at"],
            }
        started = datetime.now(UTC)
        run_id = identifier("collection_run")
        requests = []
        deadline = time.monotonic() + source.total_seconds
        defer_until = None
        try:
            async with asyncio.timeout(source.total_seconds):
                if source.method == "browser":
                    raise CollectionError(
                        "unsupported_method",
                        "Browser adapter is not enabled; use an HTTP/RSS source",
                    )
                url = endpoint(source)
                redirects = 0
                attempts = 0
                visited = {url}
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise CollectionError(
                            "timeout", "Collection exceeded its total time budget"
                        )
                    host = AnyHttpUrl(url).host
                    wait = self.store.reserve_host(
                        host, time.time(), source.host_interval_seconds, time.time() + remaining
                    )
                    if wait is None:
                        raise CollectionError(
                            "rate_limited", "Host pacing exceeds this collection's time budget"
                        )
                    if wait:
                        await self._pause(wait)
                    headers = {
                        "User-Agent": f"MotorsportResearch/{__version__} (personal research)",
                        "Accept-Encoding": "identity",
                        "Accept": "application/rss+xml, application/atom+xml, application/xml"
                        if source.method == "rss"
                        else "text/html, text/plain, application/pdf",
                    }
                    if cache and cache["effective_url"] == url:
                        if cache["etag"]:
                            headers["If-None-Match"] = cache["etag"]
                        if cache["last_modified"]:
                            headers["If-Modified-Since"] = cache["last_modified"]
                    request = {
                        "url": url,
                        "started_at": timestamp(datetime.now(UTC)),
                        "finished_at": None,
                        "outcome": "network_error",
                        "http_status": None,
                        "received_bytes": 0,
                        "etag": None,
                        "last_modified": None,
                        "detail": None,
                    }
                    requests.append(request)
                    attempts += 1
                    try:
                        async with self.client.stream(
                            "GET",
                            url,
                            headers=headers,
                            follow_redirects=False,
                            timeout=min(
                                source.timeout_seconds, max(0.01, deadline - time.monotonic())
                            ),
                        ) as response:
                            request.update(
                                http_status=response.status_code,
                                etag=_header(response, "etag"),
                                last_modified=_header(response, "last-modified"),
                            )
                            status = response.status_code
                            if status in REDIRECTS:
                                location = response.headers.get("location")
                                if not location or len(location) > 4096:
                                    raise CollectionError(
                                        "redirect_error", "Redirect has no usable Location"
                                    )
                                try:
                                    target = AnyHttpUrl(urljoin(url, location))
                                    target_url = canonical_url(target)
                                except ValueError as error:
                                    raise CollectionError(
                                        "redirect_error", "Redirect URL is invalid"
                                    ) from error
                                if target.host not in source.hosts or (
                                    AnyHttpUrl(url).scheme == "https" and target.scheme != "https"
                                ):
                                    raise CollectionError(
                                        "redirect_denied",
                                        "Redirect is outside approved hosts or downgrades HTTPS",
                                    )
                                if target_url in visited or redirects >= source.max_redirects:
                                    raise CollectionError(
                                        "redirect_error", "Redirect loop or redirect limit exceeded"
                                    )
                                request["outcome"] = "redirect"
                                visited.add(target_url)
                                url = target_url
                                redirects += 1
                                attempts = 0
                                continue
                            if status == 304:
                                if (
                                    not cache
                                    or cache["effective_url"] != url
                                    or not (
                                        "If-None-Match" in headers or "If-Modified-Since" in headers
                                    )
                                ):
                                    raise CollectionError(
                                        "invalid_not_modified",
                                        "304 response has no matching validated cache",
                                    )
                                request["outcome"] = "not_modified"
                                request["finished_at"] = timestamp(datetime.now(UTC))
                                return self.store.finish(
                                    source,
                                    source_id,
                                    config_id,
                                    run_id,
                                    started,
                                    "not_modified",
                                    requests,
                                    cache=cache,
                                )
                            if status in RETRYABLE:
                                delay = _retry_delay(_header(response, "retry-after"))
                                if delay is not None:
                                    defer_until = datetime.now(UTC) + timedelta(seconds=delay)
                                    self.store.defer_host(host, defer_until.timestamp())
                                pause = delay if delay is not None else min(2 ** (attempts - 1), 4)
                                if (
                                    attempts < source.max_attempts
                                    and pause < deadline - time.monotonic()
                                ):
                                    request["outcome"] = "retry"
                                    await self._pause(pause)
                                    continue
                                raise CollectionError(
                                    "rate_limited" if status == 429 else "http_error",
                                    "Retryable HTTP failure exhausted its retry budget",
                                )
                            if status in {401, 403, 451}:
                                raise CollectionError(
                                    "access_denied", f"Source returned HTTP {status}"
                                )
                            if status != 200:
                                raise CollectionError(
                                    "http_error", f"Source returned HTTP {status}"
                                )
                            if (
                                response.headers.get("content-encoding", "identity").lower()
                                != "identity"
                            ):
                                raise CollectionError(
                                    "unsupported_format",
                                    "Server ignored identity encoding; compression is unsupported",
                                )
                            length = response.headers.get("content-length")
                            if length and length.isdigit() and int(length) > source.max_bytes:
                                raise CollectionError(
                                    "too_large", "Declared response size exceeds source limit"
                                )
                            parts = []
                            async for chunk in response.aiter_raw():
                                request["received_bytes"] += len(chunk)
                                if request["received_bytes"] > source.max_bytes:
                                    raise CollectionError(
                                        "too_large", "Streamed response exceeds source limit"
                                    )
                                if time.monotonic() >= deadline:
                                    raise CollectionError(
                                        "timeout", "Response exceeded total time budget"
                                    )
                                parts.append(chunk)
                            content = b"".join(parts)
                            request["content"] = content
                            media_type = (
                                response.headers.get("content-type", "")
                                .split(";", 1)[0]
                                .strip()
                                .lower()
                            )
                            parsed = parse_document(
                                content,
                                media_type,
                                response.encoding or "utf-8",
                                source.method,
                                url,
                            )
                            request["outcome"] = "success"
                            request["finished_at"] = timestamp(datetime.now(UTC))
                            return self.store.finish(
                                source,
                                source_id,
                                config_id,
                                run_id,
                                started,
                                "success",
                                requests,
                                parsed=parsed,
                                content=content,
                                effective_url=url,
                                media_type=media_type,
                            )
                    except httpx.TimeoutException:
                        request.update(outcome="timeout", detail="HTTP request timed out")
                        if attempts >= source.max_attempts:
                            raise CollectionError("timeout", "HTTP request timed out") from None
                        await self._pause(min(1, max(0, deadline - time.monotonic())))
                    except httpx.ProxyError:
                        raise CollectionError(
                            "proxy_error",
                            "Environment proxy rejected or could not forward the request",
                        ) from None
                    except httpx.HTTPError:
                        request.update(
                            outcome="network_error", detail="HTTP connection or protocol failed"
                        )
                        if attempts >= source.max_attempts:
                            raise CollectionError(
                                "network_error", "HTTP connection or protocol failed"
                            ) from None
                        await self._pause(min(1, max(0, deadline - time.monotonic())))
                    finally:
                        request["finished_at"] = request["finished_at"] or timestamp(
                            datetime.now(UTC)
                        )
        except TimeoutError:
            detail = "Collection exceeded its total time budget"
            if requests:
                requests[-1].update(outcome="timeout", detail=detail)
            return self.store.finish(
                source, source_id, config_id, run_id, started, "timeout", requests, detail=detail
            )
        except CollectionError as error:
            if requests:
                requests[-1].update(outcome=error.outcome, detail=str(error))
            return self.store.finish(
                source,
                source_id,
                config_id,
                run_id,
                started,
                error.outcome,
                requests,
                detail=str(error),
                defer_until=defer_until,
            )
