# Official-record fixture provenance

These are development reference captures taken on 2026-10-07, plus explicitly
synthetic procedure examples. Each manifest records its publisher URL, source
attribution, capture date, exact file hash, reviewed scope and expected entry count.
`captured_at` records the UTC filesystem time when the source capture was
written after retrieval, or when a synthetic fixture was created. Exact HTTP
attempt timestamps are recorded by separate live collector checks. Imports record `fixture`, never HTTP 200.

F1 HTML files retain the exact first h1 and complete results table from the
published page. Their manifests retain the original full-response SHA-256 and
mark `excerpt`. Bahrain 2024 includes every entry in three practices, qualifying,
and the race. Miami 2024 includes the complete sprint table. The published final FIA
race PDF is retained in full, as an independent classification source. Driver
and constructor standings include every published 2024 entry.

WEC's Fuji 2026 final timing CSV retains all 35 entries, including the 17 Hypercar
and 18 LMGT3 entries. Class-scope manifests reuse that exact file. The Hypercar
class archive contains the original CSV and complete official results-page HTML,
with each component's original text, URL and checksum. That page's current event
and class were reviewed, then joined on number, laps and race time. Its published
class positions include non-classified/retired entries; CSV statuses stay separate.
No LMGT3 class table is claimed as verified.

DTM's shared JSON fixture retains the complete publisher event objects for Red
Bull Ring 2026, including all seven results sessions. The manifests mark the
response as an excerpt from the season query and retain the original full-season
response hash. The live catalogue uses a smaller meeting query to avoid the
full-season response's unsupported compressed encoding.

WRC archives join the exact public API responses used by WRC's official results
component: event, entries, classification, retirements, and stages when applicable.
Each component contains its original text, URL and SHA-256. These JSON archives
are assembled evidence bundles, not direct single-endpoint HTTP responses.
Monte Carlo 2026 includes all 48 rally classification rows and all 56 final-stage
time rows. Retirements remain attributed notices; an entry missing from results
does not acquire an invented classification or status.

The FIA calendar notice is a real complete HTML capture. It concerns F2/F3 and
is deliberately unassigned to the four tracked championships, demonstrating that
FIA-wide notices do not automatically acquire an unsupported F1 designation.
The rule-change, investigation, imposed-penalty and overturned-decision files
are **synthetic**, attributed to an `unknown` source at `example.invalid`. The
amendment/reversion test also constructs fictional crews at `example.invalid`.
They validate procedure handling without asserting misconduct by real people.

`reference-results.json` contains fixed field vectors transcribed directly from
captured publisher tables/API fields, independently of the production adapters.
All 421 rows across 17 classifications are compared on number, position, crew,
team, class, laps, time, gap and points. Display names trim outer whitespace;
for example WRC's published `MJ ` is displayed as `MJ`, with the original bytes
and quote retained. Additional assertions check published FIA classifications,
class-table joins, sprint points, standings, known winners and statuses.
These are development checks, not a held-out accuracy evaluation or proof of
independent corroboration for all the data.

Git attributes preserve these files' exact bytes across checkouts, including
CSV CRLF line endings and original HTML whitespace, so capture checksums remain
stable when developing on Windows.
