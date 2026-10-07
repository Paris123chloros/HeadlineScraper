# Motorsport Research

A local motorsport research project covering F1, WEC, WRC, and DTM. The planned
workflow collects race records, driver and sport news, FIA announcements, and
scandal/controversy reporting into sourced events and automated English digests.
It connects to the existing native Windows Ollama app with configurable
`qwen3.5-instruct:4b`. The user's Docker-hosted Odysseus remains a separate interface.

Phases one through three implement the Python package, validated configuration, CLI,
Docker foundation, health endpoints, Ollama diagnostic, database migrations,
versioned documents, entity aliases, evidence-linked claims, and one-shot HTTP/RSS
collection with source status and history. Live collection is verified for all four
series and FIA news; official DTM collection still needs an adapter. Race-data
extraction, the event feed, and reports remain later phases.

- [Windows Docker and development guide](docs/DEVELOPMENT.md): setup, native Ollama
  connectivity, configuration, CLI commands, and tests.
- [Development plan](docs/DEVELOPMENT_PLAN.md): 12 implementation segments with
  dependencies, deliverables, and acceptance checks.
- [Validation results](docs/VALIDATION.md): checks performed and remaining limits.
- [Evidence storage](docs/STORAGE.md): migrations, offline imports, revision history,
  and claim traceability.
- [Source collection](docs/COLLECTION.md): catalogue, CLI usage, caching, failure history,
  and current coverage limits.
- [Deferred local checks](docs/LOCAL_VALIDATION.md): Windows/Ollama checks to revisit
  when the user can access their machine.

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
