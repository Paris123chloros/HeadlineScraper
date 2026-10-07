import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from motorsport_research.cli import main
from motorsport_research.config import Settings
from motorsport_research.logging import JsonFormatter
from motorsport_research.web.app import create_app


@pytest.fixture
def ollama_fixture():
    requests = []
    listing = {"models": [{"name": "qwen3.5-instruct:4b"}]}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(("GET", self.path))
            body = json.dumps(listing).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", listing, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_web_health_is_independent_of_model_availability(ollama_fixture):
    url, listing, requests = ollama_fixture
    with TestClient(create_app(Settings(ollama_base_url=url))) as client:
        assert client.get("/health/live").json()["status"] == "ok"
        assert requests == []
        assert client.get("/").status_code == 200
        assert "FIA announcements" in client.get("/").text
        ready = client.get("/health/ollama")
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"
        listing["models"] = []
        missing = client.get("/health/ollama")
        assert missing.status_code == 503
        assert missing.json()["status"] == "model_missing"
        assert client.get("/health/live").status_code == 200
    assert requests == [("GET", "/api/tags"), ("GET", "/api/tags")]


def test_cli_checks_real_http_and_returns_failure_for_missing_model(
    ollama_fixture, monkeypatch, capsys
):
    url, listing, requests = ollama_fixture
    monkeypatch.setenv("OLLAMA_BASE_URL", url)
    assert main(["check-ollama"]) == 0
    assert json.loads(capsys.readouterr().out)["model_available"] is True
    listing["models"] = []
    assert main(["check-ollama"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "model_missing"
    assert requests == [("GET", "/api/tags"), ("GET", "/api/tags")]


def test_json_logging_preserves_single_line_records():
    record = logging.LogRecord("foundation", logging.INFO, __file__, 1, "line\nbreak", (), None)
    output = JsonFormatter().format(record)
    assert len(output.splitlines()) == 1
    assert json.loads(output)["message"] == "line\nbreak"
