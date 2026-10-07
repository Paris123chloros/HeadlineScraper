# Article parsing and relevance

Phase five prepares readable English articles for later extraction. It requires
no Ollama inference. Collection remains manual. Qwen claims, event grouping and
scheduling arrive in phases six, seven and eight.

## Collect and inspect an article

Run from the repository root. Initialize/upgrade storage with `db-init`. Choose a
full article URL from a reviewed publisher or a collected feed's discovered links.
News indexes and RSS snapshots are not full articles.

Native PowerShell:

```powershell
uv run --locked motorsport-research db-init
$url = "https://www.motorsport.com/wrc/news/sebastien-ogiers-2027-wrc-future-is-undecided-but-he-wont-be-at-monte-carlo/10862667/"
$result = uv run --locked motorsport-research collect-article --source motorsport-wrc --url $url | ConvertFrom-Json
$result
uv run --locked motorsport-research article-detail $result.article.article_id
uv run --locked motorsport-research article-status --limit 20
```

Docker Desktop uses the existing worker CLI and persistent volumes:

```powershell
docker compose up --build -d dashboard
$url = "https://www.motorsport.com/wrc/news/sebastien-ogiers-2027-wrc-future-is-undecided-but-he-wont-be-at-monte-carlo/10862667/"
$result = docker compose run --rm worker collect-article --source motorsport-wrc --url $url | ConvertFrom-Json
$result
docker compose run --rm worker article-detail $result.article.article_id
docker compose run --rm worker article-status --limit 20
```

Inspect the receipt before using its article ID: failed/skipped collection has no
article; parsing failure has no article ID. Historical URLs may become unavailable;
choose a current feed article when needed. Valid unrelated content still creates
an inspectable article with `outcome: irrelevant`.

`collect-article` selects one source (`--catalogue PATH` is supported), retains
its publisher attribution, scheme, approved hosts, request limits and durable
host pacing, and fetches exactly the requested URL. `--force` bypasses only refresh
timing; disabled sources stay disabled. Browser sources require a supported browser
adapter. Source links and canonical references are never automatically fetched.

The article URL/HTTP method creates a versioned request configuration, with its own
refresh/cache state. The feed's cache remains intact. `collection-history` shows
the different configurations; the default freshness view concerns the configured
feed/index endpoint.

## Existing archives and offline fixtures

```powershell
uv run --locked motorsport-research parse-article DOCUMENT_VERSION_ID
uv run --locked motorsport-research parse-article DOCUMENT_VERSION_ID --encoding windows-1252
uv run --locked motorsport-research article-history DOCUMENT_ID
```

Parsing creates no new retrieval and never rewrites the archive. UTF-8 is default;
choose the encoding that actually produces the stored collection text. Other text
parser archives fail visibly rather than receiving guessed offsets. JSON, RSS and
PDF require their own adapters.

Use an isolated development database for synthetic fixtures:

```powershell
$env:DATA_DIR = "data-phase-five-check"
uv run --locked motorsport-research db-init
$first = uv run --locked motorsport-research import-article tests/fixtures/articles/race.manifest.json | ConvertFrom-Json
uv run --locked motorsport-research import-article tests/fixtures/articles/race.manifest.json
uv run --locked motorsport-research import-article tests/fixtures/articles/updated.manifest.json
uv run --locked motorsport-research article-detail $first.article_id
uv run --locked motorsport-research article-history $first.document.document_id
uv run --locked motorsport-research import-article tests/fixtures/articles/unrelated.manifest.json
uv run --locked motorsport-research article-status --limit 20 --offset 0
Remove-Item Env:DATA_DIR
```

Manifest schema: `schema_version: 1`, `provenance` (`captured`, `excerpt`, `synthetic`),
`source` (key/name/homepage URL/kind and optional existing `upstream_source_id`),
article `url`, relative `file`, actual raw-byte `sha256`, timezone-aware `captured_at`,
and `media_type` (HTML/XHTML/plain text). Optional fields: `encoding` (UTF-8 default),
`title` for plain text, and `original_sha256` (required for excerpts). See the
complete manifests in `tests/fixtures/articles/`.

Files must resolve below their manifest directory and be at most 10 MiB; manifests
are at most 256 KiB. Source URLs reject credentials. Source keys retain immutable
attribution. Capture time is an observation, separate from publication. Offline
imports record `fixture` observations without an HTTP status. The archive commits
before parsing so failures remain visible. Invalid manifests/checksums import
nothing. Offline fixture replay does not prove current live access.

## Evidence, uncertainty and filtering

`article-detail` verifies raw-byte/source-text hashes and every body fragment.
It returns title, author candidates with metadata origins, readable body, source
links, publication/modification values, topics, championship/entity hints, genre
labels, procedural/contract cues, warnings, attribution and copy candidates.

Body blocks have `body_start`/`body_end`. Each fragment has the exact original
`quote`, source `start_offset`/`end_offset`, and its clean-body span. Offsets count
Unicode characters; ends are exclusive. Whitespace cleanup can join inline markup,
so one readable sentence may map to multiple source spans. Later extraction must
use this map rather than equate clean-body offsets with source offsets.

Canonical metadata never replaces the fetched URL/publisher. Body links accept
HTTP(S) without credentials; scripts/mail links/fragments are excluded. JSON/CLI
output does not execute source HTML.

Publication and modification remain separate. Calendar days stay `date_only`,
naive times `timezone_unknown`, absent values `missing`, and invalid/conflicting
values visible. No midnight, retrieval time or source timezone is invented.
Equivalent explicit offsets can identify the same UTC instant.

Reviewable English rules live in `extraction/relevance.py` (`article-rules:1`).
Topics cover race, penalties, contracts, driver/team news, regulations, calendars,
controversies, investigations, sport news and FIA announcements. Relevance requires
a tracked-series mention plus sporting topic, or a reviewed official FIA publisher.
Championship hints are mentions, including incidental ones, not affected-series
assignments. Catalogue coverage never fills them. Organization-wide notices can
remain unassigned. Other motorsport content is retained as irrelevant for review.

Rumor cues label `rumor_reporting`; opinion/analysis titles or publisher genre
label `opinion`. Signing, negotiation and uncertain-future cues stay distinct.
Allegation, response, investigation, finding, decision and correction are wording
cues, including negated mentions. They do not establish guilt, verify contracts,
set case status, create claims or grant evidence assessments.

Entity hints match a small reviewed name lexicon and existing database aliases,
retaining candidate identities and series scopes. Unique candidates still require
assessment; ambiguous aliases remain visible. Alias changes create a new immutable
analysis for the same source version. Previous candidate snapshots survive.
Parser/rule versions, encoding and import provenance also identify analyses.

Copy detection compares bodies of at least 40 words after whitespace normalization.
It flags same-publisher copies, unchanged-body revisions, declared shared-upstream
copies, or possible syndication. Case differences/paraphrases/short notices may be
missed. Text equality alone leaves cross-publisher independence unassessed. Nothing
is merged/deleted or counted as independent corroboration. Detail returns at most
50 copy candidates.

## Outcomes and coverage limits

Successful `relevant`/`irrelevant` parses return CLI exit 0. `parser_failure`,
`unsupported_format` and `access_denied` return 1 and retain failure attempts.
Invalid schema/catalogue input returns 2. Disabled/not-due collection returns 0
as a visible skip and creates no parse attempt. `article-status` pages immutable
attempts with limit 1–100/nonnegative offset; `article-history` lists analyses by
original document revision.

Supported bodies: one semantic `<article>`, explicit `articleBody`/reviewed article
containers, FIA lead/body containers, and plain text. Captures cover Motorsport.com
articles mentioning all four series and an FIA calendar notice. Navigation, related
stories, cookie/consent UI, ads, surveys, social UI and hidden elements are excluded.
Invalid/ambiguous JSON-LD is left unassigned. Arbitrary publisher markup, JavaScript
shells and paywalled bodies require reviewed adapters.

Bounds: 100,000 HTML nodes, depth 128, 256 body candidates; 256 KiB/5,000 nodes per
JSON-LD block; 1 MiB body/20,000 fragments. Bodies shorter than 20 words fail as
insufficient, not irrelevant. These conservative heuristics can overmatch mixed
topics or miss valid short notices. The acceptance suite is regression evidence,
not a measured general-news accuracy benchmark.
