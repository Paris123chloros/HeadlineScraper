"""Manual article preparation, immutable analysis, and inspectable failure attempts."""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, field_validator

from motorsport_research.championships.json_data import decode
from motorsport_research.extraction.articles import (
    MAX_BYTES,
    PARSER_VERSION,
    ArticleError,
    parse_article,
)
from motorsport_research.extraction.relevance import RULES_VERSION, classify
from motorsport_research.sources.parsers import PageText
from motorsport_research.storage.database import StorageError
from motorsport_research.storage.models import (
    DocumentInput,
    InputModel,
    Nonempty,
    SourceInput,
    safe_url,
    utc,
)
from motorsport_research.storage.repository import fingerprint, identifier, now, open_repository


class ArticleManifest(InputModel):
    schema_version: Literal[1] = 1
    provenance: Literal["captured", "excerpt", "synthetic"]
    source: SourceInput
    url: AnyHttpUrl
    file: Nonempty
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    original_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    captured_at: datetime
    media_type: Literal["text/html", "application/xhtml+xml", "text/plain"] = "text/html"
    encoding: Nonempty = "utf-8"
    title: Nonempty | None = None

    _url = field_validator("url")(safe_url)
    _date = field_validator("captured_at")(utc)


def _origin(repo, version_id):
    version = dict(repo._require("document_versions", version_id))
    document = dict(repo._require("documents", version["document_id"]))
    source = dict(repo._require("sources", document["source_id"]))
    raw = repo.blobs.read(version["content_hash"])
    if hashlib.sha256(version["extracted_text"].encode()).hexdigest() != version["text_hash"]:
        raise StorageError("Archived source text differs from its hash")
    return version, document, source, raw


def _aliases(repo):
    rows = repo.connection.execute(
        "SELECT a.alias, a.normalized_alias, a.entity_id, a.championship_id, e.kind, e.name "
        "FROM entity_aliases a JOIN entities e ON e.id = a.entity_id "
        "ORDER BY a.normalized_alias, a.alias, a.entity_id, a.championship_id LIMIT 10001"
    ).fetchall()
    if len(rows) > 10000:
        raise ArticleError("parser_failure", "Entity registry exceeds 10000 aliases")
    aliases = {}
    for row in rows:
        aliases.setdefault(row["normalized_alias"], []).append(
            {key: row[key] for key in ("entity_id", "championship_id", "kind", "name")}
        )
    return aliases


def _verify(article, source_text):
    for block in article["blocks"]:
        if article["body"][block["body_start"] : block["body_end"]] != block["text"]:
            raise StorageError("Stored article block differs from its body")
        for span in block["spans"]:
            if source_text[span["start_offset"] : span["end_offset"]] != span["quote"]:
                raise StorageError("Stored article span differs from its source")
            if article["body"][span["body_start"] : span["body_end"]] != " ".join(
                span["quote"].split()
            ):
                raise StorageError("Stored article span differs from its clean text")


class ArticleService:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def collect_article(self, catalogue, source_key, url, *, force=False):
        from motorsport_research.sources.catalogue import Catalogue, SourceDefinition
        from motorsport_research.sources.collector import Collector

        original = catalogue.select([source_key])[0]
        requested = safe_url(AnyHttpUrl(url))
        if requested.host not in original.hosts or requested.scheme != original.url.scheme:
            raise ValueError("Article URL must use the configured source scheme and approved hosts")
        if original.method == "browser":
            raise ValueError("Browser sources require a supported browser adapter")
        selected = SourceDefinition.model_validate(
            original.model_dump(mode="json") | {"url": str(requested), "method": "http"}
        )
        scoped = Catalogue(
            sources=[selected if s.key == source_key else s for s in catalogue.sources]
        )
        collection = Collector(self.data_dir).collect(scoped, [source_key], force=force)[0]
        if collection["outcome"] not in {"success", "not_modified"}:
            return {"outcome": collection["outcome"], "collection": collection, "article": None}
        article = self.parse(collection["document_version_id"])
        return {"outcome": article["outcome"], "collection": collection, "article": article}

    def import_manifest(self, path: Path):
        if path.stat().st_size > 256 * 1024:
            raise ValueError("Article manifest exceeds 256 KiB")
        manifest = ArticleManifest.model_validate(decode(path.read_bytes()))
        root = path.parent.resolve()
        file = (root / manifest.file).resolve()
        if not file.is_relative_to(root) or file.stat().st_size > MAX_BYTES:
            raise ValueError("Article file must be below its manifest and at most 10 MiB")
        raw = file.read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest.sha256:
            raise ValueError("Article file checksum differs from the manifest")
        if manifest.provenance == "excerpt" and manifest.original_sha256 is None:
            raise ValueError("Article excerpts require the original response checksum")
        try:
            text = raw.decode(manifest.encoding)
        except (UnicodeError, LookupError) as error:
            raise ValueError("Article file encoding is invalid; check the manifest") from error
        if manifest.media_type != "text/plain":
            tree = PageText()
            tree.feed(text)
            text = "\n".join(tree.parts)
            title = manifest.title or " ".join(tree.title) or str(manifest.url)
        else:
            title = manifest.title or str(manifest.url)
        # Archive even malformed/index pages so their parse failures remain visible.
        with open_repository(self.data_dir) as repo:
            source_id = repo.register_source(manifest.source)
            receipt = repo.import_document(
                source_id,
                DocumentInput(
                    url=manifest.url,
                    content=raw,
                    extracted_text=text,
                    title=title,
                    parser_version="collection:2",
                    retrieved_at=manifest.captured_at,
                    retrieval_method="fixture",
                    media_type=manifest.media_type,
                ),
            )
        return {
            "document": receipt,
            **self.parse(
                receipt["version_id"],
                encoding=manifest.encoding,
                provenance={
                    "kind": manifest.provenance,
                    "sha256": manifest.sha256,
                    "original_sha256": manifest.original_sha256,
                },
            ),
        }

    def parse(self, version_id: str, *, encoding="utf-8", provenance=None):
        try:
            with open_repository(self.data_dir, read_only=True) as repo:
                version, document, source, raw = _origin(repo, version_id)
                aliases = _aliases(repo)
            parsed = parse_article(
                raw,
                version["media_type"],
                document["canonical_url"],
                version["extracted_text"],
                version["title"],
                encoding,
            )
            parsed.update(classify(parsed, source, aliases))
            parsed["origin"] = {
                "document_version_id": version_id,
                "content_hash": version["content_hash"],
                "text_hash": version["text_hash"],
                "source_id": source["id"],
                "source_name": source["name"],
                "source_kind": source["kind"],
                "upstream_source_id": source["upstream_source_id"],
                "url": document["canonical_url"],
                "first_retrieved_at": version["first_retrieved_at"],
                "document_revision": version["revision"],
            }
            parsed["provenance"] = provenance or {"kind": "archived_document"}
            registry_hash = fingerprint(
                {"aliases": aliases, "encoding": encoding, "provenance": parsed["provenance"]}
            )
            outcome = parsed["relevance"]["status"]
            _verify(parsed, version["extracted_text"])
            with open_repository(self.data_dir) as repo:
                existing = repo.connection.execute(
                    "SELECT id FROM article_parses WHERE document_version_id = ? "
                    "AND parser_version = ? AND rules_version = ? AND registry_hash = ?",
                    (version_id, PARSER_VERSION, RULES_VERSION, registry_hash),
                ).fetchone()
                article_id = existing["id"] if existing else identifier("article")
                if not existing:
                    repo.connection.execute(
                        "INSERT INTO article_parses VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            article_id,
                            version_id,
                            PARSER_VERSION,
                            RULES_VERSION,
                            registry_hash,
                            parsed["body_hash"],
                            outcome,
                            json.dumps(parsed, ensure_ascii=False),
                            now(),
                        ),
                    )
                attempt_id = self._attempt(repo, version_id, outcome, article_id)
            return {
                "outcome": outcome,
                "article_id": article_id,
                "created": not bool(existing),
                "attempt_id": attempt_id,
                "document_version_id": version_id,
                "title": parsed["title"],
                "warnings": parsed["warnings"],
            }
        except ArticleError as error:
            with open_repository(self.data_dir) as repo:
                attempt_id = self._attempt(repo, version_id, error.outcome, detail=str(error))
            return {
                "outcome": error.outcome,
                "document_version_id": version_id,
                "attempt_id": attempt_id,
                "detail": str(error),
                "article_id": None,
            }

    @staticmethod
    def _attempt(repo, version_id, outcome, article_id=None, detail=None):
        identity = identifier("article_attempt")
        repo.connection.execute(
            "INSERT INTO article_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                identity,
                version_id,
                PARSER_VERSION,
                RULES_VERSION,
                outcome,
                article_id,
                detail,
                now(),
            ),
        )
        return identity

    def detail(self, article_id):
        with open_repository(self.data_dir, read_only=True) as repo:
            row = dict(repo._require("article_parses", article_id))
            result = json.loads(row.pop("result_json"))
            version, _, _, _ = _origin(repo, row["document_version_id"])
            _verify(result, version["extracted_text"])
            copies = []
            # Exact normalized body equality is only a copy hint, never corroboration.
            if len(result["body"].split()) >= 40:
                for peer in repo.connection.execute(
                    "SELECT a.id, a.document_version_id, a.result_json, d.source_id, "
                    "d.id AS document_id, d.canonical_url, s.name, s.upstream_source_id "
                    "FROM article_parses a JOIN document_versions v "
                    "ON v.id = a.document_version_id "
                    "JOIN documents d ON d.id = v.document_id JOIN sources s ON s.id = d.source_id "
                    "WHERE a.body_hash = ? AND a.id != ? ORDER BY a.created_at DESC LIMIT 51",
                    (row["body_hash"], article_id),
                ):
                    peer_result = json.loads(peer["result_json"])
                    origin = result["origin"]
                    if peer["document_version_id"] == row["document_version_id"]:
                        continue
                    shared = (peer["upstream_source_id"] or peer["source_id"]) == (
                        origin["upstream_source_id"] or origin["source_id"]
                    )
                    relation = (
                        "unchanged_body_revision"
                        if peer["document_id"] == version["document_id"]
                        else "same_publisher_copy"
                        if peer["source_id"] == origin["source_id"]
                        else "shared_upstream_copy"
                        if shared
                        else "possible_syndication"
                    )
                    copies.append(
                        {
                            "article_id": peer["id"],
                            "document_version_id": peer["document_version_id"],
                            "source_id": peer["source_id"],
                            "source_name": peer["name"],
                            "url": peer["canonical_url"],
                            "relation": relation,
                            "basis": "identical body after whitespace normalization",
                            "independence": "shared_upstream" if shared else "unassessed",
                            "title": peer_result["title"],
                        }
                    )
            return {
                **row,
                **result,
                "duplicate_candidates": copies[:50],
                "duplicate_candidates_truncated": len(copies) > 50,
                "evidence_verified": True,
            }

    def status(self, *, limit=50, offset=0):
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("Use limit 1..100 and a nonnegative offset")
        with open_repository(self.data_dir, read_only=True) as repo:
            counts = {
                row["outcome"]: row["n"]
                for row in repo.connection.execute(
                    "SELECT outcome, count(*) AS n FROM article_attempts GROUP BY outcome"
                )
            }
            attempts = [
                dict(row)
                for row in repo.connection.execute(
                    "SELECT * FROM article_attempts ORDER BY created_at DESC, rowid DESC "
                    "LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            ]
            return {
                "attempt_counts": counts,
                "attempts": attempts,
                "limit": limit,
                "offset": offset,
            }

    def history(self, document_id):
        with open_repository(self.data_dir, read_only=True) as repo:
            repo._require("documents", document_id)
            return [
                dict(row)
                for row in repo.connection.execute(
                    "SELECT a.id AS article_id, a.document_version_id, v.revision, "
                    "a.parser_version, "
                    "a.rules_version, a.outcome, a.created_at FROM article_parses a "
                    "JOIN document_versions v ON v.id = a.document_version_id "
                    "WHERE v.document_id = ? ORDER BY v.revision, a.created_at",
                    (document_id,),
                )
            ]
