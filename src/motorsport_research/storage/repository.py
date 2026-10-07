"""Transactional source records, immutable revisions, identity, and evidence links."""

import hashlib
import json
import sqlite3
import unicodedata
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from motorsport_research.storage.blobs import BlobStore
from motorsport_research.storage.database import StorageError, connect, migrations, schema_version
from motorsport_research.storage.models import (
    Championship,
    ClaimInput,
    DocumentInput,
    EntityInput,
    EvidenceInput,
    ExtractionRunInput,
    RecordInput,
    SourceInput,
    canonical_url,
    timestamp,
)

COUNT_TABLES = (
    "sources",
    "documents",
    "document_versions",
    "retrievals",
    "championships",
    "entities",
    "claims",
    "records",
    "record_versions",
    "extraction_runs",
    "jobs",
    "source_configurations",
    "collection_runs",
    "collection_requests",
    "discovered_links",
)


def identifier(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def fingerprint(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def normalized_alias(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class Repository:
    def __init__(self, connection: sqlite3.Connection, data_dir: Path):
        self.connection = connection
        self.blobs = BlobStore(data_dir / "documents")

    def _require(self, table: str, identity: str) -> sqlite3.Row:
        row = self.connection.execute(f"SELECT * FROM {table} WHERE id = ?", (identity,)).fetchone()
        if row is None:
            raise StorageError(f"Unknown {table} reference: {identity}")
        return row

    def register_source(self, source: SourceInput) -> str:
        source = SourceInput.model_validate(source)
        values = (source.name, canonical_url(source.url), source.kind, source.upstream_source_id)
        existing = self.connection.execute(
            "SELECT * FROM sources WHERE source_key = ?", (source.key,)
        ).fetchone()
        if existing is not None:
            if (
                tuple(existing[key] for key in ("name", "url", "kind", "upstream_source_id"))
                != values
            ):
                raise StorageError("Source key already exists with different attribution metadata")
            return existing["id"]
        identity = identifier("source")
        self.connection.execute(
            "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?)",
            (identity, source.key, *values, now()),
        )
        return identity

    def import_document(self, source_id: str, document: DocumentInput) -> dict:
        document = DocumentInput.model_validate(document)
        self._require("sources", source_id)
        url = canonical_url(document.url)
        content_hash = self.blobs.put(document.content)
        text_hash = hashlib.sha256(document.extracted_text.encode()).hexdigest()
        metadata = document.model_dump(
            mode="json",
            exclude={
                "content",
                "extracted_text",
                "retrieved_at",
                "url",
                "retrieval_method",
                "http_status",
            },
        )
        metadata["published_at"] = timestamp(document.published_at)
        revision_hash = fingerprint(
            {**metadata, "content_hash": content_hash, "text_hash": text_hash}
        )
        existing = self.connection.execute(
            "SELECT id FROM documents WHERE source_id = ? AND canonical_url = ?",
            (source_id, url),
        ).fetchone()
        document_id = existing["id"] if existing else identifier("document")
        if existing is None:
            self.connection.execute(
                "INSERT INTO documents VALUES (?, ?, ?, ?)", (document_id, source_id, url, now())
            )
        latest = self.connection.execute(
            "SELECT * FROM document_versions WHERE document_id = ? ORDER BY revision DESC LIMIT 1",
            (document_id,),
        ).fetchone()
        created = latest is None or latest["revision_hash"] != revision_hash
        if created:
            revision = latest["revision"] + 1 if latest else 1
            version_id = identifier("document_version")
            self.connection.execute(
                "INSERT INTO document_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    version_id,
                    document_id,
                    revision,
                    revision_hash,
                    content_hash,
                    text_hash,
                    document.extracted_text,
                    document.title,
                    document.author,
                    timestamp(document.published_at),
                    document.source_timezone,
                    document.parser_version,
                    document.media_type,
                    timestamp(document.retrieved_at),
                ),
            )
        else:
            revision, version_id = latest["revision"], latest["id"]
        attempt_id = self.record_retrieval(
            source_id,
            url,
            outcome="success",
            document_version_id=version_id,
            retrieved_at=document.retrieved_at,
            http_status=document.http_status,
            method=document.retrieval_method,
        )
        return {
            "document_id": document_id,
            "version_id": version_id,
            "revision": revision,
            "created": created,
            "retrieval_id": attempt_id,
        }

    def record_retrieval(
        self,
        source_id: str,
        url: str,
        *,
        outcome: str,
        document_version_id: str | None = None,
        retrieved_at: datetime | None = None,
        http_status: int | None = None,
        error: str | None = None,
        method: str = "manual",
    ) -> str:
        from pydantic import AnyHttpUrl

        from motorsport_research.storage.models import utc

        self._require("sources", source_id)
        if document_version_id is not None:
            version = self._require("document_versions", document_version_id)
            document = self._require("documents", version["document_id"])
            if document["source_id"] != source_id:
                raise StorageError("Retrieval source does not match its document version")
        retrieved_at = utc(retrieved_at) if retrieved_at is not None else datetime.now(UTC)
        identity = identifier("retrieval")
        self.connection.execute(
            "INSERT INTO retrievals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                identity,
                source_id,
                canonical_url(AnyHttpUrl(url)),
                timestamp(retrieved_at),
                method,
                outcome,
                http_status,
                error,
                document_version_id,
                now(),
            ),
        )
        return identity

    def register_entity(self, entity: EntityInput) -> str:
        entity = EntityInput.model_validate(entity)
        existing = None
        if entity.identity_key is not None:
            existing = self.connection.execute(
                "SELECT id FROM entities WHERE kind = ? AND identity_key = ?",
                (entity.kind, entity.identity_key),
            ).fetchone()
        identity = existing["id"] if existing else identifier("entity")
        if existing is None:
            self.connection.execute(
                "INSERT INTO entities VALUES (?, ?, ?, ?, ?)",
                (identity, entity.kind, entity.identity_key, entity.name, now()),
            )
        for alias in [entity.name, *entity.aliases]:
            self.connection.execute(
                "INSERT OR IGNORE INTO entity_aliases VALUES (?, ?, ?, ?)",
                (identity, alias, normalized_alias(alias), entity.championship),
            )
        return identity

    def resolve_alias(self, alias: str, championship: Championship | None = None) -> dict:
        candidates = [
            dict(row)
            for row in self.connection.execute(
                "SELECT DISTINCT entities.* FROM entities JOIN entity_aliases "
                "ON entities.id = entity_aliases.entity_id WHERE normalized_alias = ? "
                "AND (? IS NULL OR championship_id IS NULL OR championship_id = ?) ORDER BY id",
                (normalized_alias(alias), championship, championship),
            )
        ]
        status = "missing" if not candidates else "unique" if len(candidates) == 1 else "ambiguous"
        return {"status": status, "candidates": candidates}

    def record_extraction(self, extraction: ExtractionRunInput) -> str:
        extraction = ExtractionRunInput.model_validate(extraction)
        self._require("document_versions", extraction.document_version_id)
        identity = identifier("extraction")
        self.connection.execute(
            "INSERT INTO extraction_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                identity,
                extraction.document_version_id,
                extraction.parser_version,
                extraction.model_tag,
                extraction.model_version,
                extraction.prompt_version,
                extraction.status,
                now(),
            ),
        )
        return identity

    def _span(self, evidence: EvidenceInput) -> tuple[int, int]:
        evidence = EvidenceInput(
            **{field: getattr(evidence, field) for field in EvidenceInput.model_fields}
        )
        version = self._require("document_versions", evidence.document_version_id)
        self.blobs.read(version["content_hash"])
        text = version["extracted_text"]
        if hashlib.sha256(text.encode()).hexdigest() != version["text_hash"]:
            raise StorageError("Stored extracted text does not match its hash")
        start = evidence.start_offset
        if start is None:
            start = text.find(evidence.quote)
            if start >= 0 and text.find(evidence.quote, start + 1) >= 0:
                raise StorageError("Evidence quote is ambiguous; provide start_offset")
        end = start + len(evidence.quote)
        if start < 0 or text[start:end] != evidence.quote:
            raise StorageError("Evidence quote does not match its document version")
        return start, end

    def add_evidence(self, claim_id: str, evidence: EvidenceInput) -> None:
        self._require("claims", claim_id)
        start, end = self._span(evidence)
        self.connection.execute(
            "INSERT OR IGNORE INTO claim_evidence VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                identifier("evidence"),
                claim_id,
                evidence.document_version_id,
                evidence.quote,
                start,
                end,
                evidence.relation,
            ),
        )

    def record_claim(self, claim: ClaimInput) -> str:
        claim = ClaimInput.model_validate(claim)
        start, end = self._span(claim)
        for entity_id in [*claim.entity_ids, claim.asserted_by_entity_id]:
            if entity_id is not None:
                self._require("entities", entity_id)
        if claim.supersedes_claim_id is not None:
            self._require("claims", claim.supersedes_claim_id)
        if claim.extraction_run_id:
            extraction = self._require("extraction_runs", claim.extraction_run_id)
            if extraction["document_version_id"] != claim.document_version_id:
                raise StorageError("Extraction run does not refer to the evidence document version")
            if extraction["status"] != "success":
                raise StorageError("Failed extraction runs cannot produce accepted claims")
        values = claim.model_dump(mode="json", exclude={"extraction_run_id", "entity_ids"})
        for field in ("event_at", "effective_at"):
            values[field] = timestamp(getattr(claim, field))
        values.update(start_offset=start, end_offset=end, entity_ids=sorted(set(claim.entity_ids)))
        identity_hash = fingerprint(values)
        existing = self.connection.execute(
            "SELECT id FROM claims WHERE identity_hash = ?", (identity_hash,)
        ).fetchone()
        identity = existing["id"] if existing else identifier("claim")
        if existing is None:
            self.connection.execute(
                "INSERT INTO claims VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identity,
                    identity_hash,
                    claim.statement,
                    claim.assertion_type,
                    claim.asserted_by_entity_id,
                    claim.supersedes_claim_id,
                    timestamp(claim.event_at),
                    timestamp(claim.effective_at),
                    now(),
                ),
            )
            for entity_id in set(claim.entity_ids):
                self.connection.execute(
                    "INSERT INTO claim_entities VALUES (?, ?)", (identity, entity_id)
                )
        self.add_evidence(identity, claim)
        if claim.extraction_run_id:
            self.connection.execute(
                "INSERT OR IGNORE INTO claim_extraction_runs VALUES (?, ?)",
                (identity, claim.extraction_run_id),
            )
        return identity

    def trace_claim(self, claim_id: str) -> dict:
        claim = dict(self._require("claims", claim_id))
        evidence = []
        for row in self.connection.execute(
            "SELECT e.*, v.document_id, v.revision, v.content_hash, v.text_hash, "
            "v.extracted_text, v.title, v.author, v.published_at, v.first_retrieved_at, "
            "v.source_timezone, v.parser_version, d.canonical_url, "
            "s.name AS source_name, s.kind AS source_kind, s.upstream_source_id "
            "FROM claim_evidence e JOIN document_versions v ON v.id = e.document_version_id "
            "JOIN documents d ON d.id = v.document_id JOIN sources s ON s.id = d.source_id "
            "WHERE claim_id = ? ORDER BY e.id",
            (claim_id,),
        ):
            self._span(
                EvidenceInput(
                    document_version_id=row["document_version_id"],
                    quote=row["quote"],
                    start_offset=row["start_offset"],
                    relation=row["relation"],
                )
            )
            evidence.append({key: row[key] for key in row.keys() if key != "extracted_text"})
        extraction_runs = [
            dict(row)
            for row in self.connection.execute(
                "SELECT r.* FROM extraction_runs r JOIN claim_extraction_runs c "
                "ON r.id = c.extraction_run_id WHERE c.claim_id = ? ORDER BY r.created_at, r.id",
                (claim_id,),
            )
        ]
        assessment = self.connection.execute(
            "SELECT label, rationale FROM claim_assessments WHERE claim_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (claim_id,),
        ).fetchone()
        return {
            **claim,
            "evidence": evidence,
            "extraction_runs": extraction_runs,
            "assessment": dict(assessment) if assessment else {"label": "unassessed"},
        }

    def record(self, record: RecordInput) -> dict:
        record = RecordInput.model_validate(record)
        if record.document_version_id is not None:
            self._require("document_versions", record.document_version_id)
        for entity_id in [*record.entity_ids, record.issuer_entity_id]:
            if entity_id is not None:
                self._require("entities", entity_id)
        for claim_id in record.claim_ids:
            self._require("claims", claim_id)
        for relation, version_id in record.related_versions.items():
            related = self._require("record_versions", version_id)
            parent = self._require("records", related["record_id"])
            if relation in {"season", "meeting", "session"} and parent["kind"] != relation:
                raise StorageError("Hierarchy link does not match its related record kind")
        data = record.model_dump(mode="json")
        for field in ("published_at", "event_at", "effective_at"):
            data[field] = timestamp(getattr(record, field))
        for field in ("championships", "entity_ids", "claim_ids"):
            data[field] = sorted(set(data[field]))
        revision_hash = fingerprint(data)
        existing = self.connection.execute(
            "SELECT id FROM records WHERE kind = ? AND record_key = ?", (record.kind, record.key)
        ).fetchone()
        record_id = existing["id"] if existing else identifier("record")
        if existing is None:
            self.connection.execute(
                "INSERT INTO records VALUES (?, ?, ?, ?)",
                (record_id, record.kind, record.key, now()),
            )
        latest = self.connection.execute(
            "SELECT * FROM record_versions WHERE record_id = ? ORDER BY revision DESC LIMIT 1",
            (record_id,),
        ).fetchone()
        if latest is not None and latest["revision_hash"] == revision_hash:
            return {
                "record_id": record_id,
                "version_id": latest["id"],
                "revision": latest["revision"],
                "created": False,
            }
        version_id = identifier("record_version")
        revision = latest["revision"] + 1 if latest else 1
        self.connection.execute(
            "INSERT INTO record_versions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                version_id,
                record_id,
                revision,
                revision_hash,
                record.title,
                json.dumps(record.payload, sort_keys=True, ensure_ascii=False, allow_nan=False),
                record.document_version_id,
                record.issuer_entity_id,
                record.jurisdiction,
                record.case_status,
                record.outcome,
                data["published_at"],
                data["event_at"],
                data["effective_at"],
                record.parser_version,
                now(),
            ),
        )
        for table, field in (
            ("record_championships", "championships"),
            ("record_entities", "entity_ids"),
            ("record_claims", "claim_ids"),
        ):
            for value in data[field]:
                self.connection.execute(f"INSERT INTO {table} VALUES (?, ?)", (version_id, value))
        for relation, related_version in record.related_versions.items():
            self.connection.execute(
                "INSERT INTO record_links VALUES (?, ?, ?)", (version_id, related_version, relation)
            )
        return {
            "record_id": record_id,
            "version_id": version_id,
            "revision": revision,
            "created": True,
        }

    def record_history(self, record_id: str) -> list[dict]:
        self._require("records", record_id)
        history = []
        for row in self.connection.execute(
            "SELECT * FROM record_versions WHERE record_id = ? ORDER BY revision", (record_id,)
        ):
            value = dict(row)
            value["payload"] = json.loads(value.pop("payload_json"))
            for table, key, field in (
                ("record_championships", "championship_id", "championships"),
                ("record_entities", "entity_id", "entity_ids"),
                ("record_claims", "claim_id", "claim_ids"),
            ):
                value[field] = [
                    link[key]
                    for link in self.connection.execute(
                        f"SELECT {key} FROM {table} WHERE record_version_id = ? ORDER BY {key}",
                        (row["id"],),
                    )
                ]
            value["related_versions"] = {
                link["relation"]: link["related_version_id"]
                for link in self.connection.execute(
                    "SELECT * FROM record_links WHERE record_version_id = ?", (row["id"],)
                )
            }
            history.append(value)
        return history

    def stats(self) -> dict:
        return {
            "status": "ready",
            "schema_version": schema_version(self.connection, migrations()),
            "counts": {
                table: self.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in COUNT_TABLES
            },
        }


@contextmanager
def open_repository(data_dir: Path, *, read_only: bool = False) -> Iterator[Repository]:
    connection = connect(data_dir, read_only=read_only)
    try:
        expected = migrations()
        if schema_version(connection, expected) != len(expected):
            raise StorageError("Storage has pending migrations; run motorsport-research db-init")
        connection.execute("BEGIN" if read_only else "BEGIN IMMEDIATE")
        yield Repository(connection, data_dir)
        connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()
