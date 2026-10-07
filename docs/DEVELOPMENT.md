# Development and local startup

Phases one through five implement the package, CLI, health endpoints, Ollama model
diagnostic, migrations, evidence storage, HTTP/RSS collection, official race records
and deterministic article preparation. Live collection is verified for all four
series and FIA news. Qwen extraction, persistent jobs and digests are later phases.
See [article commands and limits](ARTICLES.md).
The Compose `worker` is currently an opt-in, one-shot diagnostic scaffold.
See [storage commands and provenance](STORAGE.md), [source collection](COLLECTION.md), and the
[deferred local validation checklist](LOCAL_VALIDATION.md).

## Windows Docker Desktop setup

Use Docker Desktop with its WSL2 backend and Linux containers. Run these commands
in PowerShell from the repository root. Start your existing native Windows Ollama
app. Odysseus is your separate Docker-hosted interface; this project connects
directly to Ollama and does not manage Odysseus or Ollama's installation/models.

Create the local settings file without overwriting an existing one:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

Set this endpoint in `.env` for the research containers:

```dotenv
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

If you created `.env` from the previous container-based instructions, replace its
`OLLAMA_BASE_URL` with this address and remove the obsolete `OLLAMA_NETWORK` entry.
Docker Desktop provides the host DNS name; Compose creates its own application
network. There is no external-network attachment step or new Ollama service.

Start the dashboard and run the separate Ollama diagnostic:

```powershell
docker compose config --quiet
docker compose up --build -d dashboard
docker compose ps
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/storage
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

`docker compose down` retains the named volumes and leaves your native Ollama app
and separate Odysseus container running. The research app runs as a
non-root user; Docker initializes named volume ownership from image directories.
The `storage-init` service applies migrations before dependent services start.
Database and document files persist in named volumes; the report volume is reserved
for later phases. Keep `.env` and local outputs outside version control.

For builds behind a trusted TLS-inspecting proxy, the Dockerfile accepts an
optional BuildKit secret named `build_ca_bundle`, containing a trusted PEM CA
bundle. Pass it with `docker build --secret id=build_ca_bundle,src=PATH_TO_BUNDLE .`
alongside your supported proxy configuration. It is used only during dependency
installation and is not copied into the image. TLS verification remains enabled.

### Diagnosing the Windows/WSL connection

An installation prompt involving WSL does not establish where Ollama's API
listener runs. Docker Desktop using WSL2 and an Ollama server running inside WSL
are separate configurations. Check the API from Windows PowerShell first, then
run `docker compose run --rm worker` to check it from the research container.

If PowerShell succeeds but the container cannot connect, check the existing
Odysseus interface's configured Ollama endpoint and Windows listener/firewall
settings. If Ollama needs to accept connections beyond loopback, its supported
Windows user setting is:

```powershell
[Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0:11434", "User")
```

Only apply that change if needed, then fully quit Ollama from the system tray and
reopen it before retrying the diagnostic. This binds all interfaces; keep firewall
access limited to the local/Docker clients you intend to allow. Existing Odysseus
access may mean the necessary listener configuration is already in place.

If PowerShell fails but the API works inside WSL, identify the WSL-hosted server
and the reachable endpoint already used by Odysseus. Override `OLLAMA_BASE_URL`
with that verified endpoint; the Windows-host default is not proof that WSL's API
is forwarded there. WSL NAT, mirrored networking, binding, and firewall settings
can affect routing, so do not guess an address from the installer prompt.

References: [Ollama Windows environment configuration](https://docs.ollama.com/faq)
and [Docker Desktop host networking](https://docs.docker.com/desktop/features/networking/).

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
non-root volumes, installed/missing/offline model diagnostics, and real HTTP feed
collection/conditional caching against a synthetic server. It does not
connect to or modify your native Ollama or Odysseus installation, and does not
validate real inference. The fixture overrides host-name routing only for its
isolated test services; it does not exercise Windows host forwarding.

For native Windows development, the native Ollama app can be reached through localhost.
The process environment overrides the Docker-oriented `.env` settings:

```powershell
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
uv run --locked motorsport-research config
uv run --locked motorsport-research check-ollama
uv run --locked motorsport-research db-init
uv run --locked motorsport-research serve
```

Local API diagnostics bypass host HTTP proxy variables, retain TLS verification,
and do not follow redirects. Docker development uses `host.docker.internal` to
reach Windows; `localhost` inside the container refers to that container itself.

## Settings and CLI behavior

| Setting | Default | Meaning |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` natively | Compose uses `http://host.docker.internal:11434` for native Windows Ollama |
| `OLLAMA_MODEL` | `qwen3.5-instruct:4b` | Exact installed tag, configurable without code changes |
| `OLLAMA_TIMEOUT_SECONDS` | `5` | Positive HTTP timeout, at most 120 seconds |
| `REPORT_TIMEZONE` | `Europe/Athens` | Valid IANA timezone; reports arrive in a later phase |
| `LOG_LEVEL` | `INFO` | Case-insensitive standard log level |
| `SOURCE_CATALOGUE` | `config/sources.yaml` natively | Compose uses `/app/config/sources.yaml`; collection commands accept `--catalogue PATH` |
| `DATA_DIR` | `data` natively, `/data` in Docker | Reserved persistent storage root |
| `DASHBOARD_PORT` | `8000` | Host port bound to `127.0.0.1` by Compose |

Settings load from `.env` in the working directory, then process environment
overrides. Unknown `.env` keys are ignored so Compose-only settings can coexist.
Credential-bearing URLs, invalid timezones, blank model tags, and invalid timeouts
produce actionable configuration errors without echoing the rejected values.

CLI exit codes: `0` for success, `1` for failed Ollama diagnostics, and `2` for
invalid configuration or command arguments. Diagnostics print JSON to stdout;
application logs are JSON records on stderr. Use `python -m motorsport_research`
as an equivalent entry point.
Storage commands return `1` for operational errors and `2` for invalid fixture
input. `db-init` is repeatable; offline imports keep claims explicitly unassessed.

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

## Official results and FIA notices

The phase-four CLI adds `import-official`, `normalize-official`, `bundle-wrc`,
`bundle-wec`, `record-history`, and `official-status`. The image packages the
separate `config/official_sources.yaml` catalogue and reviewed contexts in
`config/official_contexts/`. See [the official-record guide](OFFICIAL_RECORDS.md)
for complete Windows and Docker commands, supported formats, and evidence limits.
