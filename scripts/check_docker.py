"""Exercise the built image with isolated Compose resources and a synthetic Ollama."""

import argparse
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="motorsport-research:local")
    args = parser.parse_args()
    project = f"motorsport-check-{uuid.uuid4().hex[:12]}"
    fixture = f"{project}-ollama"
    environment = dict(
        os.environ,
        MOTORSPORT_IMAGE=args.image,
        OLLAMA_NETWORK=project,
        OLLAMA_BASE_URL="http://motorsport-ollama:11434",
        OLLAMA_MODEL="qwen3.5-instruct:4b",
        OLLAMA_TIMEOUT_SECONDS="1",
        REPORT_TIMEZONE="UTC",
        LOG_LEVEL="INFO",
        DASHBOARD_PORT="0",
    )
    compose = ["docker", "compose", "--project-name", project]

    def run(command: list[str], expected: int = 0) -> str:
        result = subprocess.run(
            command, cwd=ROOT, env=environment, text=True, capture_output=True, timeout=60
        )
        if result.returncode != expected:
            raise RuntimeError(
                f"Command {command[:3]} exited {result.returncode}, expected {expected}: "
                f"{result.stdout}\n{result.stderr}"
            )
        return result.stdout

    def probe(path: str) -> dict:
        code = """
import json, sys, urllib.error, urllib.request
try:
    response = urllib.request.urlopen('http://127.0.0.1:8000' + sys.argv[1], timeout=3)
except urllib.error.HTTPError as error:
    response = error
with response:
    print(json.dumps({'http_status': response.status, 'body': json.load(response)}))
"""
        return json.loads(run([*compose, "exec", "-T", "dashboard", "python", "-c", code, path]))

    def wait_for_liveness() -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                result = probe("/health/live")
                if result["http_status"] == 200 and result["body"]["status"] == "ok":
                    return
            except (RuntimeError, KeyError, json.JSONDecodeError):
                pass
            time.sleep(0.5)
        raise RuntimeError("Application failed to return the expected liveness response")

    fixture_code = """
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != '/api/tags':
            self.send_error(404)
            return
        body = json.dumps({'models': [{'name': 'qwen3.5-instruct:4b'}]}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
HTTPServer(('0.0.0.0', 11434), Handler).serve_forever()
"""
    run(["docker", "run", "--rm", args.image, "--version"])
    run(["docker", "network", "create", project])
    fixture_started = False
    try:
        run([*compose, "up", "--no-build", "--detach", "dashboard"])
        wait_for_liveness()
        offline = probe("/health/ollama")
        assert offline["http_status"] == 503, offline
        assert offline["body"]["reachable"] is False, offline

        container = run([*compose, "ps", "--quiet", "dashboard"]).strip()
        ports = json.loads(
            run(["docker", "inspect", "--format", "{{json .NetworkSettings.Ports}}", container])
        )
        assert ports["8000/tcp"][0]["HostIp"] == "127.0.0.1", ports
        volume_check = """
import os
from pathlib import Path
assert os.getuid() == 10001
for directory in ['/data', '/data/documents', '/data/reports']:
    path = Path(directory) / 'phase-one-check'
    path.write_text('temporary acceptance check')
    path.unlink()
"""
        run([*compose, "exec", "-T", "dashboard", "python", "-c", volume_check])
        run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                fixture,
                "--network",
                project,
                "--network-alias",
                "motorsport-ollama",
                "--entrypoint",
                "python",
                args.image,
                "-u",
                "-c",
                fixture_code,
            ]
        )
        fixture_started = True
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            available = probe("/health/ollama")
            if available["http_status"] == 200:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Synthetic Ollama fixture was not reachable")
        assert available["body"]["model_available"] is True, available
        diagnostic = json.loads(run([*compose, "run", "--rm", "worker"]))
        assert diagnostic["status"] == "ready", diagnostic
        missing = json.loads(
            run(
                [*compose, "run", "--rm", "-e", "OLLAMA_MODEL=not-installed:4b", "worker"],
                expected=1,
            )
        )
        assert missing["status"] == "model_missing", missing
        run([*compose, "restart", "dashboard"])
        wait_for_liveness()
        assert probe("/health/ollama")["http_status"] == 200
        print("PASS: image CLI, Compose startup/restart, local port binding, non-root volumes")
        print("PASS: Ollama offline, installed-tag fixture, and missing-tag diagnostic exit code")
        print("Synthetic Ollama fixture only; real model inference and Windows remain unverified.")
    finally:
        if fixture_started:
            run(["docker", "rm", "--force", fixture])
        run([*compose, "down", "--volumes"])
        run(["docker", "network", "rm", project])


if __name__ == "__main__":
    main()
