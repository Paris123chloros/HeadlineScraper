import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from motorsport_research.cli import main
from motorsport_research.config import Settings
from motorsport_research.storage.database import Migration, StorageError, initialize, migrations
from motorsport_research.storage.models import (
    ClaimInput,
    DocumentInput,
    EntityInput,
    ExtractionRunInput,
    RecordInput,
    SourceInput,
)
from motorsport_research.storage.repository import open_repository
from motorsport_research.web.app import create_app

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/evidence.json"


def source():
    return SourceInput(key="fixture", name="Synthetic fixture", url="https://example.invalid")


def document(text="Synthetic investigation announced. Résumé 🏁", **changes):
    values = {
        "url": "https://example.invalid/notice#section",
        "content": text.encode(),
        "extracted_text": text,
        "title": "Synthetic notice",
        "parser_version": "fixture:1",
    }
    return DocumentInput(**(values | changes))


@pytest.fixture
def data(tmp_path):
    initialize(tmp_path)
    return tmp_path


def test_document_revisions_reversions_and_retrieval_audit(data):
    with open_repository(data) as repository:
        source_id = repository.register_source(source())
        first = repository.import_document(source_id, document())
        repeat = repository.import_document(source_id, document())
        changed = repository.import_document(source_id, document(title="Corrected title"))
        reverted = repository.import_document(source_id, document())
        assert first["version_id"] == repeat["version_id"]
        assert repeat["created"] is False
        assert changed["revision"] == 2
        assert reverted["revision"] == 3
        assert reverted["version_id"] != first["version_id"]
        assert repository.stats()["counts"]["documents"] == 1
        assert repository.stats()["counts"]["retrievals"] == 4
        assert len(list((data / "documents").glob("*/*.bin"))) == 1
        row = repository.connection.execute("SELECT * FROM retrievals LIMIT 1").fetchone()
        assert row["http_status"] is None
        assert row["method"] == "manual"
        repository.record_retrieval(
            source_id,
            "https://example.invalid/denied",
            outcome="denied",
            method="http",
            http_status=403,
            error="Synthetic denial",
        )
        assert repository.stats()["counts"]["document_versions"] == 3


def test_trace_unicode_offsets_provenance_and_old_evidence_survive_update(data):
    with open_repository(data) as repository:
        source_id = repository.register_source(source())
        first = repository.import_document(source_id, document())
        run = repository.record_extraction(
            ExtractionRunInput(
                document_version_id=first["version_id"],
                parser_version="fixture:1",
                model_tag="fixture-model:4b",
                model_version="synthetic-digest",
                prompt_version="fixture:1",
            )
        )
        claim = ClaimInput(
            document_version_id=first["version_id"],
            quote="Résumé 🏁",
            statement="Synthetic quote",
            extraction_run_id=run,
        )
        identity = repository.record_claim(claim)
        second_run = repository.record_extraction(
            ExtractionRunInput(document_version_id=first["version_id"], parser_version="fixture:1")
        )
        assert (
            repository.record_claim(claim.model_copy(update={"extraction_run_id": second_run}))
            == identity
        )
        repository.import_document(source_id, document("Corrected synthetic document"))
    with open_repository(data, read_only=True) as repository:
        trace = repository.trace_claim(identity)
        evidence = trace["evidence"][0]
        assert evidence["document_version_id"] == first["version_id"]
        assert evidence["quote"] == "Résumé 🏁"
        assert evidence["end_offset"] - evidence["start_offset"] == len("Résumé 🏁")
        assert evidence["canonical_url"] == "https://example.invalid/notice"
        assert evidence["published_at"] is None
        assert trace["event_at"] is None
        assert trace["assessment"]["label"] == "unassessed"
        assert len(trace["extraction_runs"]) == 2


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_historical_rows_cannot_be_rewritten(data, operation):
    with open_repository(data) as repository:
        source_id = repository.register_source(source())
        repository.import_document(source_id, document())
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        with open_repository(data) as repository:
            sql = (
                "UPDATE document_versions SET title = 'changed'"
                if operation == "UPDATE"
                else "DELETE FROM document_versions"
            )
            repository.connection.execute(sql)


def test_transaction_rolls_back_partial_import_and_rejects_bad_quote(data):
    with pytest.raises(StorageError, match="does not match"):
        with open_repository(data) as repository:
            source_id = repository.register_source(source())
            receipt = repository.import_document(source_id, document())
            repository.record_claim(
                ClaimInput(
                    document_version_id=receipt["version_id"],
                    quote="Not in source",
                    statement="Invalid",
                )
            )
    with open_repository(data, read_only=True) as repository:
        counts = repository.stats()["counts"]
        assert counts["sources"] == counts["documents"] == counts["claims"] == 0


def test_ambiguous_quote_requires_an_explicit_offset(data):
    with open_repository(data) as repository:
        source_id = repository.register_source(source())
        receipt = repository.import_document(source_id, document("Repeated. Repeated."))
    with pytest.raises(StorageError, match="ambiguous"):
        with open_repository(data) as repository:
            repository.record_claim(
                ClaimInput(
                    document_version_id=receipt["version_id"],
                    quote="Repeated.",
                    statement="Synthetic",
                )
            )
    with open_repository(data) as repository:
        identity = repository.record_claim(
            ClaimInput(
                document_version_id=receipt["version_id"],
                quote="Repeated.",
                start_offset=10,
                statement="Synthetic",
            )
        )
        assert repository.trace_claim(identity)["evidence"][0]["start_offset"] == 10


def test_entity_identity_and_conflicting_aliases_remain_visible(data):
    with open_repository(data) as repository:
        first = repository.register_entity(
            EntityInput(
                kind="driver",
                name="Driver One",
                identity_key="fixture:driver:one",
                aliases=["A Racer"],
                championship="F1",
            )
        )
        assert (
            repository.register_entity(
                EntityInput(
                    kind="driver",
                    name="New Display Name",
                    identity_key="fixture:driver:one",
                    aliases=["A Racer"],
                    championship="F1",
                )
            )
            == first
        )
        second = repository.register_entity(
            EntityInput(
                kind="driver",
                name="Driver Two",
                identity_key="fixture:driver:two",
                aliases=["A Racer"],
                championship="WEC",
            )
        )
        assert repository.resolve_alias("  a   RACER ")["status"] == "ambiguous"
        assert repository.resolve_alias("A Racer", "F1")["candidates"][0]["id"] == first
        assert repository.resolve_alias("A Racer", "WEC")["candidates"][0]["id"] == second
        assert repository.resolve_alias("New Display Name")["candidates"][0]["id"] == first
        assert repository.resolve_alias("Unknown")["status"] == "missing"


def test_migration_upgrade_preserves_data_and_failed_upgrade_is_atomic(tmp_path):
    steps = migrations()
    initialize(tmp_path, steps=steps[:2])
    connection = sqlite3.connect(tmp_path / "research.sqlite3")
    connection.execute(
        "INSERT INTO sources VALUES ('existing', 'existing', 'Existing', "
        "'https://example.invalid', "
        "'unknown', NULL, '2026-01-01T00:00:00+00:00')"
    )
    connection.commit()
    connection.close()
    assert initialize(tmp_path) == 3
    assert initialize(tmp_path) == 3
    bad = Migration(
        4,
        "004_bad.sql",
        "CREATE TABLE should_rollback(id TEXT);\nINSERT INTO missing VALUES (1);\n",
    )
    with pytest.raises(sqlite3.OperationalError):
        initialize(tmp_path, steps=(*steps, bad))
    with open_repository(tmp_path, read_only=True) as repository:
        assert repository.stats()["counts"]["sources"] == 1
        assert (
            repository.connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'should_rollback'"
            ).fetchone()
            is None
        )
        assert repository.stats()["schema_version"] == 3


def test_migration_checksums_and_newer_schema_are_rejected(data):
    connection = sqlite3.connect(data / "research.sqlite3")
    connection.execute("UPDATE schema_migrations SET checksum = 'changed' WHERE version = 1")
    connection.commit()
    connection.close()
    with pytest.raises(StorageError, match="differs"):
        initialize(data)
    clean = data / "other"
    initialize(clean)
    connection = sqlite3.connect(clean / "research.sqlite3")
    connection.execute("INSERT INTO schema_migrations VALUES (4, 'future', 'future', 'future')")
    connection.commit()
    connection.close()
    with pytest.raises(StorageError, match="newer"):
        initialize(clean)


def test_foreign_keys_and_content_integrity(data):
    with pytest.raises(StorageError, match="Unknown"):
        with open_repository(data) as repository:
            repository.import_document("missing", document())
    with open_repository(data) as repository:
        source_id = repository.register_source(source())
        receipt = repository.import_document(source_id, document())
        identity = repository.record_claim(
            ClaimInput(
                document_version_id=receipt["version_id"],
                quote="investigation",
                statement="Synthetic",
            )
        )
        trace = repository.trace_claim(identity)
        artifact = repository.blobs.path(trace["evidence"][0]["content_hash"])
    artifact.write_bytes(b"corrupted fixture")
    with pytest.raises(StorageError, match="does not match its hash"):
        with open_repository(data, read_only=True) as repository:
            repository.trace_claim(identity)
    with pytest.raises(sqlite3.IntegrityError):
        with open_repository(data) as repository:
            repository.connection.execute(
                "INSERT INTO documents VALUES ('invalid', 'missing', "
                "'https://example.invalid', 'now')"
            )


def test_announcements_cases_and_exact_parent_versions(data):
    with open_repository(data) as repository:
        source_id = repository.register_source(source())
        receipt = repository.import_document(source_id, document())
        issuer = repository.register_entity(
            EntityInput(
                kind="governing_body", name="Synthetic authority", identity_key="fixture:authority"
            )
        )
        announcement = repository.record(
            RecordInput(
                kind="announcement",
                key="fixture:notice",
                title="Synthetic announcement",
                document_version_id=receipt["version_id"],
                issuer_entity_id=issuer,
                jurisdiction="synthetic",
                parser_version="fixture:1",
            )
        )
        original = RecordInput(
            kind="controversy_case",
            key="fixture:case",
            title="Synthetic controversy",
            document_version_id=receipt["version_id"],
            parser_version="fixture:1",
            case_status="under_investigation",
            related_versions={"notice": announcement["version_id"]},
        )
        first = repository.record(original)
        assert repository.record(original)["created"] is False
        closed = repository.record(
            original.model_copy(update={"case_status": "closed", "outcome": "cleared"})
        )
        assert closed["revision"] == 2
        reopened = repository.record(original)
        assert reopened["revision"] == 3
        history = repository.record_history(first["record_id"])
        assert [entry["case_status"] for entry in history] == [
            "under_investigation",
            "closed",
            "under_investigation",
        ]
        assert history[1]["outcome"] == "cleared"
        assert history[0]["related_versions"]["notice"] == announcement["version_id"]
        assert repository.record_history(announcement["record_id"])[0]["championships"] == []
        for championship in ("F1", "WEC", "WRC", "DTM"):
            season = repository.record(
                RecordInput(
                    kind="season",
                    key=f"fixture:{championship}:season",
                    title="Synthetic season",
                    championships=[championship],
                    document_version_id=receipt["version_id"],
                    parser_version="fixture:1",
                )
            )
            repository.record(
                RecordInput(
                    kind="meeting",
                    key=f"fixture:{championship}:meeting",
                    title="Synthetic meeting",
                    championships=[championship],
                    document_version_id=receipt["version_id"],
                    related_versions={"season": season["version_id"]},
                    parser_version="fixture:1",
                )
            )


def test_record_inputs_require_evidence_and_explicit_case_outcome():
    with pytest.raises(ValidationError, match="require a source"):
        RecordInput(kind="event", key="missing", title="Missing", parser_version="test")
    with pytest.raises(ValidationError, match="explicit outcome"):
        RecordInput(
            kind="controversy_case",
            key="case",
            title="Case",
            parser_version="test",
            document_version_id="document",
            case_status="closed",
        )
    with pytest.raises(ValidationError, match="explicit timezone"):
        document(published_at="2026-01-01T12:00:00")
    with pytest.raises(ValidationError, match="HTTP response"):
        document(http_status=200)


def test_publication_offset_is_retained_and_utc_strings_sort_chronologically(data):
    with open_repository(data) as repository:
        source_id = repository.register_source(source())
        repository.import_document(source_id, document(published_at="2026-01-01T14:00:00+02:00"))
        version = repository.connection.execute("SELECT * FROM document_versions").fetchone()
        assert version["published_at"] == "2026-01-01T12:00:00.000000+00:00"
        assert version["source_timezone"] == "UTC+02:00"
        later = repository.import_document(
            source_id, document(published_at="2026-01-01T14:00:00.100000+02:00")
        )
        rows = list(
            repository.connection.execute(
                "SELECT revision FROM document_versions ORDER BY published_at"
            )
        )
        assert [row["revision"] for row in rows] == [1, later["revision"]]


def test_cli_import_is_repeatable_and_storage_health_is_independent(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        assert client.get("/health/storage").status_code == 503
        assert client.get("/health/live").status_code == 200
        assert main(["db-init"]) == 0
        assert json.loads(capsys.readouterr().out)["schema_version"] == 3
        assert main(["import-fixture", str(FIXTURE)]) == 0
        first = json.loads(capsys.readouterr().out)
        assert main(["import-fixture", str(FIXTURE)]) == 0
        second = json.loads(capsys.readouterr().out)
        assert second["document"]["version_id"] == first["document"]["version_id"]
        assert second["claim_ids"] == first["claim_ids"]
        assert main(["trace-claim", first["claim_ids"][0]]) == 0
        assert json.loads(capsys.readouterr().out)["assessment"]["label"] == "unassessed"
        status = client.get("/health/storage").json()
        assert status["counts"]["document_versions"] == 1
        assert status["counts"]["claims"] == 2
        assert status["counts"]["championships"] == 4
