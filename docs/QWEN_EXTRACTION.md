# Local Qwen extraction

Phase six calls the existing native Windows Ollama app directly through
`/api/chat`. Odysseus remains a separate interface. The configured default is
`qwen3.5-instruct:4b`; use the exact installed tag reported by `/api/tags`.
No command installs, pulls or manages a model. The cloud has no reachable real
Qwen server: model accuracy, Windows connectivity and representative throughput
remain pending in [the local checklist](LOCAL_VALIDATION.md).

## Extract and inspect

Complete [local startup](DEVELOPMENT.md), including the separate model-list
diagnostic. Docker defaults to `http://host.docker.internal:11434`; native Python
uses localhost unless overridden. Apply migrations with `db-init` before using
an existing data directory. From the repository root in PowerShell:

```powershell
docker compose run --rm worker db-init
docker compose run --rm --volume "${PWD}/tests/fixtures:/fixtures:ro" worker import-article /fixtures/qwen/dev-f1.manifest.json
docker compose run --rm worker extract-article ARTICLE_ID
docker compose run --rm worker extraction-detail TASK_ID
docker compose run --rm worker trace-claim CLAIM_ID
docker compose run --rm worker extraction-status --limit 50 --offset 0
```

Replace the IDs with those returned by the previous command. For an archived
real article, obtain its article ID with `collect-article` or `parse-article` as
described in [article preparation](ARTICLES.md). Extraction never follows links
or fetches the original article again. Irrelevant articles are retained but
refused for automatic extraction.

The model selects complete numbered source passages, with championship/topic,
literal entity mentions, attribution, date mentions, printed numeric tokens,
uncertainty and assertion type. It cannot submit a paraphrased claim. Code maps
selected passages back to exact original Unicode spans, including whitespace
and inline-markup fragments. Source bytes, text hashes and offsets are checked.

Claims stay `unassessed`, and `review_required` stays true. Assertion types retain
allegations, responses/denials, investigations, findings, decisions and corrections
separately. Literal grounding and conservative procedural checks do not establish
semantic correctness or truth. Whole passages may contain several assertions;
their type and attribution remain model suggestions requiring human review.
An official source does not automatically verify the conduct it describes.

Names and attribution must appear in the passage. Alias candidates, including
missing or ambiguous matches, are stored as suggestions; no entity is created
or automatically linked. Date text must be literal; parsed precision/timezone
uncertainty remains visible and does not set a claim's canonical event/effective
time. Numbers must be complete printed tokens: no scoring arithmetic or inferred
unit conversions. Championship assignments require explicit passage wording.
FIA announcement suggestions additionally require a source with FIA's official
homepage. Topics and date roles still need semantic review.

## Bounds, provenance and recovery

| Setting | Default | Accepted range |
| --- | --- | --- |
| `QWEN_TIMEOUT_SECONDS` | 90 | Greater than 0, at most 120 |
| `QWEN_MAX_INPUT_BYTES` | 4000 | 1500–4000 source-payload bytes per chunk |
| `QWEN_MAX_OUTPUT_TOKENS` | 1024 | 128–2048 |
| `QWEN_MAX_ATTEMPTS` | 2 | 1–3 invalid completions per chunk |
| `QWEN_MAX_CHUNKS` | 32 | 1–64 per article |

Chat uses a JSON schema, temperature zero, seed zero, context size 8192 and
`think=false`. The input-byte budget covers the source JSON payload; the fixed
system prompt and schema are additional context. Passage pieces are at most
1000 UTF-8 bytes. Oversized articles fail visibly before inference rather than
silently dropping remaining text. Chat responses are capped at 256 KiB; model
list responses at 1 MiB. Redirects, compressed responses, tool calls, duplicate
JSON keys, extra schema fields and truncated completions are refused. HTTPX
inactivity timeouts and elapsed checks bound requests; a trickling response can
take up to roughly twice the configured timeout before control returns.

Source content is untrusted input. It is separated from system instructions and
has no tools or command execution access. Exact passage selection limits invented
evidence, but does not prove universal resistance to prompt injection or guarantee
that every selected passage is useful. An empty claim list is a valid completion;
evaluation must measure missed claims separately.

Every attempt records its outcome, bounded raw response when available, duration,
token/timing metrics and model provenance. The installed model digest is pinned
and checked before and after each chat. Changed weights fail the task without
committing claims. Prompt `qwen-extractive:1` and validation pipeline
`qwen-validation:1` are retained in extraction records.

One extraction owns the inference lease at a time. Network waits happen outside
database write transactions. All chunks must validate before the article's claims
are committed atomically. Validated chunks survive an outage. An unavailable
server, missing model or timeout leaves durable `pending` work with a 30-second
retry cooldown. Invalid completions use the bounded per-chunk retry budget, then
become `failed`. There is no scheduler in this phase; retry manually:

```powershell
docker compose run --rm worker retry-extraction TASK_ID
```

Expired leases are recovered on the next extraction/retry. Retry uses the exact
saved endpoint, model and settings; if configuration changed, start a new run.
Completed/failed tasks are returned on ordinary replay without repeating model
requests. A cached completion does not probe for newly installed weights. For an
intentional fresh generation, including a changed model under the same tag:

```powershell
docker compose run --rm worker extract-article ARTICLE_ID --new-run
```

`extract-article`/`retry-extraction` exit zero for completed work and one for
pending/failed work. Status/detail reads remain successful commands. Claim
identity remains idempotent; separate runs retain their own suggestions and
provenance even when they select the same evidence.

## Evaluate on your machine

The [fixture README](../tests/fixtures/qwen/README.md) explains the development
and reserved held-out datasets. Each has six synthetic cases. Protocol mocks
exercise application behavior only; they are never evidence of actual Qwen
accuracy or hardware performance. Use an isolated evaluation database and keep
reports outside Git. Create the host output folder before mounting it:

```powershell
New-Item -ItemType Directory -Force .local-qwen-evaluation | Out-Null
docker compose run --rm --env DATA_DIR=/evaluation/data --volume "${PWD}/.local-qwen-evaluation:/evaluation" --volume "${PWD}/tests/fixtures/qwen:/dataset:ro" worker db-init
docker compose run --rm --env DATA_DIR=/evaluation/data --volume "${PWD}/.local-qwen-evaluation:/evaluation" --volume "${PWD}/tests/fixtures/qwen:/dataset:ro" worker evaluate-qwen --dataset /dataset/development.json --output /evaluation/development.json --hardware "Windows; CPU MODEL; GPU MODEL / VRAM; RAM; Ollama VERSION"
```

Inspect every prediction, source passage and failure. Freeze model, prompt and
settings before repeating the evaluation command with `/dataset/heldout.json`
and a fresh output path such as `/evaluation/heldout.json`. Changing settings
after viewing held-out results turns those cases into development data; reserve
new unseen cases for a subsequent evaluation. Output files are never overwritten.
The evaluation always creates fresh inference runs, avoiding cached timing.

Reports retain dataset SHA-256, split, self-reported hardware, model tag/digests,
expected and predicted fields, task/attempt IDs, failures, wall-clock throughput
and Ollama's reported generation throughput. Strict precision/recall require
complete passage and field agreement with manual labels, ignoring list order.
Field accuracy is reported only where quotes match. Pending/failed cases remain
visible and are not successful inference; a pending run exits one while retaining
its report and task. Retry those tasks for diagnosis, then use a new evaluation
output path for a complete timed run.

These initial cases are too small and synthetic to approve production handling.
Add representative, independently labeled real reporting across all four series,
FIA notices and controversy procedures, agree task-specific thresholds, and
review the held-out results before enabling automation. This implementation always
reports `automatic_handling_approved=false`. Phase-six acceptance remains pending
until real local inference and representative accuracy/throughput are recorded.
