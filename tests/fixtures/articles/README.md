# Reviewed article fixtures

`race`, `contract`, `rumor`, `opinion`, `fia`, `allegation`, `response`, `unrelated`,
`updated`, `copy` and `syndicated` are explicitly synthetic. Their manifests retain
creation times and SHA256 values. No invented result, allegation or signing is
evidence about a real person/team. `expected.json` contains independently authored
body, topic, championship, label, procedural-cue and relevance expectations.

`updated` shares the race URL, corrects twenty laps to twenty-one, and adds a
separate modification date. Copies preserve bodies with distinct publisher keys
and URLs. Tests declare a shared upstream using a real database source ID.

The four `captured-*` series pages are full public Motorsport.com HTML responses
retrieved on 2026-10-07. Manifests retain URLs, publisher names, exact capture times
and checksums. Tests review actual body beginnings/endings and authors, and require
related stories/survey UI removal. The F1-feed item concerns Dakar and mentions F1:
feed membership never becomes an affected-championship assertion.

`captured-fia` reuses the phase-four FIA calendar page with its original capture
time/bytes. It covers lead/body, tables, inline markup, dates and related-news removal.

HTML is retained verbatim, with newline conversion disabled in `.gitattributes`.
Script/analytics elements are inert fixture data, never executed/fetched. Tests are
offline; separate live validation uses bounded collection for connectivity evidence.
