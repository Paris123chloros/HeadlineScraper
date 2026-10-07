"""Official record ingestion with exact evidence, stable parents and atomic failures."""

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, Field, TypeAdapter, field_validator

from motorsport_research.championships import dtm, f1, wec, wrc
from motorsport_research.championships.common import PARSER_VERSION, OfficialDataError
from motorsport_research.championships.json_data import decode
from motorsport_research.championships.models import NoticeContext, OfficialContext, RaceContext
from motorsport_research.championships.notices import parse_notice
from motorsport_research.storage.database import StorageError
from motorsport_research.storage.models import (
    ClaimInput,
    DocumentInput,
    EntityInput,
    ExtractionRunInput,
    InputModel,
    Nonempty,
    RecordInput,
    SourceInput,
    safe_url,
    utc,
)
from motorsport_research.storage.repository import (
    identifier,
    normalized_alias,
    now,
    open_repository,
)

CONTEXT = TypeAdapter(OfficialContext)
COMPONENT_IDS = TypeAdapter(dict[Nonempty, Nonempty])
HOSTS = {
    "f1-html": {"www.formula1.com"},
    "fia-f1-pdf": {"www.fia.com"},
    "f1-standings-html": {"www.formula1.com"},
    "wec-csv": {"fiawec.alkamelsystems.com"},
    "wec-class-bundle": {"fiawec.alkamelsystems.com"},
    "dtm-json": {"api.dtm.com"},
    "wrc-json": {"p-p.redbull.com"},
    "fia-notice": {"www.fia.com"},
}


class OfficialManifest(InputModel):
    schema_version: Literal[1] = 1
    provenance: Literal["captured", "excerpt", "synthetic"]
    source: SourceInput
    url: AnyHttpUrl
    file: Nonempty
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    original_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    captured_at: datetime
    media_type: Nonempty
    context: OfficialContext

    _url = field_validator("url")(safe_url)
    _date = field_validator("captured_at")(utc)


def read_manifest(path: Path) -> tuple[OfficialManifest, bytes]:
    if path.stat().st_size > 256 * 1024:
        raise OfficialDataError("Official manifest exceeds 256 KiB")
    manifest = OfficialManifest.model_validate(decode(path.read_bytes()))
    root = path.parent.resolve()
    file = (root / manifest.file).resolve()
    if not file.is_relative_to(root) or file.stat().st_size > 10 * 1024 * 1024:
        raise OfficialDataError(
            "Official file must be below its manifest directory and at most 10 MiB"
        )
    raw = file.read_bytes()
    if hashlib.sha256(raw).hexdigest() != manifest.sha256:
        raise OfficialDataError("Official file checksum differs from the reviewed manifest")
    if manifest.provenance == "excerpt" and manifest.original_sha256 is None:
        raise OfficialDataError("Excerpts require the original response checksum")
    return manifest, raw


def parse(raw: bytes, url: str, media_type: str, context, source_kind: str, provenance: str):
    synthetic = provenance == "synthetic" and urlsplit(url).hostname == "example.invalid"
    if not synthetic and (
        source_kind != "official"
        or urlsplit(url).hostname not in HOSTS[context.adapter]
        or urlsplit(url).scheme != "https"
    ):
        raise OfficialDataError("Adapter requires a reviewed official HTTPS publisher")
    if context.adapter == "wec-class-bundle":
        return wec.parse_class_bundle(raw, url, context)
    if context.adapter == "fia-f1-pdf":
        return f1.parse_fia_classification(raw, url, context)
    if context.adapter == "fia-notice":
        return parse_notice(raw, media_type, context)
    if context.adapter == "f1-standings-html":
        return f1.parse_standings(raw, url, context)
    adapters = {"f1-html": f1, "wec-csv": wec, "wrc-json": wrc, "dtm-json": dtm}
    return adapters[context.adapter].parse_classification(raw, url, context)


def _parent(
    repo,
    kind: str,
    key: str,
    title: str,
    payload: dict,
    document_id: str,
    championship: str,
    related: dict,
):
    previous = repo.connection.execute(
        "SELECT id FROM records WHERE kind = ? AND record_key = ?", (kind, key)
    ).fetchone()
    if previous:
        latest = repo.record_history(previous["id"])[-1]
        if (
            latest["payload"] == payload
            and latest["title"] == title
            and latest["related_versions"] == related
        ):
            return latest["id"]
    return repo.record(
        RecordInput(
            kind=kind,
            key=key,
            title=title,
            payload=payload,
            document_version_id=document_id,
            championships=[championship],
            related_versions=related,
            parser_version=PARSER_VERSION,
        )
    )["version_id"]


def _persist(repo, parsed, context, document_id: str, source_name: str, provenance: dict):
    issuer = repo.register_entity(
        EntityInput(
            kind="governing_body" if isinstance(context, NoticeContext) else "organization",
            name=context.issuer if isinstance(context, NoticeContext) else source_name,
            identity_key="publisher:"
            + (context.issuer if isinstance(context, NoticeContext) else source_name),
        )
    )
    extraction = repo.record_extraction(
        ExtractionRunInput(document_version_id=document_id, parser_version=PARSER_VERSION)
    )
    payload = (
        parsed.classification.model_dump(mode="json") if parsed.classification else parsed.payload
    )
    payload = {**payload, "provenance": provenance}
    assertion = "reported"
    related = {}
    if isinstance(context, RaceContext):
        championship = context.championship
        season_key = f"{championship.lower()}:{context.season}"
        season = _parent(
            repo,
            "season",
            season_key,
            f"{championship} {context.season}",
            {"championship": championship, "year": context.season},
            document_id,
            championship,
            {},
        )
        meeting = _parent(
            repo,
            "meeting",
            context.meeting_identity,
            context.meeting_name,
            {"meeting_key": context.meeting_key, "name": context.meeting_name},
            document_id,
            championship,
            {"season": season},
        )
        session = _parent(
            repo,
            "session",
            context.session_identity,
            f"{context.session} {context.session_number}",
            {"type": context.session, "number": context.session_number},
            document_id,
            championship,
            {"meeting": meeting},
        )
        related = {"season": season, "meeting": meeting, "session": session}
        key, kind, championships = context.record_key, "classification", [championship]
    elif isinstance(context, NoticeContext):
        key, kind, championships = "fia:" + context.key, context.kind, context.championships
        related = context.related_versions
        assertion = (
            "investigation"
            if context.notice_type == "investigation_announced"
            else "decision"
            if kind == "decision"
            else "reported"
        )
    else:
        key, kind, championships = (
            f"f1:{context.season}:standings:{context.category}",
            "classification",
            ["F1"],
        )
        season = _parent(
            repo,
            "season",
            f"f1:{context.season}",
            f"F1 {context.season}",
            {"championship": "F1", "year": context.season},
            document_id,
            "F1",
            {},
        )
        related = {"season": season}
    claims, entities = [], []
    for row in payload["rows"]:
        row_entities = []
        if isinstance(context, RaceContext):
            # Numbers and crews are scoped to this meeting; names alone are not global IDs.
            car = repo.register_entity(
                EntityInput(
                    kind="car",
                    identity_key=f"{context.meeting_identity}:entry:{row['entry_number']}",
                    name=row["entry_number"],
                    championship=context.championship,
                )
            )
            row_entities.append(car)
            for role, names in (
                ("driver", row["drivers"] + ([row["co_driver"]] if row["co_driver"] else [])),
                ("team", [row["team"]] if row["team"] else []),
                ("manufacturer", [row["manufacturer"]] if row["manufacturer"] else []),
            ):
                for name in names:
                    row_entities.append(
                        repo.register_entity(
                            EntityInput(
                                kind=role,
                                name=name,
                                identity_key=f"{context.meeting_identity}:{role}:published:{normalized_alias(name)}",
                                championship=context.championship,
                            )
                        )
                    )
            if len(row["drivers"]) > 1:
                row_entities.append(
                    repo.register_entity(
                        EntityInput(
                            kind="crew",
                            name=" / ".join(row["drivers"]),
                            identity_key=f"{context.meeting_identity}:crew:{row['entry_number']}:"
                            + "/".join(row["drivers"]),
                            championship=context.championship,
                        )
                    )
                )
        claim = repo.record_claim(
            ClaimInput(
                document_version_id=document_id,
                statement=row["quote"],
                quote=row["quote"],
                start_offset=row["start_offset"],
                assertion_type=assertion,
                asserted_by_entity_id=issuer,
                entity_ids=row_entities,
                extraction_run_id=extraction,
            )
        )
        row["claim_id"] = claim
        claims.append(claim)
        entities.extend(row_entities)
    record = repo.record(
        RecordInput(
            kind=kind,
            key=key,
            title=parsed.title,
            payload=payload,
            document_version_id=document_id,
            championships=championships,
            issuer_entity_id=issuer,
            jurisdiction=context.jurisdiction
            if isinstance(context, NoticeContext)
            else context.championship,
            entity_ids=entities,
            claim_ids=claims,
            related_versions=related,
            parser_version=PARSER_VERSION,
        )
    )
    return record, claims


class OfficialService:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def _audit(self, context, outcome, *, origin=None, document=None, record=None, error=None):
        with open_repository(self.data_dir) as repo:
            identity = identifier("official_ingestion")
            repo.connection.execute(
                "INSERT INTO official_ingestions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identity,
                    origin,
                    document,
                    context.adapter,
                    PARSER_VERSION,
                    context.model_dump_json(),
                    outcome,
                    error,
                    record,
                    now(),
                ),
            )
            return identity

    def _ingest(self, source, raw, url, media_type, context, captured_at, provenance, origin=None):
        try:
            parsed = parse(raw, url, media_type, context, source.kind, provenance["kind"])
            with open_repository(self.data_dir) as repo:
                source_id = repo.register_source(source)
                document = repo.import_document(
                    source_id,
                    DocumentInput(
                        url=url,
                        content=raw,
                        extracted_text=parsed.text,
                        title=parsed.title,
                        parser_version=PARSER_VERSION,
                        media_type=media_type,
                        retrieved_at=captured_at,
                        retrieval_method="fixture"
                        if provenance["kind"] in {"captured", "excerpt", "synthetic"}
                        else "manual",
                    ),
                )
                record, claims = _persist(
                    repo, parsed, context, document["version_id"], source.name, provenance
                )
                identity = identifier("official_ingestion")
                repo.connection.execute(
                    "INSERT INTO official_ingestions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        identity,
                        origin,
                        document["version_id"],
                        context.adapter,
                        PARSER_VERSION,
                        context.model_dump_json(),
                        "success",
                        None,
                        record["version_id"],
                        now(),
                    ),
                )
            return {
                "ingestion_id": identity,
                "document": document,
                "record": record,
                "claim_ids": claims,
            }
        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            IndexError,
            ArithmeticError,
            OSError,
            StorageError,
            sqlite3.Error,
        ) as error:
            # Keep errors actionable without echoing source-controlled values or SQL parameters.
            detail = (
                str(error)
                if isinstance(error, OfficialDataError)
                else type(error).__name__ + ": invalid official input"
            )
            audit = self._audit(context, "failed", origin=origin, error=detail)
            raise OfficialDataError(f"{detail}; failed ingestion {audit}") from error

    def import_manifest(self, path: Path):
        manifest, raw = read_manifest(path)
        return self._ingest(
            manifest.source,
            raw,
            str(manifest.url),
            manifest.media_type,
            manifest.context,
            manifest.captured_at,
            {"kind": manifest.provenance, "original_sha256": manifest.original_sha256},
        )

    def normalize(self, version_id: str, context):
        context = CONTEXT.validate_python(context)
        with open_repository(self.data_dir, read_only=True) as repo:
            version = repo._require("document_versions", version_id)
            document = repo._require("documents", version["document_id"])
            source = repo._require("sources", document["source_id"])
            raw = repo.blobs.read(version["content_hash"])
            args = (
                SourceInput(
                    key=source["source_key"],
                    name=source["name"],
                    url=source["url"],
                    kind=source["kind"],
                    upstream_source_id=source["upstream_source_id"],
                ),
                raw,
                document["canonical_url"],
                version["media_type"],
                context,
                datetime.fromisoformat(version["first_retrieved_at"]),
                {"kind": "archived_document", "original_sha256": None},
                version_id,
            )
        return self._ingest(*args)

    def status(self, limit: int = 50):
        with open_repository(self.data_dir, read_only=True) as repo:
            return [
                dict(row)
                for row in repo.connection.execute(
                    "SELECT id, origin_document_version_id, document_version_id, adapter, "
                    "parser_version, outcome, error, record_version_id, created_at "
                    "FROM official_ingestions ORDER BY created_at DESC, id DESC LIMIT ?",
                    (limit,),
                )
            ]

    def bundle_wrc(self, version_ids: dict[str, str], context):
        """Archive an explicit reviewed set of already-collected API documents."""
        context = CONTEXT.validate_python(context)
        version_ids = COMPONENT_IDS.validate_python(version_ids)
        if not isinstance(context, RaceContext) or context.adapter != "wrc-json":
            raise OfficialDataError("WRC bundle requires WRC classification context")
        required = {"event", "entries", "results"} | (
            {"stages"} if context.session == "stage" else set()
        )
        if not required.issubset(version_ids) or set(version_ids) - required - {"retirements"}:
            raise OfficialDataError("WRC component roles are incomplete or unrecognized")
        components = {}
        with open_repository(self.data_dir, read_only=True) as repo:
            for role, version_id in version_ids.items():
                version = repo._require("document_versions", version_id)
                document = repo._require("documents", version["document_id"])
                source_row = repo._require("sources", document["source_id"])
                if source_row["kind"] != "official":
                    raise OfficialDataError("WRC components require official source attribution")
                raw = repo.blobs.read(version["content_hash"])
                components[role] = {
                    "url": document["canonical_url"],
                    "sha256": version["content_hash"],
                    "content": raw.decode("utf-8"),
                }
                if role == "event":
                    source = SourceInput(
                        key=source_row["source_key"],
                        name=source_row["name"],
                        url=source_row["url"],
                        kind="official",
                        upstream_source_id=source_row["upstream_source_id"],
                    )
                    captured_at = datetime.fromisoformat(version["first_retrieved_at"])
        from motorsport_research.championships.json_data import quote

        raw = quote({"format": "wrc-public-api:1", "components": components}).encode()
        # The assembly is an explicit manual transformation, not a fabricated HTTP response.
        return self._ingest(
            source,
            raw,
            components["event"]["url"],
            "application/json",
            context,
            captured_at,
            {"kind": "api_bundle", "component_versions": version_ids},
            version_ids["event"],
        )

    def bundle_wec(self, version_ids: dict[str, str], context):
        context = CONTEXT.validate_python(context)
        version_ids = COMPONENT_IDS.validate_python(version_ids)
        if (
            not isinstance(context, RaceContext)
            or context.adapter != "wec-class-bundle"
            or set(version_ids) != {"csv", "classification"}
        ):
            raise OfficialDataError(
                "WEC class archive requires csv/classification versions and class context"
            )
        components = {}
        with open_repository(self.data_dir, read_only=True) as repo:
            for role, version_id in version_ids.items():
                version = repo._require("document_versions", version_id)
                document = repo._require("documents", version["document_id"])
                source_row = repo._require("sources", document["source_id"])
                if source_row["kind"] != "official":
                    raise OfficialDataError("WEC components require official source attribution")
                raw = repo.blobs.read(version["content_hash"])
                components[role] = {
                    "url": document["canonical_url"],
                    "sha256": version["content_hash"],
                    "content": raw.decode("utf-8"),
                }
                if role == "csv":
                    source = SourceInput(
                        key=source_row["source_key"],
                        name=source_row["name"],
                        url=source_row["url"],
                        kind="official",
                        upstream_source_id=source_row["upstream_source_id"],
                    )
                    captured_at = datetime.fromisoformat(version["first_retrieved_at"])
        from motorsport_research.championships.json_data import quote

        raw = quote({"format": "wec-class-bundle:1", "components": components}).encode()
        return self._ingest(
            source,
            raw,
            components["csv"]["url"],
            "application/json",
            context,
            captured_at,
            {"kind": "api_bundle", "component_versions": version_ids},
            version_ids["csv"],
        )
