# Development validation

## Phase three: source collection

Validated on Linux in the cloud on 2026-10-07, with Python 3.12 and the
`motorsport-research:phase-three` Docker image.

| Check | Result |
| --- | --- |
| Complete Python suite, including collection failure cases | 75 passed |
| Catalogue validation, RSS/Atom discovery, offset dates and unknown dates | Passed |
| Conditional caching, duplicate import, changed feeds and cache integrity | Passed |
| Timeout/retry budgets, slow headers/trickling bodies, HTTP denial and proxy failure | Passed |
| Durable host pacing and server `Retry-After` across forced collections | Passed |
| Redirect loops, unapproved hosts and HTTPS downgrade refusal | Passed |
| Malformed/unsafe feeds, streaming size limits and unsupported formats | Passed |
| Migration from existing phase-two storage and immutable attempt history | Passed |
| Offline fixtures covering all four series and FIA | Passed; synthetic content |
| Ruff lint/format, locked dependencies, wheel and Compose configuration | Passed |
| Legacy scraper import | Passed; original source unchanged |
| Docker non-root catalogue access and real HTTP feed collection | Passed |
| Docker conditional 304 and collection persistence after restart | Passed |
| Existing Docker/Ollama diagnostic and evidence acceptance checks | Passed with synthetic responses |
| Live official F1, WEC, WRC and FIA indexes | Passed; relevant archived news text inspected |
| Live Motorsport.com F1, WEC, WRC and DTM feeds | Passed; article titles/dates/links inspected |
| Repeated live collection of all eight enabled sources | Passed; both passes exited 0 |
| Official DTM index | Disabled: unsupported response and HTML shell without news text |
| Real Windows Docker Desktop, installed Ollama and inference | Pending |
| Hosted CI workflow | Configured; no hosted run observed |

The initial cloud proxy denied source requests. Required publisher domains were
added to the onboarding network draft while preserving ESPN entries; subsequent
live requests succeeded. These observations establish current-instance access,
not publication of the reusable environment configuration.

Live coverage now includes two usable sources each for F1, WEC and WRC, and one
independent feed for DTM. FIA collection remains organization-wide. Source
collection does not verify race results, corroborate article claims, or establish
independence between feeds owned by the same publisher. Official DTM and the
disabled team/document candidates require later adapter work.

The first container check found that the non-root user could not read the copied
catalogue. The Dockerfile now grants read/traversal access to the public catalogue;
the rebuilt image passed the full acceptance check. The one Starlette deprecation
warning remains. See [collection usage and limits](COLLECTION.md).

## Phase two: evidence persistence

Validated on Linux in the development cloud environment using Python 3.12 and
the built `motorsport-research:phase-two` Docker image.

| Check | Result |
| --- | --- |
| Complete Python suite, including storage integration tests | 47 passed |
| Migration upgrades, checksum refusal, and failed-upgrade rollback | Passed |
| Document revisions/reversions, immutable history, and transaction rollback | Passed |
| Exact Unicode evidence spans, content integrity, and extraction provenance | Passed |
| Scoped alias ambiguity, announcement scope, and case history | Passed |
| Original publisher offset and chronological UTC timestamp ordering | Passed |
| Ruff lint/format, wheel build, and Compose configuration | Passed |
| Fresh Docker image with packaged migrations | Passed |
| Compose storage initialization and read-only storage health | Passed |
| Repeated offline import and claim tracing inside Docker | Passed |
| Imported document/claim persistence after dashboard restart | Passed |
| Existing Ollama diagnostic acceptance checks | Passed with synthetic responses |
| User's Windows/Ollama connection and real Qwen inference | Pending |

The fixture is fictional and offline. These checks establish persistence and
traceability; they do not establish extraction accuracy, corroboration quality,
or truth. A matching evidence quote leaves its claim `unassessed`.

The Python suite still emits the Starlette dependency deprecation warning described
below. The Windows checks are retained in the
[deferred local validation checklist](LOCAL_VALIDATION.md).

## Phase one: foundations

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
its containers, volumes, and network afterward. Following the native-Windows
correction, the test maps `host.docker.internal` to its private fixture only. It
establishes integration and diagnostic behavior, not actual Windows host forwarding,
model inference capability, or factual extraction quality. Production Compose uses
Docker Desktop's host DNS and requires no external Ollama network.

See [the development guide](DEVELOPMENT.md) for repeatable commands and local
Windows/Ollama verification. Phase four is the next implementation segment:
official race data and decisions.
