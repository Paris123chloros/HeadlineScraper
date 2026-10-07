"""Development entry point for configuration, diagnostics, and the local web app."""

import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from motorsport_research import __version__
from motorsport_research.config import ConfigurationError, load_settings
from motorsport_research.extraction.ollama import check_ollama
from motorsport_research.logging import configure_logging
from motorsport_research.storage.database import StorageError, initialize
from motorsport_research.storage.models import ClaimInput, EvidenceFixture
from motorsport_research.storage.repository import open_repository


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="motorsport-research")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("config", help="Validate and print non-secret application settings")
    commands.add_parser(
        "check-ollama", help="Check connectivity and installed model, without pulling"
    )
    commands.add_parser("db-init", help="Initialize storage and apply checked migrations")
    commands.add_parser("storage-status", help="Inspect schema and record counts")
    fixture = commands.add_parser("import-fixture", help="Import offline evidence JSON atomically")
    fixture.add_argument("path", help="JSON file path, or - to read stdin")
    trace = commands.add_parser("trace-claim", help="Show and verify a claim's source evidence")
    trace.add_argument("claim_id")
    article_import = commands.add_parser(
        "import-article", help="Archive and parse an article manifest"
    )
    article_import.add_argument("path", type=Path)
    article_parse = commands.add_parser("parse-article", help="Parse an archived article version")
    article_parse.add_argument("document_version_id")
    article_parse.add_argument("--encoding", default="utf-8")
    article_collect = commands.add_parser(
        "collect-article", help="Fetch an explicit approved article URL and parse it"
    )
    article_collect.add_argument("--source", required=True)
    article_collect.add_argument("--url", required=True)
    article_collect.add_argument("--catalogue", type=Path)
    article_collect.add_argument("--force", action="store_true")
    article_detail = commands.add_parser(
        "article-detail", help="Inspect article and verify source spans"
    )
    article_detail.add_argument("article_id")
    article_history = commands.add_parser(
        "article-history", help="Inspect article document revisions"
    )
    article_history.add_argument("document_id")
    article_status = commands.add_parser("article-status", help="Inspect article parsing attempts")
    article_status.add_argument("--limit", type=int, default=50)
    article_status.add_argument("--offset", type=int, default=0)
    extract = commands.add_parser(
        "extract-article", help="Run review-required local Qwen extraction"
    )
    extract.add_argument("article_id")
    extract.add_argument("--new-run", action="store_true", help="Create an explicit new model run")
    retry = commands.add_parser(
        "retry-extraction", help="Resume a pending extraction with its pinned settings"
    )
    retry.add_argument("task_id")
    extraction_detail = commands.add_parser(
        "extraction-detail", help="Inspect Qwen attempts and source selections"
    )
    extraction_detail.add_argument("task_id")
    extraction_status = commands.add_parser("extraction-status", help="Inspect durable Qwen work")
    extraction_status.add_argument("--limit", type=int, default=50)
    extraction_status.add_argument("--offset", type=int, default=0)
    evaluation = commands.add_parser(
        "evaluate-qwen", help="Run a labeled dataset and save a local evaluation artifact"
    )
    evaluation.add_argument("--dataset", type=Path, required=True)
    evaluation.add_argument("--output", type=Path, required=True)
    evaluation.add_argument("--hardware", required=True)
    official = commands.add_parser(
        "import-official", help="Import a reviewed official archive manifest"
    )
    official.add_argument("path", type=Path)
    normalize = commands.add_parser(
        "normalize-official", help="Normalize an archived document version"
    )
    normalize.add_argument("document_version_id")
    normalize.add_argument("--context", type=Path, required=True)
    bundle = commands.add_parser("bundle-wrc", help="Join explicit archived WRC API components")
    bundle.add_argument("--components", type=Path, required=True)
    bundle.add_argument("--context", type=Path, required=True)
    wec_bundle = commands.add_parser("bundle-wec", help="Join WEC CSV and published class table")
    wec_bundle.add_argument("--components", type=Path, required=True)
    wec_bundle.add_argument("--context", type=Path, required=True)
    commands.add_parser("official-status", help="Show official ingestion outcomes")
    records = commands.add_parser(
        "record-history", help="Inspect an immutable sporting record history"
    )
    records.add_argument("record_id")
    sources = commands.add_parser("sources", help="Inspect configured sources without fetching")
    status = commands.add_parser(
        "collection-status", help="Inspect collection outcomes and coverage"
    )
    history = commands.add_parser(
        "collection-history", help="Inspect a source's attempts and configuration"
    )
    history.add_argument("source")
    collect = commands.add_parser(
        "collect", help="Collect enabled or explicitly selected sources once"
    )
    collect.add_argument("--source", action="append", help="Source key; repeat to select several")
    collect.add_argument(
        "--force",
        action="store_true",
        help="Ignore refresh interval, retaining host pacing and retry limits",
    )
    for command in (sources, status, history, collect):
        command.add_argument("--catalogue", type=Path, help="Override SOURCE_CATALOGUE")
    serve = commands.add_parser("serve", help="Start the local foundation web application")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if args.command == "serve" and not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    try:
        settings = load_settings()
    except ConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 2
    configure_logging(settings.log_level)

    if args.command == "evaluate-qwen":
        from motorsport_research.extraction.evaluation import evaluate

        try:
            result = evaluate(settings, args.dataset, args.output, args.hardware)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0 if result["all_cases_finished"] else 1
        except ValidationError:
            print("Invalid evaluation dataset; check the documented schema.", file=sys.stderr)
            return 2
        except (StorageError, sqlite3.Error, OSError, ValueError) as error:
            print(f"Evaluation operation failed: {error}", file=sys.stderr)
            return 1

    if args.command in {
        "extract-article",
        "retry-extraction",
        "extraction-detail",
        "extraction-status",
    }:
        from motorsport_research.extraction.qwen_service import QwenService

        try:
            service = QwenService(settings)
            if args.command == "extract-article":
                result = service.extract(args.article_id, new_run=args.new_run)
            elif args.command == "retry-extraction":
                result = service.retry(args.task_id)
            elif args.command == "extraction-detail":
                result = service.detail(args.task_id)
            else:
                result = service.status(limit=args.limit, offset=args.offset)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return (
                0
                if args.command in {"extraction-detail", "extraction-status"}
                or result["status"] == "completed"
                else 1
            )
        except (StorageError, sqlite3.Error, OSError, ValueError) as error:
            print(f"Extraction operation failed: {error}", file=sys.stderr)
            return 1

    if args.command in {
        "import-article",
        "collect-article",
        "parse-article",
        "article-detail",
        "article-history",
        "article-status",
    }:
        from motorsport_research.extraction.service import ArticleService
        from motorsport_research.sources.catalogue import CatalogueError, load_catalogue

        try:
            service = ArticleService(settings.data_dir)
            if args.command == "import-article":
                result = service.import_manifest(args.path)
            elif args.command == "collect-article":
                catalogue = load_catalogue(args.catalogue or settings.source_catalogue)
                result = service.collect_article(catalogue, args.source, args.url, force=args.force)
            elif args.command == "parse-article":
                result = service.parse(args.document_version_id, encoding=args.encoding)
            elif args.command == "article-detail":
                result = service.detail(args.article_id)
            elif args.command == "article-history":
                result = service.history(args.document_id)
            else:
                result = service.status(limit=args.limit, offset=args.offset)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            outcome = result.get("outcome", "relevant") if isinstance(result, dict) else "relevant"
            return 0 if outcome in {"relevant", "irrelevant", "not_due", "disabled"} else 1
        except ValidationError:
            print("Invalid article manifest; check the documented schema.", file=sys.stderr)
            return 2
        except CatalogueError as error:
            print(f"Catalogue error: {error}", file=sys.stderr)
            return 2
        except (StorageError, sqlite3.Error, OSError, ValueError) as error:
            print(f"Article operation failed: {error}", file=sys.stderr)
            return 1

    if args.command == "config":
        print(json.dumps(settings.model_dump(mode="json"), indent=2))
        return 0
    if args.command == "check-ollama":
        status = check_ollama(settings)
        print(status.model_dump_json(indent=2))
        return 0 if status.status == "ready" else 1

    if args.command in {
        "import-official",
        "normalize-official",
        "official-status",
        "record-history",
        "bundle-wrc",
        "bundle-wec",
    }:
        from motorsport_research.championships.json_data import decode
        from motorsport_research.championships.service import CONTEXT, OfficialService

        try:
            service = OfficialService(settings.data_dir)
            if args.command == "import-official":
                result = service.import_manifest(args.path)
            elif args.command == "normalize-official":
                if args.context.stat().st_size > 256 * 1024:
                    raise ValueError("Official context exceeds 256 KiB")
                context = CONTEXT.validate_python(decode(args.context.read_bytes()))
                result = service.normalize(args.document_version_id, context)
            elif args.command in {"bundle-wrc", "bundle-wec"}:
                if (
                    args.context.stat().st_size > 256 * 1024
                    or args.components.stat().st_size > 256 * 1024
                ):
                    raise ValueError("Official context/components exceed 256 KiB")
                bundle_method = (
                    service.bundle_wrc if args.command == "bundle-wrc" else service.bundle_wec
                )
                result = bundle_method(
                    decode(args.components.read_bytes()),
                    CONTEXT.validate_python(decode(args.context.read_bytes())),
                )
            elif args.command == "record-history":
                with open_repository(settings.data_dir, read_only=True) as repository:
                    result = repository.record_history(args.record_id)
            else:
                result = service.status()
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        except ValidationError:
            print(
                "Invalid official manifest/context; check the documented schema.", file=sys.stderr
            )
            return 2
        except (StorageError, sqlite3.Error, OSError, ValueError) as error:
            print(f"Official record operation failed: {error}", file=sys.stderr)
            return 1

    if args.command in {"sources", "collect", "collection-status", "collection-history"}:
        from motorsport_research.sources.catalogue import CatalogueError, load_catalogue
        from motorsport_research.sources.collector import SUCCESS, Collector
        from motorsport_research.sources.store import CollectionStore

        try:
            catalogue = load_catalogue(args.catalogue or settings.source_catalogue)
            if args.command == "sources":
                result = catalogue.model_dump(mode="json")
            elif args.command == "collect":
                result = Collector(settings.data_dir).collect(
                    catalogue, args.source, force=args.force
                )
                print(json.dumps(result, indent=2, ensure_ascii=False))
                return 0 if all(item["outcome"] in SUCCESS for item in result) else 1
            elif args.command == "collection-history":
                catalogue.select([args.source])
                result = CollectionStore(settings.data_dir).history(args.source)
            else:
                result = CollectionStore(settings.data_dir).status(catalogue)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        except CatalogueError as error:
            print(f"Catalogue error: {error}", file=sys.stderr)
            return 2
        except (StorageError, sqlite3.Error, OSError, ValueError) as error:
            print(f"Collection operation failed: {error}", file=sys.stderr)
            return 1

    if args.command in {"db-init", "storage-status", "import-fixture", "trace-claim"}:
        try:
            if args.command == "db-init":
                initialize(settings.data_dir)
            if args.command in {"db-init", "storage-status"}:
                with open_repository(settings.data_dir, read_only=True) as repository:
                    result = repository.stats()
            elif args.command == "trace-claim":
                with open_repository(settings.data_dir, read_only=True) as repository:
                    result = repository.trace_claim(args.claim_id)
            else:
                content = (
                    sys.stdin.read()
                    if args.path == "-"
                    else Path(args.path).read_text(encoding="utf-8")
                )
                fixture_data = EvidenceFixture.model_validate_json(content)
                document = fixture_data.document.model_copy(
                    update={"retrieval_method": "fixture", "http_status": None}
                )
                with open_repository(settings.data_dir) as repository:
                    source_id = repository.register_source(fixture_data.source)
                    receipt = repository.import_document(source_id, document)
                    claims = [
                        repository.record_claim(
                            ClaimInput(
                                document_version_id=receipt["version_id"], **claim.model_dump()
                            )
                        )
                        for claim in fixture_data.claims
                    ]
                    result = {"source_id": source_id, "document": receipt, "claim_ids": claims}
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        except ValidationError as error:
            details = "; ".join(
                f"{'.'.join(map(str, item['loc']))}: {item['msg']}"
                for item in error.errors(include_input=False, include_url=False)
            )
            print(f"Invalid evidence input: {details}", file=sys.stderr)
            return 2
        except (StorageError, sqlite3.Error, OSError, ValueError) as error:
            print(f"Storage operation failed: {error}", file=sys.stderr)
            return 1

    import uvicorn

    from motorsport_research.web.app import create_app

    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_config=None)
    return 0
