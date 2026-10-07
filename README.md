This is a simple Bot i wrote in order to practice Python and coding in general.
This bot has a simple task:
  *Go to espn.com/racing
  *Click "Accept" on the onetrust container
  *Scrape <h2> headlines
  *Save them into a csv

Hope this helps anyone that is new and learing

## Motorsport research development

The next version is planned as a local Docker application covering F1, WEC, WRC,
and DTM, with sourced events, race records, and automated English digests. It will
reuse an existing Ollama container for local Qwen extraction.

See the [development plan](docs/DEVELOPMENT_PLAN.md) for implementation segments,
dependencies, architecture decisions, and acceptance checks. The existing scraper
remains the current implementation; the planned application is not built yet.
