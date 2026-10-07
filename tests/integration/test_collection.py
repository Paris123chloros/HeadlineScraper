import asyncio
import json
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from motorsport_research.cli import main
from motorsport_research.config import Settings
from motorsport_research.sources.catalogue import (
    Catalogue,
    CatalogueError,
    SourceDefinition,
    load_catalogue,
)
from motorsport_research.sources.collector import Collector
from motorsport_research.sources.parsers import CollectionError, parse_document, parse_feed
from motorsport_research.sources.store import CollectionStore
from motorsport_research.storage.database import StorageError, initialize, migrations
from motorsport_research.storage.repository import open_repository
from motorsport_research.web.app import create_app

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/collection"
RSS = (FIXTURES / "rss.xml").read_bytes()
HTML = (FIXTURES / "page.html").read_bytes()


def definition(**changes):
    return SourceDefinition(
        **(
            {
                "key": "synthetic",
                "name": "Synthetic source",
                "homepage": "https://example.invalid/",
                "url": "https://example.invalid/feed",
                "kind": "official",
                "role": "championship",
                "publisher": "Fictional publisher",
                "championships": ["F1"],
                "method": "rss",
                "availability": "unverified",
                "notes": "Synthetic fixture, not a real publisher",
                "host_interval_seconds": 0.1,
            }
            | changes
        )
    )


def response(status=200, content=RSS, **headers):
    return httpx.Response(
        status,
        headers={"Content-Type": "application/rss+xml", **headers},
        stream=httpx.ByteStream(content),
    )


@pytest.fixture
def data(tmp_path):
    initialize(tmp_path)
    return tmp_path


def run(data, handler, source=None, *, force=True, sleep=lambda _: None):
    source = source or definition()

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await Collector(data, client=client, sleep=sleep).collect_async(
                Catalogue(sources=[source]), [source.key], force=force
            )
            return result[0]

    return asyncio.run(execute())


def test_catalogue_all_series_organization_scope_and_validation(tmp_path):
    catalogue = load_catalogue(ROOT / "config/sources.yaml")
    assert {c for source in catalogue.sources if source.enabled for c in source.championships} == {
        "F1",
        "WEC",
        "WRC",
        "DTM",
    }
    assert catalogue.select(["fia-news"])[0].championships == []
    assert all(
        source.availability in {"unverified", "usable", "needs_browser"}
        for source in catalogue.sources
    )
    assert {s.role for s in catalogue.sources} == {
        "championship",
        "team",
        "governing_body",
        "newsroom",
    }
    with pytest.raises(CatalogueError, match="Unknown"):
        catalogue.select(["absent"])
    with pytest.raises(ValidationError):
        Catalogue(sources=[definition(), definition()])
    with pytest.raises(ValidationError):
        Catalogue(sources=[definition(upstream_key="synthetic")])
    with pytest.raises(ValidationError):
        definition(url="https://username:password@example.invalid/feed")
    with pytest.raises(ValidationError):
        definition(allowed_hosts=["unrelated.invalid"])
    path = tmp_path / "ambiguous.yaml"
    path.write_text("schema_version: 1\nsources: []\nsources: []\n")
    with pytest.raises(CatalogueError, match="Duplicate"):
        load_catalogue(path)


def test_rss_atom_dates_and_links_do_not_assert_findings():
    parsed = parse_feed(RSS, "https://example.invalid/feed")
    assert "investigation" in parsed.text
    assert "No finding is asserted" in parsed.text
    assert parsed.links[0]["url"] == "https://example.invalid/news/bulletin"
    assert parsed.links[0]["published_at"] == "2026-01-01T11:00:00.000000+00:00"
    assert parsed.links[0]["source_timezone"] == "UTC+02:00"
    assert parsed.links[1]["published_at"] is None
    assert parsed.warnings
    atom = parse_feed((FIXTURES / "atom.xml").read_bytes(), "https://example.invalid/feed")
    assert atom.links[0]["url"] == "https://example.invalid/announcements/notice"
    assert atom.links[0]["published_at"] == parsed.links[0]["published_at"]


def test_import_conditional_cache_304_repeat_and_changed_feed(data):
    first = run(
        data, lambda _: response(ETag='"one"', **{"Last-Modified": "Thu, 01 Jan 2026 11:00:00 GMT"})
    )

    def unchanged(request):
        assert request.headers["if-none-match"] == '"one"'
        assert "if-modified-since" in request.headers
        return response(304, b"")

    second = run(data, unchanged)
    repeat = run(data, lambda _: response())
    updated = run(
        data,
        lambda _: response(
            content=RSS.replace(b"Fictional race bulletin", b"Corrected fictional bulletin")
        ),
    )
    assert first["outcome"] == repeat["outcome"] == "success"
    assert second["outcome"] == "not_modified"
    assert (
        first["document_version_id"]
        == second["document_version_id"]
        == repeat["document_version_id"]
    )
    assert updated["document"]["revision"] == 2
    with open_repository(data, read_only=True) as repository:
        counts = repository.stats()["counts"]
        assert counts["documents"] == 1 and counts["document_versions"] == 2
        assert counts["collection_runs"] == counts["retrievals"] == 4
        assert counts["discovered_links"] == 4
        assert counts["claims"] == 0
    status = CollectionStore(data).status(Catalogue(sources=[definition()]))
    assert status["coverage"]["F1"]["sources_with_success"] == 1
    assert status["coverage"]["WEC"]["sources_with_success"] == 0


def test_due_disabled_and_host_pacing_survive_new_collector(data):
    pauses = []
    run(data, lambda _: response(), sleep=pauses.append)
    assert run(data, lambda _: pytest.fail("not due"), force=False)["outcome"] == "not_due"
    run(data, lambda _: response(), sleep=pauses.append)
    assert any(pause > 0 for pause in pauses)
    assert (
        run(data, lambda _: pytest.fail("disabled"), definition(enabled=False))["outcome"]
        == "disabled"
    )
    store = CollectionStore(data)
    assert store.reserve_host("paced.invalid", 100, 2, 110) == 0
    assert store.reserve_host("paced.invalid", 100, 2, 110) == 2
    assert store.reserve_host("paced.invalid", 100, 2, 103) is None


@pytest.mark.parametrize(
    "status,outcome",
    [
        (401, "access_denied"),
        (403, "access_denied"),
        (451, "access_denied"),
        (404, "http_error"),
        (304, "invalid_not_modified"),
    ],
)
def test_status_failures_are_audited_without_documents(data, status, outcome):
    result = run(data, lambda _: response(status, b""))
    assert result["outcome"] == outcome
    history = CollectionStore(data).history("synthetic")
    assert history[0]["requests"][0]["http_status"] == status
    assert history[0]["document_version_id"] is None
    with open_repository(data, read_only=True) as repository:
        assert repository.stats()["counts"]["document_versions"] == 0
        assert repository.stats()["counts"]["retrievals"] == 1


def test_retry_success_and_retry_after_defer(data):
    calls = []

    def transient(request):
        calls.append(request)
        return response(503 if len(calls) == 1 else 200)

    result = run(data, transient)
    assert result["outcome"] == "success" and len(calls) == 2
    history = CollectionStore(data).history("synthetic")[0]
    assert [r["outcome"] for r in history["requests"]] == ["retry", "success"]
    calls.clear()

    def throttled(request):
        calls.append(request)
        return response(429, b"", **{"Retry-After": "7200"})

    result = run(data, throttled)
    assert result["outcome"] == "rate_limited" and len(calls) == 1
    assert (
        datetime.fromisoformat(result["next_due_at"]) - datetime.now(UTC)
    ).total_seconds() > 7100
    assert (
        run(data, lambda _: pytest.fail("Retry-After survives force"))["outcome"] == "rate_limited"
    )


@pytest.mark.parametrize(
    "exception,outcome",
    [
        (httpx.ReadTimeout, "timeout"),
        (httpx.ConnectError, "network_error"),
        (httpx.ProxyError, "proxy_error"),
    ],
)
def test_transport_failure_retry_limits_and_safe_details(data, exception, outcome):
    calls = []

    def failed(request):
        calls.append(request)
        raise exception("sensitive transport diagnostic", request=request)

    result = run(data, failed)
    assert result["outcome"] == outcome
    assert len(calls) == (1 if outcome == "proxy_error" else 2)
    assert "sensitive" not in json.dumps(CollectionStore(data).history("synthetic"))


def test_redirect_chain_and_cache_validators_stay_at_effective_url(data):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/feed":
            assert "if-none-match" not in request.headers
            return response(302, b"", Location="/actual")
        assert request.url.path == "/actual"
        return (
            response(304, b"")
            if request.headers.get("if-none-match")
            else response(ETag='"actual"')
        )

    first = run(data, handler)
    second = run(data, handler)
    assert first["outcome"] == "success" and second["outcome"] == "not_modified"
    assert len(calls) == 4
    assert [r["outcome"] for r in CollectionStore(data).history("synthetic")[0]["requests"]] == [
        "redirect",
        "not_modified",
    ]


@pytest.mark.parametrize(
    "location,outcome",
    [
        ("https://unrelated.invalid/feed", "redirect_denied"),
        ("http://example.invalid/feed", "redirect_denied"),
        ("/feed", "redirect_error"),
        ("https://user:pass@example.invalid/other", "redirect_error"),
    ],
)
def test_redirect_denials_never_follow_target(data, location, outcome):
    calls = []

    def handler(request):
        calls.append(request)
        return response(302, b"", Location=location)

    assert run(data, handler)["outcome"] == outcome
    assert len(calls) == 1


@pytest.mark.parametrize(
    "content,media_type,outcome",
    [
        (b"<rss>", "application/rss+xml", "parser_failure"),
        (
            b'<!DOCTYPE rss [<!ENTITY x "unsafe">]><rss><channel>'
            b"<title>&x;</title></channel></rss>",
            "application/rss+xml",
            "parser_failure",
        ),
        (HTML, "text/html", "unsupported_format"),
    ],
)
def test_bad_feed_retains_raw_diagnostic_but_no_document(data, content, media_type, outcome):
    result = run(data, lambda _: response(content=content, **{"Content-Type": media_type}))
    assert result["outcome"] == outcome
    request = CollectionStore(data).history("synthetic")[0]["requests"][0]
    with open_repository(data, read_only=True) as repository:
        assert repository.blobs.read(request["content_hash"]) == content
        assert repository.stats()["counts"]["documents"] == 0


def test_size_limits_declared_and_streamed_compression_and_total_deadline(data):
    source = definition(max_bytes=1024)
    assert (
        run(data, lambda _: response(**{"Content-Length": "2048"}), source)["outcome"]
        == "too_large"
    )
    assert run(data, lambda _: response(content=b"x" * 2048), source)["outcome"] == "too_large"
    assert (
        run(data, lambda _: response(**{"Content-Encoding": "gzip"}))["outcome"]
        == "unsupported_format"
    )
    assert run(data, lambda _: pytest.fail("deadline"), definition(total_seconds=0.000001))[
        "outcome"
    ] in {"timeout", "rate_limited"}


def test_cache_configuration_change_and_corrupt_blob_fail_explicitly(data):
    first = run(data, lambda _: response(ETag='"old"'))

    def changed(request):
        assert "if-none-match" not in request.headers
        return response()

    run(data, changed, definition(notes="Changed configuration; new snapshot"))
    assert len(CollectionStore(data).history("synthetic")) == 2
    with open_repository(data, read_only=True) as repository:
        version = repository._require("document_versions", first["document_version_id"])
        blob = repository.blobs.path(version["content_hash"])
    blob.write_bytes(b"corrupted")
    with pytest.raises(StorageError, match="hash"):
        run(data, lambda _: pytest.fail("must verify before fetching"))


@pytest.mark.parametrize("stage", ["headers", "body"])
def test_total_deadline_cancels_slow_headers_and_trickling_body(data, stage):
    class Trickle(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.01)
                yield b" "

    async def handler(request):
        if stage == "headers":
            await asyncio.sleep(2)
        return httpx.Response(
            200, headers={"Content-Type": "application/rss+xml"}, stream=Trickle()
        )

    start = time.monotonic()
    result = run(data, handler, definition(total_seconds=0.06, timeout_seconds=1))
    assert result["outcome"] == "timeout"
    assert time.monotonic() - start < 0.5
    assert result["requests"] == 1
    assert CollectionStore(data).history("synthetic")[0]["requests"][0]["outcome"] == "timeout"


def test_html_pdf_and_browser_boundaries(data):
    parsed = parse_document(HTML, "text/html", "utf-8", "http", "https://example.invalid/")
    assert "Fictional race news" in parsed.text
    assert parsed.title == "Synthetic racing news index"
    assert "window.secret" not in parsed.text and "color: red" not in parsed.text
    result = run(
        data,
        lambda _: response(content=HTML, **{"Content-Type": "text/html"}),
        definition(method="http"),
    )
    assert result["outcome"] == "success"
    pdf = parse_document(
        b"%PDF-1.4\nSynthetic placeholder",
        "application/pdf",
        "utf-8",
        "http",
        "https://example.invalid/decision.pdf",
    )
    assert pdf.text == "" and pdf.warnings
    with pytest.raises(CollectionError, match="challenge"):
        parse_document(
            b"<title>Just a moment</title>",
            "text/html",
            "utf-8",
            "http",
            "https://example.invalid/",
        )
    assert (
        run(data, lambda _: pytest.fail("browser"), definition(method="browser"))["outcome"]
        == "unsupported_method"
    )


def test_existing_phase_two_database_migrates_without_losing_evidence(tmp_path):
    initialize(tmp_path, steps=migrations()[:3])
    connection = sqlite3.connect(tmp_path / "research.sqlite3")
    connection.execute(
        "INSERT INTO sources VALUES ('old', 'old', 'Old', 'https://example.invalid/', "
        "'official', NULL, '2026-01-01T00:00:00Z')"
    )
    connection.commit()
    connection.close()
    initialize(tmp_path)
    run(tmp_path, lambda _: response())
    with open_repository(tmp_path) as repository:
        assert repository.stats()["counts"]["sources"] == 2
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            repository.connection.execute("DELETE FROM collection_runs")
    assert CollectionStore(tmp_path).history("synthetic")


def test_each_series_offline_fixture_and_cli_status(data, monkeypatch, capsys):
    catalogue = load_catalogue(ROOT / "config/sources.yaml")
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    cases = {case["source_url"]: case for case in manifest["cases"]}

    def handler(request):
        case = cases[str(request.url)]
        return response(
            content=(FIXTURES / case["file"]).read_bytes(), **{"Content-Type": case["media_type"]}
        )

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await Collector(data, client=client, sleep=lambda _: None).collect_async(
                catalogue, [case["source_key"] for case in cases.values()]
            )

    results = asyncio.run(execute())
    assert all(result["outcome"] == "success" for result in results)
    monkeypatch.setenv("DATA_DIR", str(data))
    monkeypatch.setenv("SOURCE_CATALOGUE", str(ROOT / "config/sources.yaml"))
    assert main(["collection-status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert all(value["sources_with_success"] >= 1 for value in status["coverage"].values())
    assert main(["sources"]) == 0
    assert len(json.loads(capsys.readouterr().out)["sources"]) == len(catalogue.sources)
    assert main(["collect", "--source", "unknown"]) == 2
    with TestClient(
        create_app(Settings(data_dir=data, source_catalogue=ROOT / "config/sources.yaml"))
    ) as client:
        result = client.get("/api/collection")
        assert result.status_code == 200
        assert result.json()["coverage"] == status["coverage"]
