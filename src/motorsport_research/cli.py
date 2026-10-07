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

    if args.command == "config":
        print(json.dumps(settings.model_dump(mode="json"), indent=2))
        return 0
    if args.command == "check-ollama":
        status = check_ollama(settings)
        print(status.model_dump_json(indent=2))
        return 0 if status.status == "ready" else 1

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
