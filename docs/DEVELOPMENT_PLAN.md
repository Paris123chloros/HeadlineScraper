# Motorsport research: development plan

Status: implementation backlog; the application described here is not built yet.

## Product agreement

Build a personal, English-language research tool for **F1, WEC, WRC, and DTM**.
Collect published race information and reporting, organize it into events, retain
the supporting evidence, and produce a searchable feed and automated digests.

Coverage includes session results, championship standings, penalties,
investigations, appeals, regulations, calendar changes, driver contracts,
injuries, team developments, and wider news relevant to the sport. Contract
announcements, negotiations, and rumors must remain distinguishable.

Run locally on **Windows with Docker Desktop's WSL2 backend and Linux containers**.
Reuse the user's existing Docker-hosted Ollama and configurable model tag
`qwen3.5-instruct:4b`. No cloud inference service is required.

The defining principle is: **every factual claim retains its evidence, and every
material revision remains traceable**. Source agreement is evidence of agreement,
not an automatic guarantee of truth.

## Architecture and working rules

- Python 3.12 initially; FastAPI, a simple server-rendered dashboard, and a worker.
- SQLite with migrations, foreign keys, WAL, short transactions, and a busy timeout.
  One worker owns domain-record writes. The API can enqueue job requests; database
  writes are serialized by SQLite. Run migrations once before either service starts.
- Docker Compose services for the dashboard and worker. Reuse Ollama through a
  documented shared Docker network; preserve its existing model storage and GPU
  configuration. Do not start a second Ollama instance by default.
- Named volumes retain the database, source documents, and generated reports.
  Keep the SQLite volume inside Docker's Linux filesystem rather than a Windows
  bind mount. Bind the dashboard's published port to `127.0.0.1`.
- RSS and HTTP collectors first; browser collection is an optional dependency
  enabled per source. Official PDFs can use document-specific parsers.
- Store timestamps in UTC, retain source timezone information when available, and
  render reports in the configured timezone. Unknown event times remain unknown.
- Use explicit source adapters and championship normalizers behind shared
  interfaces. Collection, extraction, evidence assessment, and reporting remain
  separate stages.
- Treat fetched documents as untrusted data. Bound size and processing time,
  preserve TLS verification, and keep model prompts separate from source content.
- Introduce AI only after deterministic collection and structured records work.
  Code handles numerical results, scoring rules, and exact date comparisons.
- Preserve `run.py` and `motosport/` as the existing prototype while building the
  new package. Introduce a documented replacement entry point when it is usable.

Proposed layout, to be created in segment 01:

```text
src/motorsport_research/
  config.py
  cli.py
  storage/          # repositories, migrations, document storage
  sources/          # catalogue, transport, RSS/HTML/PDF/browser adapters
  championships/    # f1, wec, wrc, dtm normalizers
  extraction/       # deterministic parsing, Ollama client, schemas
  events/           # matching, evidence labels, revision handling
  jobs/             # scheduling, retry, worker lifecycle
  reporting/        # deterministic report records and renderers
  web/              # API, templates, static assets
tests/
  fixtures/         # attributed offline documents and expected records
  unit/
  integration/
  acceptance/
config/sources.yaml
docs/
compose.yaml
Dockerfile
pyproject.toml
```

## Segment overview

Each segment should become a focused pull request or a small sequence of pull
requests. Dependencies describe integration gates, not permission to omit any
championship. All four series are required for the first release.

| ID | Segment | Depends on | Reviewable outcome |
| --- | --- | --- | --- |
| 01 | Project and Docker foundations | None | Installable package and local container workflow |
| 02 | Records, identity, and persistence | 01 | Migrated database with traceable source and claim records |
| 03 | Source catalogue and collection | 02 | Repeatable retrieval with visible source failures |
| 04 | Official race data and decisions | 03 | Structured results and penalties for all four series |
| 05 | Article parsing and relevance | 03 | Clean, attributed articles and deterministic metadata |
| 06 | Local Qwen extraction | 02, 05 | Validated, evidence-bound claims from Ollama |
| 07 | Event grouping and corroboration | 04, 06 | Searchable events with independent evidence and revisions |
| 08 | Scheduling and resilient jobs | 03; integrate 04–07 | Restart-safe collection and processing |
| 09 | Feed, API, and review interface | 07, 08 | Local dashboard with evidence drill-down |
| 10 | Automated digests and exports | 07, 08 | Reproducible English reports with citations |
| 11 | Windows operations and recovery | 09, 10 | Documented Compose setup, upgrades, and backups |
| 12 | End-to-end validation and release | 01–11 | Evaluated first release with known limitations |

## 01 — Project and Docker foundations

**Goal:** establish a maintainable development workflow before adding collectors.

Tasks:

- Add the package layout, dependency declarations, a reproducible dependency lock,
  test configuration, and a CLI entry point.
- Add a Dockerfile and Compose skeleton, configuration loading, non-secret example
  settings, logging, and exclusions for local data and build outputs.
- Define `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, and `REPORT_TIMEZONE`; use the agreed
  model tag as a configurable default.
- Document joining the existing Ollama container to a shared network. Inspect
  `/api/tags` to verify the requested model exists; report a missing model without
  automatically pulling models or changing the existing container.
- Add basic CI for package installation and meaningful tests as they arrive.

**Acceptance:** a fresh Docker build imports the package and runs its CLI; the
dashboard exposes a liveness response; configuration errors are actionable;
Ollama connectivity is checked separately from application liveness. Commands
leave the existing scraper usable.

## 02 — Records, identity, and persistence

**Goal:** keep evidence and changes inspectable from the beginning.

Tasks:

- Model sources, retrieval attempts, versioned documents, championships, seasons,
  meetings, sessions, entities, classifications, decisions, claims, events, jobs,
  extraction runs, and report snapshots.
- Assign stable IDs and retain aliases for drivers, crews, cars, teams, and
  manufacturers. Record ambiguous entity matches for review.
- Distinguish publication time, retrieval time, event time, and effective time.
- Store canonical URLs, content hashes, original attribution, parser versions,
  supporting passages, and model/prompt versions where relevant.
- Add migrations, uniqueness constraints, transactional repositories, and document
  storage linked to immutable document versions.

**Acceptance:** importing the same document twice is idempotent; changed content
creates a revision; stored claims can be traced to exact document versions and
passages; migrations preserve existing data; conflicting aliases remain visible.

## 03 — Source catalogue and collection

**Goal:** collect consistently while making coverage gaps visible.

Tasks:

- Catalogue official championship, governing-body, team, and independent English
  sources. Record access method, championship coverage, attribution, upstream
  origins, refresh interval, and whether a source is currently usable.
- Implement RSS and HTTP collection with conditional requests, timeouts, response
  size limits, caching, per-host rate limits, redirects, and bounded retry.
- Distinguish unsupported formats, access denials, parser failures, and valid
  no-change responses. Support a browser adapter only where needed.
- Save collection attempts even when fetching fails. Create offline fixtures with
  source URLs, retrieval dates, and expected outcomes.

**Acceptance:** successfully collect a documented usable source for each series;
repeated retrieval does not duplicate documents; tests exercise timeout, denial,
redirect, and malformed-feed behavior. Offline fixtures support development when
live access fails, but do not count as proof of live connectivity.

## 04 — Official race data and decisions

**Goal:** anchor race facts to authoritative published records.

Tasks:

- Implement an adapter and normalizer for each championship:
  - F1: session type, sprint/race distinctions, driver and constructor identity.
  - WEC: overall and class positions, car entry, crew, and manufacturer identity.
  - WRC: stage and rally classification, category, retirement/restart status.
  - DTM: race-one/race-two identity, driver, team, and manufacturer.
- Preserve published position, time/gap, status, and points when supplied. Never
  infer a numeric gap from text such as a lap deficit without an explicit rule.
- Distinguish provisional, final, and amended classifications; retain previous
  versions and their source documents.
- Represent investigations, imposed penalties, appeals, and overturned decisions
  independently from their effect on a classification.
- Store official standings when available. Implement derived standings only with
  versioned championship rules and verified treatment of dropped scores, special
  points, disqualifications, and tie-breaking.

**Acceptance:** one completed weekend or meeting from each series matches its
official records; WEC classes and DTM races remain distinct; an amended-result
fixture and a penalty-revision fixture preserve their histories.

## 05 — Article parsing and relevance

**Goal:** supply attributed, readable content to later extraction stages.

Tasks:

- Extract article title, author, publication time, article body, and source links;
  remove navigation, cookie notices, and repeated page furniture.
- Define topic categories and deterministic championship/entity hints.
- Retain uncertainty in dates and identity matches instead of silently filling
  missing values. Label commentary and rumor reporting explicitly.
- Detect obvious duplicate and syndicated documents while retaining attribution.

**Acceptance:** reviewed fixtures include race news, a contract announcement,
rumor, opinion piece, updated article, and unrelated content; extracted evidence
maps back to the stored source text; parsing failure is distinguishable from an
irrelevant article.

## 06 — Local Qwen extraction

**Goal:** evaluate the existing 4B model on bounded extraction tasks.

Tasks:

- Implement an Ollama `/api/chat` client with bounded input/output, explicit
  timeouts, configurable model settings, and schema-constrained responses.
- Extract championship, topic, entities, claims, attribution, relevant dates,
  uncertainty, and supporting text spans. Split long articles at useful boundaries.
- Validate schema, evidence passages, dates, identities, and numeric fields against
  source text. Reject unsupported claims and flag ambiguous extraction for review.
- Record prompt/model versions and extraction duration; keep a manually labeled
  development set separate from the held-out evaluation set.
- Preserve pending work if Ollama is unavailable. Invalid output gets bounded
  retries and then a visible failure state.

**Acceptance:** exercise real local inference; test invalid JSON, fabricated
evidence, unavailable model, timeout, and instructions embedded in source text.
Publish extraction accuracy and throughput on representative hardware. Approve
automatic handling only for task types that meet their evaluation thresholds.

## 07 — Event grouping and corroboration

**Goal:** combine coverage without losing disagreements or attribution.

Tasks:

- Match candidates using championship, meeting/session, entities, topic, dates,
  URLs, and text similarity. Use Qwen only for bounded ambiguous comparisons.
- Identify shared upstream reporting; do not count syndicated copies as separate
  corroboration. Retain evidence of how independence was assessed.
- Assess claims with labels: officially announced, independently corroborated,
  single-source, disputed, and corrected/superseded. Store the rationale.
- Represent conflicting assertions together. Link corrections and result amendments
  without erasing previous records.
- Support reversible merge/split and human adjudication with an audit trail.

**Acceptance:** fixtures prove both grouping and separation, including consecutive
races involving the same driver, the same car number in different series, copied
announcements, conflicting reports, and subsequent corrections. Labels remain
attached to claims rather than granting blanket credibility to entire articles.

## 08 — Scheduling and resilient jobs

**Goal:** run unattended while preserving work across restarts.

Tasks:

- Persist collection, parsing, extraction, event-update, and reporting jobs with
  leases, attempt counts, retry times, and final failure states.
- Separate fetch scheduling from inference throughput; prevent slow inference from
  stopping collection. Start with one inference job at a time and measure capacity.
- Configure race-weekend and ordinary refresh intervals, with manual collection
  requests and explicit timezone handling.
- Recover expired leases after restart, deduplicate queued work, and make repeated
  processing idempotent. Record source freshness and queue age.

**Acceptance:** terminate a worker during processing, restart it, and verify work
recovers without duplicate events or reports. Ollama outages accumulate visible
pending extraction jobs; recovery drains them. Retry exhaustion is observable.

## 09 — Feed, API, and review interface

**Goal:** make the collected evidence useful for personal research.

Tasks:

- Expose paginated events, search, championship/topic/date filters, and event detail
  with entities, evidence links, supporting passages, and revision history.
- Show source freshness, failed collection, pending extraction, and uncertainty.
- Add queued manual-refresh and review actions with an auditable outcome.
- Escape source content in templates and serve local assets. Keep the interface
  readable on a normal desktop browser without a separate frontend toolchain.

**Acceptance:** find events from each series, inspect conflicting evidence, follow
an amendment, and observe a failed source. Source HTML cannot execute in the UI.
Empty results and incomplete collection coverage appear distinctly.

## 10 — Automated digests and exports

**Goal:** produce useful, reproducible reports from stored records.

Tasks:

- Generate daily and on-demand digests with sections for results, penalties,
  driver/team developments, sport news, and corrections/unresolved reports.
- Define the report interval explicitly and persist the included event/claim
  versions. Separate event occurrence from newly published information.
- Render deterministic Markdown and HTML with citations and coverage status.
- Add CSV/JSON exports for structured records. Optional Qwen wording must remain
  bounded by selected claims and preserve citations, labels, and numeric facts;
  retain a deterministic rendering fallback.
- Record later corrections as new report versions rather than silently rewriting
  previously generated reports. Keep delivery integrations for later work.

**Acceptance:** every factual report statement has evidence; rerendering the same
snapshot reproduces its structured content; ambiguous claims keep their labels;
coverage outages are reported; timezone boundaries and daylight-saving changes
do not omit or double-count entries.

## 11 — Windows operations and recovery

**Goal:** make the installation usable beyond the development session.

Tasks:

- Write PowerShell-friendly Docker Desktop/WSL2 setup and startup instructions,
  Ollama network-attachment steps, model availability checks, and troubleshooting.
- Make first-run migrations and startup ordering explicit; add service health
  checks, graceful shutdown, log rotation, and restart policies.
- Provide versioned backups, restore verification, export, retention settings, and
  an upgrade procedure that preserves the database and existing Ollama models.
- Document that collection runs while Docker Desktop and the worker are running;
  retain the last successful retrieval watermark after downtime.
- Measure disk growth, collection delay, inference throughput, and queue backlog
  on the user's machine. Make model context and concurrency configurable.

**Acceptance:** verify startup, shutdown, restart, upgrade, and backup restoration
on Windows Docker Desktop. A fresh installation connects to the existing Ollama
container and persistent data survives container replacement. Linux-only testing
must be reported separately until Windows validation is performed.

## 12 — End-to-end validation and first release

**Goal:** assess the complete workflow against independently reviewed evidence.

Tasks:

- Assemble a held-out reference set covering all four series: completed race
  meetings, classes/stages, an amendment, a penalty, a contract announcement,
  duplicated coverage, conflicting claims, and irrelevant articles.
- Measure event recall, false merges/splits, claim precision, unsupported report
  statements, source coverage, and end-to-end processing delay.
- Exercise collector denial, parser drift, Ollama downtime, worker interruption,
  database recovery, and later corrections.
- Document supported sources, evaluated task types, unvalidated paths, manual
  review needs, and measured resource requirements; prepare a release checklist.

**Acceptance:** all four series pass representative functional flows; reviewed
structured classifications match official records exactly; the evaluated reports
contain zero unsupported factual statements; merge/split behavior and extraction
metrics are reported against thresholds agreed before evaluating the held-out set.
No readiness claim is based only on a running container, a zero-test run, or a
model producing syntactically valid JSON.

## Delivery order and first development slice

1. Complete 01 and 02 to establish the package, container workflow, and evidence
   storage. Implement only tables needed by the initial slice; add later tables
   through migrations.
2. Implement one source-to-record path in 03 and one official parser in 04, with
   an attributed offline fixture and a separate live retrieval check. Extend 04 to
   all four series before its acceptance gate is closed.
3. Add article parsing and the minimal persistent job runner. Implement 06 and 07
   against reviewed examples; evaluate Qwen before unattended claim publication.
4. Complete scheduling, then ship the dashboard and deterministic digest. Connect
   optional AI wording only after report evidence checks work.
5. Complete Windows operations and held-out validation before the first release.

The first coding PR should contain package/configuration setup, a Compose skeleton,
the initial source/document/retrieval migration, and an idempotent fixture import
exercising that storage. It should document the next source-adapter task and the
existing-Ollama connection. This slice establishes a real foundation without
pretending that collection, factual extraction, or reporting already works.

## Definition of done for each segment

- Deliverables are implemented and documented with exact working commands.
- Relevant tests execute and their results are recorded; live and offline checks
  are distinguished, as are Windows and Linux validation.
- Failure states and data migrations relevant to the change are exercised.
- Source/model attribution and existing user data remain intact.
- Known limitations are recorded and downstream interfaces are explicit.
- The segment's acceptance gate is met, or the remaining blocker is identified
  without marking the segment complete.

## Deferred scope and unresolved implementation inputs

Later releases can add multilingual sources/reports, delivery integrations,
notifications, telemetry feeds, public hosting, and additional championships.
These do not replace the required first-release coverage or evidence checks.

Before the related implementation steps, inspect rather than guess:

- The local Ollama container name, network, model tags, and available CPU/GPU/RAM.
- Actual accessibility and document formats of proposed sources. Previous cloud
  onboarding observed an ESPN proxy denial; that does not establish what is
  reachable from the user's local Windows installation.
- Report timezone and preferred schedule; retain configurable defaults meanwhile.
- Source-specific independence rules and measurable extraction/matching thresholds,
  established from the development set before held-out evaluation.
