"""Development entry point for configuration, diagnostics, and the local web app."""

import argparse
import json
import sys
from collections.abc import Sequence

from motorsport_research import __version__
from motorsport_research.config import ConfigurationError, load_settings
from motorsport_research.extraction.ollama import check_ollama
from motorsport_research.logging import configure_logging


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="motorsport-research")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("config", help="Validate and print non-secret application settings")
    commands.add_parser(
        "check-ollama", help="Check connectivity and installed model, without pulling"
    )
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

    import uvicorn

    from motorsport_research.web.app import create_app

    uvicorn.run(create_app(settings), host=args.host, port=args.port, log_config=None)
    return 0
