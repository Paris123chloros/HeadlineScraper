import logging
import sqlite3

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from motorsport_research import __version__
from motorsport_research.config import Settings, load_settings
from motorsport_research.extraction.ollama import check_ollama
from motorsport_research.sources.catalogue import CatalogueError, load_catalogue
from motorsport_research.sources.store import CollectionStore
from motorsport_research.storage.database import StorageError
from motorsport_research.storage.repository import open_repository


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else load_settings()
    app = FastAPI(title="Motorsport Research", version=__version__)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> str:
        return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Motorsport Research</title>
<style>body{max-width:48rem;margin:4rem auto;padding:0 1rem;font:1.1rem/1.6 system-ui;
background:#101820;color:#f4f6f8}h1{line-height:1.2}strong{color:#8ce3c0}</style></head>
<body><main><h1>Motorsport Research</h1><p><strong>F1 · WEC · WRC · DTM</strong></p>
<p>A sourced record of race results, penalties, driver developments,
FIA announcements, and controversies.</p>
<p>The project foundation, evidence storage, and collection CLI are available.
The event feed and automated
digests will arrive in subsequent development phases.</p></main></body></html>"""

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/health/ollama")
    def ollama() -> JSONResponse:
        result = check_ollama(settings)
        return JSONResponse(
            content=result.model_dump(), status_code=200 if result.status == "ready" else 503
        )

    @app.get("/health/storage")
    def storage() -> JSONResponse:
        try:
            with open_repository(settings.data_dir, read_only=True) as repository:
                result = repository.stats()
            return JSONResponse(result)
        except (StorageError, sqlite3.Error, OSError) as error:
            logging.getLogger(__name__).warning("Storage readiness check failed: %s", error)
            return JSONResponse(
                {
                    "status": "unavailable",
                    "detail": "Storage is not ready; run db-init and check logs.",
                },
                status_code=503,
            )

    @app.get("/api/collection")
    def collection_status() -> JSONResponse:
        try:
            catalogue = load_catalogue(settings.source_catalogue)
            return JSONResponse(CollectionStore(settings.data_dir).status(catalogue))
        except (CatalogueError, StorageError, sqlite3.Error, OSError) as error:
            logging.getLogger(__name__).warning("Collection status is unavailable: %s", error)
            return JSONResponse(
                {"status": "unavailable", "detail": "Check storage and source catalogue."},
                status_code=503,
            )

    return app
