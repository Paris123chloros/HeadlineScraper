"""Exercise the built image with isolated Compose resources and a synthetic Ollama."""

import argparse
import json
import os
import subprocess
import tempfile
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
        OLLAMA_BASE_URL="http://host.docker.internal:11434",
        OLLAMA_MODEL="qwen3.5-instruct:4b",
        OLLAMA_TIMEOUT_SECONDS="1",
        REPORT_TIMEZONE="UTC",
        LOG_LEVEL="INFO",
        DASHBOARD_PORT="0",
    )
    temporary = tempfile.TemporaryDirectory(prefix="motorsport-check-")
    override_path = Path(temporary.name) / "compose.fixture.json"
    compose = [
        "docker",
        "compose",
        "--file",
        str(ROOT / "compose.yaml"),
        "--file",
        str(override_path),
        "--project-name",
        project,
    ]

    def run(command: list[str], expected: int = 0, *, input_text: str | None = None) -> str:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=60,
            input=input_text,
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
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
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
while not Path('/tmp/ollama-fixture-enabled').exists():
    time.sleep(0.1)
HTTPServer(('0.0.0.0', 11434), Handler).serve_forever()
"""
    run(["docker", "run", "--rm", args.image, "--version"])
    run(["docker", "network", "create", project])
    fixture_started = False
    try:
        run(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                fixture,
                "--network",
                project,
                "--entrypoint",
                "python",
                args.image,
                "-u",
                "-c",
                fixture_code,
            ]
        )
        fixture_started = True
        networks = json.loads(
            run(["docker", "inspect", "--format", "{{json .NetworkSettings.Networks}}", fixture])
        )
        fixture_address = networks[project]["IPAddress"]
        # Test-only host routing prevents any request to the user's real Ollama.
        override_path.write_text(
            json.dumps(
                {
                    "services": {
                        name: {"extra_hosts": [f"host.docker.internal:{fixture_address}"]}
                        for name in ["dashboard", "worker"]
                    },
                    "networks": {"default": {"external": True, "name": project}},
                }
            ),
            encoding="utf-8",
        )
        run([*compose, "up", "--no-build", "--detach", "dashboard"])
        wait_for_liveness()
        storage = probe("/health/storage")
        assert storage["http_status"] == 200, storage
        assert storage["body"]["counts"]["championships"] == 4, storage
        fixture_input = (ROOT / "tests/fixtures/evidence.json").read_text(encoding="utf-8")
        import_command = [
            *compose,
            "exec",
            "-T",
            "dashboard",
            "motorsport-research",
            "import-fixture",
            "-",
        ]
        first_import = json.loads(run(import_command, input_text=fixture_input))
        repeated_import = json.loads(run(import_command, input_text=fixture_input))
        assert first_import["document"]["version_id"] == repeated_import["document"]["version_id"]
        assert first_import["claim_ids"] == repeated_import["claim_ids"]
        claim_trace = json.loads(
            run(
                [
                    *compose,
                    "exec",
                    "-T",
                    "dashboard",
                    "motorsport-research",
                    "trace-claim",
                    first_import["claim_ids"][0],
                ]
            )
        )
        assert claim_trace["assessment"]["label"] == "unassessed", claim_trace
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
                "exec",
                fixture,
                "python",
                "-c",
                "from pathlib import Path; Path('/tmp/ollama-fixture-enabled').touch()",
            ]
        )
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
        persistent = probe("/health/storage")
        assert persistent["body"]["counts"]["document_versions"] == 1, persistent
        assert persistent["body"]["counts"]["claims"] == 2, persistent
        print("PASS: image CLI, Compose startup/restart, local port binding, non-root volumes")
        print("PASS: migrations, repeatable evidence import, claim trace, persistent records")
        print("PASS: Ollama offline, installed-tag fixture, and missing-tag diagnostic exit code")
        print("Synthetic host routing only; Windows host forwarding and inference are unverified.")
    finally:
        if fixture_started:
            run(["docker", "rm", "--force", fixture])
        if override_path.exists():
            run([*compose, "down", "--volumes"])
        run(["docker", "network", "rm", project])
        temporary.cleanup()


if __name__ == "__main__":
    main()
