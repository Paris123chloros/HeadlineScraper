# Motorsport Research

A local motorsport research project covering F1, WEC, WRC, and DTM. The planned
workflow collects race records, driver and sport news, FIA announcements, and
scandal/controversy reporting into sourced events and automated English digests.
It connects to the existing native Windows Ollama app with configurable
`qwen3.5-instruct:4b`. The user's Docker-hosted Odysseus remains a separate interface.

Phases one through five provide local Docker startup, evidence storage, bounded
HTTP/RSS collection, official-result parsers and article preparation for all four
series. Structured
classifications, published F1 standings, reviewed FIA notices, and decision
revisions retain their source evidence. Live collection and normalization are
verified for representative official results from each series. Articles retain
readable bodies with exact source spans, uncertain dates, topic/identity hints,
rumor/opinion labels, revisions and copy hints. Qwen inference, event grouping,
scheduling, the event feed, and reports are the next development segments.

- [Windows Docker and development guide](docs/DEVELOPMENT.md): setup, native Ollama
  connectivity, configuration, CLI commands, and tests.
- [Development plan](docs/DEVELOPMENT_PLAN.md): 12 implementation segments with
  dependencies, deliverables, and acceptance checks.
- [Validation results](docs/VALIDATION.md): checks performed and remaining limits.
- [Evidence storage](docs/STORAGE.md): migrations, offline imports, revision history,
  and claim traceability.
- [Official sporting records](docs/OFFICIAL_RECORDS.md): result adapters, live and
  offline commands, class/session identity, FIA notices, and revisions.
- [Source collection](docs/COLLECTION.md): catalogue, CLI usage, caching, failure history,
  and current coverage limits.
- [Deferred local checks](docs/LOCAL_VALIDATION.md): Windows/Ollama checks to revisit
  when the user can access their machine.
- [Article preparation](docs/ARTICLES.md): explicit article collection, parsing,
  source spans, filtering, uncertainty, copies and revisions.

## Original Selenium prototype

This project began as a Python learning exercise: open ESPN's racing page, accept
its cookie banner, extract headlines, and write a CSV. `run.py` and `motosport/`
remain unchanged and available through the optional `legacy` dependency extra:

```powershell
uv run --locked --extra legacy python run.py
```

The prototype requires Chrome/driver availability and access to the configured
website. The new foundation image provides the research application's startup
workflow; browser collection receives its own adapter in a later phase.
