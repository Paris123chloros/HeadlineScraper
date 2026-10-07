# Phase-three source collection

The collection CLI archives bounded HTTP responses and RSS/Atom snapshots, discovers
feed article links, and records failures and unchanged responses. It runs without
Ollama. The catalogue includes official series sites, FIA announcements/document
indexes, independent news feeds, and team candidates. Eight enabled endpoints were
successfully collected and inspected in the cloud on 2026-10-07, covering all four
series and FIA news. The official DTM index remains disabled pending a site/browser
adapter; DTM currently has a usable independent RSS feed.

## Run a collection pass

From the repository root with native Python:

```powershell
uv run --locked motorsport-research db-init
uv run --locked motorsport-research sources
uv run --locked motorsport-research collect --source f1-official --source motorsport-f1
uv run --locked motorsport-research collection-status
uv run --locked motorsport-research collection-history f1-official
```

With Docker, after building and starting the dashboard:

```powershell
docker compose run --rm worker collect --source f1-official --source motorsport-f1
docker compose run --rm worker collection-status
docker compose run --rm worker collection-history motorsport-f1
```

`collect` without `--source` selects all enabled sources. Repeat `--source` to select
several. Disabled sources remain disabled even when explicitly selected. The default
refresh interval is 30 minutes; sources that are not due produce `not_due` without
a network request or a new retrieval observation. `--force` bypasses the refresh
interval while preserving host pacing, server `Retry-After`, and request limits.
This is a one-shot collector; scheduling and restart-safe jobs arrive in phase eight.

Collection exits 0 when every selected source succeeds, is unchanged, is not due,
or is disabled; it exits 1 when any selected source fails. Invalid catalogues or
unknown keys exit 2. Status/history commands read storage without making requests.
`GET /api/collection` provides the same coverage and latest-outcome overview without
initiating collection. An absent catalogue or unready database returns 503.

## Catalogue and attribution

`config/sources.yaml` is editable YAML with a strict, versioned schema. `sources`
prints the validated definitions. Unknown fields, duplicate YAML keys, duplicate
source identities, credentials in URLs, missing upstream identities, and upstream
cycles are rejected. Each source records:

| Fields | Purpose |
| --- | --- |
| `key`, `name`, `homepage`, `publisher`, `kind`, `role` | Stable identity and publisher attribution |
| `url`, `method`, `allowed_hosts` | Explicit endpoint, adapter, and permitted redirect hosts |
| `championships`, `topics`, `language`, `issuing_body` | Collection scope and issuing body |
| `upstream_key` | Known upstream source; leave null when unknown |
| `enabled`, `availability`, `notes` | Operational choice, declared usability, and limitations |
| `refresh_seconds`, `host_interval_seconds` | Refresh interval and durable per-host spacing |
| `timeout_seconds`, `total_seconds`, `max_bytes` | Request timeout, total source budget, and response limit |
| `max_attempts`, `max_redirects` | Retry and redirect bounds |

Coverage hints do not classify an individual article. FIA news has an empty
championship list because some announcements concern the organization as a whole.
Motorsport.com feeds share one publisher and must not be counted as independent
corroboration of each other. Topic labels such as `controversies` do not establish
that a scandal occurred or a claim was proven.

Every attempted source configuration is retained as a checksummed JSON snapshot.
Changing access settings creates a new configuration and invalidates its cache/due
state. Stable source attribution fields remain protected by phase-two storage;
changing a registered name, homepage, kind, or upstream identity requires an
explicit identity migration rather than silently rewriting historical attribution.

Native development uses `SOURCE_CATALOGUE=config/sources.yaml` by default. All
source commands accept `--catalogue PATH`. The Docker image includes its catalogue
at `/app/config/sources.yaml`; rebuild after editing, or mount a custom file read-only
at that path for the service that runs collection. CLI overrides refer to paths
inside the container. Installed-wheel users running outside the checkout must
provide a catalogue path.

## Transport, parsing, and history

The defaults allow at most 2 MiB per response, two attempts per redirect hop,
four redirects, a ten-second request timeout, and a 45-second source budget. Host
spacing applies across successive commands and services through short SQLite
transactions. Network operations do not hold database write locks. Retryable
statuses and transient connection failures receive bounded retries; access denials
and parser failures do not. A long `Retry-After` defers the host instead of blocking
a command for hours. `--force` cannot bypass that deferral.

Redirects require an approved exact hostname and cannot downgrade HTTPS. Validators
are sent only to the cached effective URL. A 304 requires a previously accepted,
integrity-checked document and a matching conditional request. Cache keys include
source configuration and parser version. A 200 with the same document fingerprint
retains its version; changed content produces a new immutable revision.

TLS verification and environment proxies remain enabled. Collection requests
identity encoding and rejects unsolicited compressed responses rather than
performing unbounded decompression. Response limits are checked both against
`Content-Length` and streamed bytes. A proxy error is distinct from a denial by
the publisher, and transport diagnostics do not echo potentially sensitive errors.

RSS 2, RSS 1, and Atom support bounded entries, XML base URLs, article links, and
known publication dates. DTD/entity declarations are rejected. Unknown or timezone-
less dates stay null with warnings; original values remain in the raw snapshot.
Valid empty feeds are accepted. Invalid or unsupported feeds do not become documents.

HTTP HTML collection archives visible text and a title, omitting scripts/styles;
it does not yet isolate article bodies or discover links from site navigation.
Common access-challenge titles are rejected. PDF responses with a PDF signature
are archived with empty text and a warning; phase four interprets their contents.
Feed links are discovery records tied to the exact feed version, not proof that
the linked article has been fetched. Neither collection path creates claims,
classifications, decisions, or truth assessments.

Run outcomes distinguish `success`, `not_modified`, `access_denied`, `proxy_error`,
`timeout`, `network_error`, `http_error`, `rate_limited`, `redirect_error`,
`redirect_denied`, `too_large`, `unsupported_format`, `parser_failure`,
`invalid_not_modified`, and `unsupported_method`. Each completed run retains its
configuration, timestamps, next due time, document reference, and individual HTTP
request outcomes, including retries and redirects. Complete bounded 200 payloads
rejected by parsing are preserved as diagnostic blobs; oversized/partial bodies
and HTTP error bodies are not archived as complete documents.

The status view reports declared availability separately from observed outcomes.
`sources_with_success` means a retained success under the current configuration;
it is not a freshness or extraction-quality guarantee. Inspect the latest result,
last-success date, and configuration-change flag when judging current coverage.

Requests and their final run are committed together after collection finishes.
A process killed before that commit may leave no attempt record. Durable job leases,
recovery from interruption, and overlapping source-run coordination belong to
phase eight. Run one collection worker at a time until that phase.

Browser collection is not required by the currently enabled usable sources. The `browser` method
produces a visible `unsupported_method` result; it does not launch the legacy scraper
or bypass a site's access controls. Determine browser requirements from actual
responses. The official DTM candidate returned an unsupported response and an HTML
shell without news text; it remains disabled pending adapter validation.

## Validation boundary and cloud networking

The synthetic fixtures in `tests/fixtures/collection/` identify candidate source
URLs, simulated retrieval dates, and expected outcomes. They contain fictional
text and were never downloaded from those publishers. Offline tests cover each
series and FIA; the Docker acceptance check uses an isolated synthetic HTTP feed,
including a real conditional 304 and persistence across restart.

Initial probes received cloud proxy denials. After the network domain additions
took effect, live collection succeeded for official F1, WEC, WRC and FIA indexes,
plus Motorsport.com feeds for F1, WEC, WRC and DTM. The archived indexes contained
relevant current headlines; all four feeds contained titled articles, publication
dates and article links. The live-source gate is met for all four series, using
the independent feed for DTM. This does not establish official race-data coverage
or that any extracted headline has been corroborated.

The onboarding network draft now includes the required publisher hosts while
preserving the existing ESPN entries. Successful subsequent requests establish
current-instance reachability; the settings draft still requires publication for
reuse as an environment configuration. Disabled candidates may need URL corrections,
redirect hosts, site adapters, or browser support. Mark them usable only after
inspecting successful responses containing relevant content. Future redirects or
resource hosts must be diagnosed explicitly.

The separate Windows/Ollama connection remains on the
[deferred local checklist](LOCAL_VALIDATION.md).

## Phase-four structured collection

`collection:2` also archives valid JSON and CSV response bodies for explicit
normalization. JSON with duplicate keys or non-finite values is refused. PDF
collection still archives bytes without interpreting sporting meaning; phase-four
normalizers handle supported PDF layouts in a bounded process. The ordinary news
catalogue remains the default. Use `config/official_sources.yaml` for reviewed
result endpoints; official DTM now has a working meeting-scoped public API path.
The full-season DTM API can ignore identity encoding, which remains an explicit
unsupported outcome. The smaller reviewed meeting response worked with the
existing bounded collector. See [official record commands](OFFICIAL_RECORDS.md).
