# Official sporting records

Phase four adds deterministic result parsers, official standings, and reviewed FIA
notices. It uses the existing evidence database and does not require Ollama.
Every accepted row has an exact passage, archived bytes, publisher attribution,
parser version, and a claim ID. Claims remain `unassessed`; corroboration and
confidence assessments are phase seven.

## Implemented formats and reviewed coverage

| Series | Format | Captured reference meeting | Preserved distinctions |
| --- | --- | --- | --- |
| F1 | Formula1.com HTML tables; FIA race PDF | Bahrain 2024: three practices, qualifying, race; FIA final race classification | Session number, driver/car/team, qualifying times, published points, lap deficits |
| WEC | Official Alkamel CSV; optional official class-table archive | Fuji 2026: all 35 race entries, 17 Hypercar and 18 LMGT3 entries | Full crew, car, class, overall position, published class-table position, retirement status |
| WRC | Public API used by WRC's official results component | Monte Carlo 2026: 48 rally classification rows and 56 final-stage rows | Driver/co-driver, category, stage versus rally times, explicit rejoining notices |
| DTM | Official public Wige results API | Red Bull Ring 2026: three practices, two qualifying sessions, both races, 21 entries per session | Race one/two, published race versus total points, driver/team/car brand, DSQ/DNF |

F1 season-driver standings are imported as a published snapshot, with all 24
2024 entries. Constructor standings are also verified: all ten 2024 teams, led by McLaren
with the published 666 points. A Miami 2024 sprint fixture verifies its 8–1 scoring. Other championship
standings and derived scoring are not implemented. New result formats fail closed.

The separate `config/official_sources.yaml` contains explicit reviewed endpoints.
The existing news catalogue remains the default. This is a manual collection and
normalization workflow; automatic meeting discovery and scheduled processing have
not been implemented.

## Offline import and inspection

From the repository root, initialize or upgrade the existing database first:

```powershell
uv run --locked motorsport-research db-init
uv run --locked motorsport-research import-official tests/fixtures/official/f1-race.manifest.json
uv run --locked motorsport-research import-official tests/fixtures/official/dtm-race1.manifest.json
uv run --locked motorsport-research official-status
```

An import receipt contains `record.record_id`, `record.version_id`, the normalized
`document.version_id`, and `claim_ids`. Substitute those IDs when inspecting:

```powershell
uv run --locked motorsport-research record-history RECORD_ID
uv run --locked motorsport-research trace-claim CLAIM_ID
```

The Docker image includes the parsers and catalogues. Reference fixtures stay in
the checkout; mount them read-only for an offline demonstration:

```powershell
docker compose build
docker compose run --rm storage-init
docker compose run --rm -v "${PWD}/tests/fixtures/official:/fixtures:ro" worker import-official /fixtures/fia-f1-final.manifest.json
docker compose run --rm worker official-status
```

These commands use the configured persistent Docker volumes. An offline import
records `fixture` retrieval, without fabricating an HTTP status or a live check.

## Live collection and normalization

Collect the explicit official endpoints once:

```powershell
uv run --locked motorsport-research collect --catalogue config/official_sources.yaml
```

In Docker use `/app/config/official_sources.yaml` with the same `collect` command.
A successful receipt includes `source` and `document_version_id`. Save its ID,
then select a reviewed template from `config/official_contexts/`, or write a
context JSON file containing the manifest's `context` object. For
example, reuse the reviewed Bahrain context:

```powershell
uv run --locked motorsport-research normalize-official DOCUMENT_VERSION_ID --context config/official_contexts/f1-race.json
```

PowerShell may write a UTF-8 BOM; context JSON and manifest JSON accept it. A
context is reviewed input: championship/year, stable meeting key and name,
session type and number, literal class scope when relevant, expected entry count,
and an exact meeting passage in the document or URL. Changing a season, practice
number or count is rejected when it conflicts with published scope. Meeting keys
are chosen consistently by the reviewer; arbitrary new keys would create separate
logical meetings.

F1, DTM, and WEC CSV normalize a single collected document. WRC publishes entry
and timing data separately. Write `wrc-components.json` with the collected IDs:

```json
{
  "event": "DOCUMENT_VERSION_ID_FROM_wrc-api-event",
  "entries": "DOCUMENT_VERSION_ID_FROM_wrc-api-entries",
  "results": "DOCUMENT_VERSION_ID_FROM_wrc-api-results",
  "retirements": "DOCUMENT_VERSION_ID_FROM_wrc-api-retirements"
}
```

Use the `context` from `wrc-rally.manifest.json` as `wrc-context.json`:

```powershell
uv run --locked motorsport-research bundle-wrc --components wrc-components.json --context config/official_contexts/wrc-rally.json
```

Stage processing additionally requires a `stages` document and the published
`stagetimes.json` endpoint as `results`. The cumulative `results.json` endpoint
at a stage is deliberately refused for a stage-time classification. Collect `wrc-api-stages` and `wrc-api-stagetimes` explicitly with `--source`
to process the reviewed final stage. Use the latter document as `results` and
`config/official_contexts/wrc-stage17.json` as context. The captured final-stage
fixture records the exact URLs and original API responses.

For WEC class positions, collect the class table explicitly:

```powershell
uv run --locked motorsport-research collect --catalogue config/official_sources.yaml --source wec-class-results
```

Write a component map with `csv` and `classification` document IDs, then use
`config/official_contexts/wec-class-hypercar.json`:

```powershell
uv run --locked motorsport-research bundle-wec --components wec-components.json --context config/official_contexts/wec-class-hypercar.json
```

The WEC page defaults to its latest selected event/class. Review that selection;
the join refuses differing cars, entry counts, laps, or race times. Hypercar's
published table has been verified. LMGT3 is separately supported by the full CSV;
its class-table retrieval has not been verified. The CSV lacks class positions,
so those remain null until supplied by a published field or a matching class
classification. The website numbers even its non-classified/retired rows: their
published class-table positions and CSV statuses both remain visible.

Bundles retain each component URL, SHA-256 and original response text inside the
archived JSON. Bundles assembled from collected documents also retain the exact
component version IDs in record provenance. Their assembly is a manual
transformation, not a new HTTP observation.

## Values, identity and revisions

A classification key includes championship, year, meeting key, session type,
session number, and class scope. WEC overall/Hypercar/LMGT3 and DTM race one/two
have separate records. Season, meeting, and session parents keep stable versions
when their metadata is unchanged. Display names trim outer whitespace; original
names and values remain in evidence and archived bytes. Meeting-scoped identities normalize Unicode/case/outer whitespace and retain
name variants as aliases, so F1 and FIA capitalizations share a driver identity.
They avoid automatically merging people who share a name across championships.

Times and gaps remain published strings. `1 LAP`, `6L`, ISO durations, and
milliseconds stay distinguishable. Missing laps, points, class positions,
retirement or restart status stay unknown. There is no inferred zero-point score,
converted lap deficit, or computed championship scoring. Manufacturer fields are
attributed to the publisher when supplied; WEC/DTM brand labels recognized from
vehicle text explicitly use `manufacturer_basis: vehicle_prefix`.

States are `published`, `provisional`, `final`, or `amended`, with their evidence
basis. A FIA classification heading and an Alkamel filename can establish a formal
state; ordinary F1/WRC result pages do not establish finality. Repeating the same
input keeps its record and claim IDs while adding an ingestion audit. A change,
amendment, or A/B/A reversion appends a revision; previous quotes and documents
stay traceable. Normalizing a collected document creates a new text-parser version
and retains its origin version in the audit. No old migration is modified.

## FIA notices and disciplinary procedure

The `fia-notice` adapter accepts HTML, text, and bounded text-bearing PDFs. Its
reviewed context selects an exact title and statement, issuing body, jurisdiction,
affected tracked championships, notice type, and optional procedural status,
sanction and exact date passages. Repeated passages require an explicit offset.
A published FIA calendar announcement demonstrates organization-wide handling
without forcing it into F1/WEC/WRC/DTM.

Rule changes, safety/calendar/governance announcements, investigation notices,
and disciplinary decisions have explicit types. Decisions require a reviewed
procedural status and supporting passage. An investigation announcement cannot
assert an imposed penalty or attach a sanction. Every claim is attributed and
verbatim; interpretation of notice type/procedure is human-reviewed metadata,
not automated legal interpretation. Rule/investigation/appeal fixtures are clearly
synthetic and do not establish historical conduct by real people.

Day-precision publication/effective dates stay date strings in the notice payload;
unknown time zones or midnight timestamps are not invented. Dates must match a
published full day/month/year passage. A year alone cannot become January 1.
Use `related_versions` to link exact race, decision, or controversy-case versions.
A revised/overturned decision uses the same key and preserves earlier revisions.
Notice imports do not change positions, times or points in race records.

## Failure behavior and bounds

Malformed input, unsupported layouts, duplicates, missing crews, wrong scope,
conflicting joins, and expected-count mismatches refuse the entire normalization.
A failed validated ingestion is audited, with no partially accepted records or
claims. Manifest/context schema and file-checksum failures occur before ingestion
and return an input error; they do not invent an ingested document.

Files are bounded to 10 MiB; manifests/contexts to 256 KiB. Offline file paths stay
under their manifest directory. Original content and evidence hashes are verified.
PDF extraction runs in a separate process with a 15-second deadline, 50-page and
10-MiB text limits, plus a 512-MiB address-space bound in Linux/Docker. Native
Windows applies page/text/deadline limits without the Linux memory bound. Scanned,
encrypted, oversized and unfamiliar PDFs fail for review. General article cleanup
and automatic notice discovery are subsequent development work.
