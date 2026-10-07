# Phase-one development and local startup

The package, configuration, CLI, liveness endpoint, and Ollama model diagnostic
are implemented. Collection, persistent jobs, race records, and digests are later
phases. The Compose `worker` is currently an opt-in, one-shot diagnostic scaffold.

## Windows Docker Desktop setup

Use Docker Desktop with its WSL2 backend and Linux containers. Run these commands
in PowerShell from the repository root. Your existing Ollama container must be
running; its models and GPU configuration remain managed by your existing setup.

Create the local settings file without overwriting an existing one:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker ps --format "{{.Names}}"
```

Choose the name of your existing Ollama container, then create the shared network
if needed and attach that container:

```powershell
$ollamaContainer = "REPLACE_WITH_YOUR_OLLAMA_CONTAINER_NAME"
docker network inspect motorsport-ai
if ($LASTEXITCODE -ne 0) { docker network create motorsport-ai }
$networks = docker inspect --format '{{json .NetworkSettings.Networks}}' $ollamaContainer | ConvertFrom-Json
if ($null -eq $networks.'motorsport-ai') {
    docker network connect --alias motorsport-ollama motorsport-ai $ollamaContainer
}
```

If that container was already attached without the `motorsport-ollama` alias, set
`OLLAMA_BASE_URL=http://YOUR_CONTAINER_NAME:11434` in `.env`. If you use a different
existing network, set `OLLAMA_NETWORK` accordingly and ensure the configured
hostname resolves on it. Network attachment does not replace or restart Ollama.

Start the dashboard and run the separate Ollama diagnostic:

```powershell
docker compose config --quiet
docker compose up --build -d dashboard
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/health/live
docker compose run --rm worker
```

The dashboard is available on the local port configured by `DASHBOARD_PORT`.
The diagnostic makes only `GET /api/tags`: it checks connection and the exact
installed tag configured by `OLLAMA_MODEL`. It does not run inference or pull a
model. If the tag is missing, inspect the models in your existing installation
and edit `.env` to use the actual tag, including any alias you created.

Application liveness does not depend on Ollama. `/health/ollama` returns HTTP 200
for an installed configured tag and HTTP 503 for unavailable or invalid responses
or a missing model. That result establishes model availability, not extraction
quality or inference readiness.

Useful commands:

```powershell
docker compose exec dashboard motorsport-research config
docker compose logs --tail 100 dashboard
docker compose run --rm worker --version
docker compose down
```

`docker compose down` retains the named volumes and leaves your existing Ollama
container running. The external network is user-managed. The app runs as a
non-root user; Docker initializes named volume ownership from image directories.
Database/document/report volumes are reserved for later phases and stored inside
Docker's Linux filesystem. Keep `.env` and local outputs outside version control.

For builds behind a trusted TLS-inspecting proxy, the Dockerfile accepts an
optional BuildKit secret named `build_ca_bundle`, containing a trusted PEM CA
bundle. Pass it with `docker build --secret id=build_ca_bundle,src=PATH_TO_BUNDLE .`
alongside your supported proxy configuration. It is used only during dependency
installation and is not copied into the image. TLS verification remains enabled.

## Native development

Install Python 3.12 and uv 0.12.19, then synchronize the locked development and
optional legacy dependencies:

```powershell
python -m pip install uv==0.12.19
uv sync --locked --all-extras
uv run --locked --all-extras ruff check
uv run --locked --all-extras ruff format --check
uv run --locked --all-extras pytest
uv build --wheel
```

After building the image, the Docker acceptance check creates an isolated network,
temporary volumes, and a synthetic Ollama container, then removes those resources:

```powershell
docker compose build
python scripts/check_docker.py
```

It checks real container startup/restart, loopback-only port binding, writable
non-root volumes, and installed/missing/offline model diagnostics. It does not
connect to or modify your Ollama container, and does not validate real inference.

For native development, a published Ollama port can be reached through localhost.
The process environment overrides the Docker-oriented `.env` settings:

```powershell
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
uv run --locked motorsport-research config
uv run --locked motorsport-research check-ollama
uv run --locked motorsport-research serve
```

Container-to-container diagnostics bypass host HTTP proxy variables, retain TLS
verification, and do not follow redirects. For Docker development, use the shared
network hostname rather than `localhost`, which refers to the app container.

## Settings and CLI behavior

| Setting | Default | Meaning |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` natively | HTTP(S) base URL; Compose uses the shared network alias |
| `OLLAMA_MODEL` | `qwen3.5-instruct:4b` | Exact installed tag, configurable without code changes |
| `OLLAMA_TIMEOUT_SECONDS` | `5` | Positive HTTP timeout, at most 120 seconds |
| `REPORT_TIMEZONE` | `Europe/Athens` | Valid IANA timezone; reports arrive in a later phase |
| `LOG_LEVEL` | `INFO` | Case-insensitive standard log level |
| `DATA_DIR` | `data` natively, `/data` in Docker | Reserved persistent storage root |
| `OLLAMA_NETWORK` | `motorsport-ai` | Compose external network name |
| `DASHBOARD_PORT` | `8000` | Host port bound to `127.0.0.1` by Compose |

Settings load from `.env` in the working directory, then process environment
overrides. Unknown `.env` keys are ignored so Compose-only settings can coexist.
Credential-bearing URLs, invalid timezones, blank model tags, and invalid timeouts
produce actionable configuration errors without echoing the rejected values.

CLI exit codes: `0` for success, `1` for failed Ollama diagnostics, and `2` for
invalid configuration or command arguments. Diagnostics print JSON to stdout;
application logs are JSON records on stderr. Use `python -m motorsport_research`
as an equivalent entry point.

## Original Selenium prototype

`run.py` and `motosport/` remain unchanged. The optional `legacy` extra installs
Selenium; running the original scraper still requires a working Chrome/driver
setup and access to its configured website:

```powershell
uv run --locked --extra legacy python run.py
```

The new foundation image does not install Chrome or Selenium. Browser-based
collection will receive its own supported adapter and image configuration later.

## Validation boundaries

The tests use synthetic Ollama listings and exercise real local HTTP as well as
failure fixtures. They cover invalid settings, environment precedence, absent
models, malformed/oversized responses, connection failure, timeout, and independent
application liveness. They do not validate Qwen inference or live news collection.

CI is configured for Python checks on Linux and Windows and an image build on
Linux. Configuring CI is separate from observing it run. Docker Desktop networking,
the user's installed model, and Windows startup must also be checked on the user's
machine before those capabilities are considered verified.
