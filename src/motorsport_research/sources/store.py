"""Short storage transactions around collection; network work never holds a write lock."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from motorsport_research.sources.catalogue import Catalogue, SourceDefinition, endpoint
from motorsport_research.sources.parsers import PARSER_VERSION, ParsedDocument
from motorsport_research.storage.models import DocumentInput, timestamp
from motorsport_research.storage.repository import identifier, now, open_repository


class CollectionStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def register(self, catalogue: Catalogue) -> dict[str, tuple[str, str]]:
        identities = {}
        remaining = list(catalogue.sources)
        with open_repository(self.data_dir) as repository:
            while remaining:
                for source in remaining[:]:
                    if source.upstream_key and source.upstream_key not in identities:
                        continue
                    upstream = identities[source.upstream_key][0] if source.upstream_key else None
                    source_id = repository.register_source(source.attribution(upstream))
                    existing = repository.connection.execute(
                        "SELECT id FROM source_configurations "
                        "WHERE source_id = ? AND config_hash = ?",
                        (source_id, source.digest),
                    ).fetchone()
                    config_id = existing["id"] if existing else identifier("source_configuration")
                    if not existing:
                        repository.connection.execute(
                            "INSERT INTO source_configurations VALUES (?, ?, ?, ?, ?)",
                            (config_id, source_id, source.digest, source.model_dump_json(), now()),
                        )
                    identities[source.key] = source_id, config_id
                    remaining.remove(source)
        return identities

    def state(self, source_id: str, source: SourceDefinition) -> tuple[dict | None, dict | None]:
        with open_repository(self.data_dir, read_only=True) as repository:
            latest = repository.connection.execute(
                "SELECT r.* FROM collection_runs r JOIN source_configurations c "
                "ON c.id = r.configuration_id WHERE r.source_id = ? AND c.config_hash = ? "
                "ORDER BY r.finished_at DESC, r.rowid DESC LIMIT 1",
                (source_id, source.digest),
            ).fetchone()
            cache = repository.connection.execute(
                "SELECT * FROM collection_cache WHERE source_id = ? AND config_hash = ? "
                "AND requested_url = ? AND parser_version = ?",
                (source_id, source.digest, endpoint(source), PARSER_VERSION),
            ).fetchone()
            if cache:
                version = repository._require("document_versions", cache["document_version_id"])
                repository.blobs.read(version["content_hash"])
            return dict(latest) if latest else None, dict(cache) if cache else None

    def reserve_host(
        self, host: str, epoch: float, interval: float, deadline_epoch: float
    ) -> float | None:
        with open_repository(self.data_dir) as repository:
            existing = repository.connection.execute(
                "SELECT next_allowed_epoch FROM collection_hosts WHERE host = ?", (host,)
            ).fetchone()
            reserved = max(epoch, existing[0] if existing else epoch)
            if reserved >= deadline_epoch:
                return None
            repository.connection.execute(
                "INSERT INTO collection_hosts VALUES (?, ?) ON CONFLICT(host) DO UPDATE "
                "SET next_allowed_epoch = excluded.next_allowed_epoch",
                (host, reserved + interval),
            )
            return reserved - epoch

    def finish(
        self,
        source: SourceDefinition,
        source_id: str,
        config_id: str,
        run_id: str,
        started: datetime,
        outcome: str,
        requests: list[dict],
        *,
        detail: str | None = None,
        parsed: ParsedDocument | None = None,
        content: bytes | None = None,
        effective_url: str | None = None,
        media_type: str | None = None,
        cache: dict | None = None,
        defer_until: datetime | None = None,
    ) -> dict:
        finished = datetime.now(UTC)
        next_due = max(
            finished + timedelta(seconds=source.refresh_seconds), defer_until or finished
        )
        version_id = None
        receipt = None
        with open_repository(self.data_dir) as repository:
            if parsed is not None:
                receipt = repository.import_document(
                    source_id,
                    DocumentInput(
                        url=effective_url,
                        content=content,
                        extracted_text=parsed.text,
                        title=parsed.title,
                        parser_version=PARSER_VERSION,
                        media_type=media_type,
                        retrieval_method="http",
                        http_status=requests[-1]["http_status"],
                        retrieved_at=finished,
                    ),
                )
                version_id = receipt["version_id"]
                for link in parsed.links:
                    repository.connection.execute(
                        "INSERT OR IGNORE INTO discovered_links VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            version_id,
                            link["position"],
                            link["url"],
                            link["title"],
                            link["item_key"],
                            link["published_at"],
                            link["source_timezone"],
                        ),
                    )
                last = requests[-1]
                repository.connection.execute(
                    "INSERT INTO collection_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(source_id, config_hash, requested_url) DO UPDATE SET "
                    "effective_url = excluded.effective_url, "
                    "parser_version = excluded.parser_version, "
                    "document_version_id = excluded.document_version_id, etag = excluded.etag, "
                    "last_modified = excluded.last_modified, checked_at = excluded.checked_at",
                    (
                        source_id,
                        source.digest,
                        endpoint(source),
                        effective_url,
                        PARSER_VERSION,
                        version_id,
                        last["etag"],
                        last["last_modified"],
                        timestamp(finished),
                    ),
                )
            else:
                version_id = (
                    cache["document_version_id"] if outcome == "not_modified" and cache else None
                )
                repository.record_retrieval(
                    source_id,
                    endpoint(source),
                    method="http",
                    retrieved_at=finished,
                    outcome=(
                        "not_modified"
                        if outcome == "not_modified"
                        else "denied"
                        if outcome == "access_denied"
                        else "failed"
                    ),
                    document_version_id=version_id,
                    http_status=requests[-1]["http_status"] if requests else None,
                    error=detail,
                )
            repository.connection.execute(
                "INSERT INTO collection_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    source_id,
                    config_id,
                    endpoint(source),
                    timestamp(started),
                    timestamp(finished),
                    timestamp(next_due),
                    outcome,
                    detail,
                    version_id,
                ),
            )
            for request in requests:
                raw = request.pop("content", None)
                digest = repository.blobs.put(raw) if raw is not None else None
                repository.connection.execute(
                    "INSERT INTO collection_requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        identifier("collection_request"),
                        run_id,
                        request["url"],
                        request["started_at"],
                        request["finished_at"],
                        request["outcome"],
                        request["http_status"],
                        request["received_bytes"],
                        digest,
                        request["etag"],
                        request["last_modified"],
                        request["detail"],
                    ),
                )
        return {
            "source": source.key,
            "run_id": run_id,
            "outcome": outcome,
            "detail": detail,
            "requests": len(requests),
            "document": receipt,
            "document_version_id": version_id,
            "next_due_at": timestamp(next_due),
            "discovered_links": len(parsed.links) if parsed else 0,
            "warnings": parsed.warnings if parsed else [],
        }

    def defer_host(self, host: str, until_epoch: float) -> None:
        with open_repository(self.data_dir) as repository:
            repository.connection.execute(
                "INSERT INTO collection_hosts VALUES (?, ?) ON CONFLICT(host) DO UPDATE "
                "SET next_allowed_epoch = max(next_allowed_epoch, excluded.next_allowed_epoch)",
                (host, until_epoch),
            )

    def status(self, catalogue: Catalogue) -> dict:
        rows = []
        with open_repository(self.data_dir, read_only=True) as repository:
            for source in catalogue.sources:
                latest = repository.connection.execute(
                    "SELECT r.*, c.config_hash FROM collection_runs r "
                    "JOIN sources s ON s.id = r.source_id "
                    "JOIN source_configurations c ON c.id = r.configuration_id "
                    "WHERE s.source_key = ? ORDER BY r.finished_at DESC, r.rowid DESC LIMIT 1",
                    (source.key,),
                ).fetchone()
                successful = repository.connection.execute(
                    "SELECT r.finished_at FROM collection_runs r "
                    "JOIN sources s ON s.id = r.source_id "
                    "JOIN source_configurations c ON c.id = r.configuration_id "
                    "WHERE s.source_key = ? AND c.config_hash = ? "
                    "AND r.outcome IN ('success', 'not_modified') "
                    "ORDER BY r.finished_at DESC LIMIT 1",
                    (source.key, source.digest),
                ).fetchone()
                rows.append(
                    {
                        "key": source.key,
                        "enabled": source.enabled,
                        "championships": source.championships,
                        "declared_availability": source.availability,
                        "latest": dict(latest) if latest else None,
                        "configuration_changed": bool(
                            latest and latest["config_hash"] != source.digest
                        ),
                        "last_success_at": successful[0] if successful else None,
                    }
                )
            links = [
                dict(row)
                for row in repository.connection.execute(
                    "SELECT l.*, s.source_key FROM discovered_links l "
                    "JOIN document_versions v ON v.id = l.document_version_id "
                    "JOIN documents d ON d.id = v.document_id JOIN sources s ON s.id = d.source_id "
                    "ORDER BY v.first_retrieved_at DESC, l.position LIMIT 100"
                )
            ]
        coverage = {}
        for championship in ("F1", "WEC", "WRC", "DTM"):
            applicable = [
                row for row in rows if row["enabled"] and championship in row["championships"]
            ]
            coverage[championship] = {
                "configured_sources": len(applicable),
                "sources_with_success": sum(bool(row["last_success_at"]) for row in applicable),
            }
        return {"sources": rows, "coverage": coverage, "discovered_links": links}

    def history(self, key: str, limit: int = 20) -> list[dict]:
        with open_repository(self.data_dir, read_only=True) as repository:
            runs = []
            for row in repository.connection.execute(
                "SELECT r.* FROM collection_runs r JOIN sources s ON s.id = r.source_id "
                "WHERE s.source_key = ? ORDER BY r.finished_at DESC, r.rowid DESC LIMIT ?",
                (key, limit),
            ):
                value = dict(row)
                value["requests"] = [
                    dict(request)
                    for request in repository.connection.execute(
                        "SELECT * FROM collection_requests WHERE run_id = ? ORDER BY rowid",
                        (row["id"],),
                    )
                ]
                config = repository._require("source_configurations", row["configuration_id"])
                value["configuration"] = json.loads(config["config_json"])
                runs.append(value)
            return runs
