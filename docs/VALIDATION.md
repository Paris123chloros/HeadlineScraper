# Development validation

## Phase six: local Qwen extraction software

Validated on Linux in the cloud on 2026-10-07 with Python 3.12 and the
`motorsport-research:phase-six` image
(`sha256:cb404eecc72f132eeb79dce9f6167931e3bf1ba38c7ac0e132fd82316bb28bc8`).
The software is implemented; phase-six acceptance remains pending real local
model accuracy and throughput on representative hardware.

| Check | Result |
| --- | --- |
| Complete Python suite | 220 passed; one existing Starlette deprecation warning |
| Strict chat schema, input/output limits and protocol checks | Passed with synthetic HTTP responses |
| Exact Unicode/inline evidence, fabricated names/numbers/dates, unsupported summaries | Passed; no invented evidence committed |
| Literal dates, ambiguous alias candidates and conservative procedural/uncertainty checks | Passed; suggestions require semantic review |
| Six manual development labels | Passed through validator using synthetic outputs; not Qwen accuracy |
| Missing model, timeout, unavailable server and bounded invalid-completion retry | Passed; pending work retained or visible failure |
| Real cloud connection failure | Configured host unreachable; task pending, unavailable attempt, zero claims |
| Model digest pin/change detection, replay and explicit new run | Passed; changed weights do not commit claims |
| Multi-chunk outage/resume, serialized leases and expired lease recovery | Passed; no network wait in write transactions |
| Atomic whole-article commit, rollback and immutable audit/provenance | Passed |
| Evaluation artifact, separate held-out data, scores and timing metrics | Passed using synthetic development-case inference only |
| Cross-document score aggregation | Passed; swapped labels cannot cancel errors across cases |
| Locked sync, Ruff lint/format, wheel modules/migration, legacy import and Compose config | Passed; no dependency or old migration changes |
| Docker chat, trace, replay, migration 007 and restart persistence | Passed with isolated synthetic Ollama service |
| Earlier Docker article, official PDF, collection/304 and diagnostic workflows | Passed |
| Actual Qwen accuracy, throughput, source-instruction behavior and Windows routing | Pending local validation |
| Automatic handling approval | False; every model suggestion requires review |
| Hosted GitHub Actions | Configured; hosted run not observed |

Docker checks use the script's own temporary resources and synthetic model
responses. They leave real research volumes, native Ollama and Odysseus alone.
The cloud build preserves TLS verification using the existing trusted CA bundle
as a build secret; no new dependencies, secret requirements or network
destinations were introduced. Public fixture files are readable by the container
user. Raw source bytes, previous migrations and the Selenium prototype are unchanged.

The twelve synthetic cases provide a small development/reserved-held-out split,
not a representative real-news benchmark. The held-out set has not been used
for validator tuning or mocked quality claims. No real model response, hardware
measurement or production threshold approval has been obtained. Exact passage
validation proves traceability, not semantic support or truth; entity links,
attribution, temporal roles and topic/procedure interpretation remain suggestions.
See [extraction commands and evaluation](QWEN_EXTRACTION.md) and the
[deferred Windows/Qwen checklist](LOCAL_VALIDATION.md).

## Phase five: articles and relevance

Validated on Linux in the cloud on 2026-10-07, with Python 3.12 and the
`motorsport-research:phase-five` image
(`sha256:48a9837e30f065f6ea71d3538a706ff379d9751b3db1d3f5892e8bd1951c8102`).

| Check | Result |
| --- | --- |
| Complete Python suite | 174 passed; one existing Starlette deprecation warning |
| Reviewed synthetic race, contract, rumor, opinion, update, FIA, allegation, denial and unrelated fixtures | Passed; fixed readable bodies and metadata expectations |
| Full captured Motorsport.com articles mentioning F1/WEC/WRC/DTM | Passed; reviewed authors/body boundaries; related stories/surveys removed |
| Captured FIA calendar lead/body, tables and publication/modification values | Passed; no catalogue-based championship assignment |
| Unicode/inline body spans and original archive integrity | Passed; every fragment maps to stored source text |
| Date-only, unknown timezone, conflicting dates and absent metadata | Passed; no invented instants |
| Entity registry ambiguity and changed-registry analysis snapshots | Passed; candidates remain inspectable |
| Copy/shared-upstream hints and publisher attribution | Passed; no automatic corroboration or merge |
| Replay, updates, A/B/A reversion and immutable attempts | Passed |
| Insufficient bodies, index/shell, access challenge, unsupported format and bounds | Passed; distinct from irrelevant success |
| Invalid JSON-LD, source instructions, encodings and canonical references | Passed; source remains untrusted input |
| Manifest checksum/path validation, migration 006 upgrade and atomic success audit | Passed |
| Explicit article collection, conditional 304, host/scheme checks and disabled sources | Passed using bounded collector with synthetic HTTP transport |
| Live explicit article collection/parsing | Passed for all four Motorsport.com series sources and FIA; verified source spans |
| Native CLI guide sequence | Passed: schema 6, repeat import, update, unrelated outcome |
| Locked dependencies, Ruff lint/format, wheel contents, legacy import and Compose configuration | Passed; no dependency changes |
| Docker article import/replay, revisions, irrelevant outcome and persisted source spans | Passed; non-root volumes and restart verified |
| Earlier Docker official PDF/feed/304/Ollama diagnostics | Passed with isolated synthetic services |
| Windows Docker Desktop, native Ollama and real inference | Pending local validation; unchanged deferred checklist |
| Hosted GitHub Actions | Configured; hosted run not observed |

The first Docker run found that restored public phase-four fixture permissions
prevented the container user reading a manifest. Read/traversal permissions on
those public fixtures were corrected; the final Docker check passed and removed
its temporary containers, networks and volumes. No private data permissions,
real research volumes or existing Ollama/Odysseus services were changed.

Live receipts reside outside the checkout in the isolated cloud development
database; committed captures are offline regression evidence. English keyword
filtering is conservative, with no measured general-news precision/recall claim.
Championship hints describe mentions, and procedural cues include negated wording.
No claims, case findings or verified identities are produced in this phase.
Publisher markup outside reviewed bodies may need another adapter. See
[article usage and limitations](ARTICLES.md).

## Phase four: official race records and decisions

Validated on Linux in the cloud on 2026-10-07, using Python 3.12 and the
`motorsport-research:phase-four` image.

| Check | Result |
| --- | --- |
| Complete Python suite | 130 passed; one existing Starlette deprecation warning |
| Fixed reference fields across 17 classifications / 421 rows | Passed: all four series |
| F1 Bahrain full weekend and separate FIA final PDF | Passed: all 20 entries per session |
| F1 Miami sprint and 2024 driver/constructor standings | Passed: published scoring preserved |
| WEC Fuji full race, distinct Hypercar/LMGT3 scopes and full crews | Passed: 35 entries; 17 and 18 per class |
| WEC published Hypercar class-table/CSV cross-check | Passed: 17 joined entries, statuses retained |
| WRC Monte Carlo rally and final-stage classifications | Passed: 48 rally and 56 stage rows; crew/category/rejoin evidence |
| DTM Red Bull Ring full weekend | Passed: seven sessions, 21 entries each; race one/two and DSQ/DNF distinct |
| Driver case variants across F1/FIA sources share a stable meeting identity | Passed; no duplicate drivers |
| Replay, amended classifications and A/B/A reversions | Passed; original record/document/claim histories retained |
| FIA rule date, investigation, imposed/overturned decision handling | Passed with explicitly synthetic procedure fixtures |
| Published FIA calendar notice and organization-wide jurisdiction | Passed with actual HTML capture; no forced tracked championship |
| Ingestion failure audit and transaction rollback | Passed |
| Previous-schema migration with existing evidence | Passed; archived evidence retained |
| CLI import, normalization, bundles, history and status | Passed, including UTF-8 BOM contexts for PowerShell |
| PDF isolated extraction, official document and invalid PDF failure | Passed; bounded Linux subprocess |
| Live collection and normalization from F1, WEC, WRC and DTM official result endpoints | Passed in the cloud Python environment |
| Live WEC class-table bundle and WRC final-stage bundle | Passed: 17 and 56 normalized rows |
| Locked dependency sync, Ruff lint/format, wheel contents and Compose configuration | Passed |
| Docker CLI, non-root volumes, startup and restart | Passed |
| Docker FIA PDF import/replay/evidence and persisted classification | Passed: 20 rows; final state and lap deficits preserved |
| Previous Docker collection/304/Ollama diagnostic checks | Passed using isolated synthetic services |
| Original Selenium prototype import | Passed; original source unchanged |
| User's Windows Docker Desktop, installed Ollama and real inference | Pending local validation |
| Hosted GitHub Actions | Configured; no hosted run observed |

Live collection uses the reviewed endpoints in `config/official_sources.yaml`.
The WRC public service was discovered in the bundle loaded by the official WRC
results component. DTM's official results API was discovered in its published
application code. Its full-season response ignored identity encoding; narrowing
the request to the reviewed meeting succeeded through the existing bounded
collector. No compression limits or TLS checks were disabled.

The first expanded Docker check found private file modes on generated public
fixtures, so the app's non-root user could not read the copied files. Read and
traversal permissions on those new public fixtures were corrected, and the final
image/check passed. Application execution remains non-root.

These checks cover the pinned layouts and reviewed records. WEC's CSV does not
publish class ranks; its Hypercar class table was separately verified, while
LMGT3 class-table retrieval remains unverified. Published website ranks and CSV
statuses are preserved even where a publisher numbers retired rows. Only F1
standings are implemented, and no championship scores are derived. FIA notice
interpretation is reviewed metadata; procedure fixtures are synthetic. Claims
remain unassessed, and these development references do not constitute a held-out
accuracy evaluation or automatic verification of truth.

New-meeting discovery, article relevance/extraction, Qwen inference, scheduling,
event grouping and reports remain subsequent development work. Cloud source
network requirements and startup instructions were saved to the onboarding draft;
saving does not publish or prove fresh-task restoration. See
[official-record usage](OFFICIAL_RECORDS.md) and the
[deferred Windows/Ollama checks](LOCAL_VALIDATION.md).

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
Windows/Ollama verification. Phase five is the next implementation segment: article parsing and relevance.
