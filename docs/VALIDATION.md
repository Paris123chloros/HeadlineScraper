# Phase-one validation

Validated in the development cloud environment on Linux with Python 3.12.14,
Docker Engine 28.4.0, and Compose 2.40.3. The built image uses Python 3.12.15.

| Check | Result |
| --- | --- |
| Frozen dependency synchronization, including the legacy extra | Passed |
| Configuration, Ollama response/failure, CLI, HTTP, and logging tests | 33 passed |
| Ruff lint and formatting | Passed |
| Wheel build | Passed |
| Existing `motosport.motobot.MotoBot` import | Passed; original source unchanged |
| Compose configuration validation | Passed |
| Docker image build and CLI | Passed |
| Real Compose startup/restart and expected liveness response | Passed |
| Loopback-only published port and non-root volume writes | Passed |
| Ollama offline, installed-tag fixture, and missing-tag exit status | Passed |
| User's Windows Docker Desktop installation | Not run |
| User's existing Ollama/Qwen model or real inference | Not run |
| GitHub Actions workflow | Configured; no hosted run observed |

The Python suite currently emits one dependency deprecation warning: Starlette
recommends its newer HTTP client for `TestClient`. All tests execute and pass;
the application uses HTTPX for its read-only Ollama diagnostic.

The ordinary Docker build initially failed because this cloud builder could not
resolve the injected proxy and did not include the platform's trusted proxy CA.
The successful build used the platform-resolved proxy hostname, host build
networking, standard proxy build arguments, and the existing trusted CA bundle
through the Dockerfile's optional `build_ca_bundle` secret. TLS verification and
locked dependency hashes remained enabled. The CA bundle is not retained in the
image. These are cloud validation overrides, not required Windows defaults.

The Compose acceptance check uses an isolated synthetic Ollama listing and removes
its containers, volumes, and network afterward. It establishes integration and
diagnostic behavior, not model inference capability or factual extraction quality.

See [the development guide](DEVELOPMENT.md) for repeatable commands and local
Windows/Ollama verification. Phase two is the next implementation segment:
versioned source records, identity, database migrations, and evidence persistence.
