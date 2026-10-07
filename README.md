# Motorsport Research

A local motorsport research project covering F1, WEC, WRC, and DTM. The planned
workflow collects race records, driver and sport news, FIA announcements, and
scandal/controversy reporting into sourced events and automated English digests.
It reuses an existing Ollama container with configurable `qwen3.5-instruct:4b`.

Phase one implements the Python package, validated configuration, CLI, Docker
foundation, liveness endpoint, and a read-only Ollama model diagnostic. Collection,
persistent evidence records, the event feed, and automated reports are subsequent
development phases.

- [Windows Docker and development guide](docs/DEVELOPMENT.md): setup, shared Ollama
  networking, configuration, CLI commands, and tests.
- [Development plan](docs/DEVELOPMENT_PLAN.md): 12 implementation segments with
  dependencies, deliverables, and acceptance checks.
- [Validation results](docs/VALIDATION.md): checks performed and remaining limits.

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
