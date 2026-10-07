CREATE TABLE qwen_tasks (
    id TEXT PRIMARY KEY,
    request_hash TEXT NOT NULL UNIQUE,
    article_id TEXT NOT NULL REFERENCES article_parses(id),
    model_tag TEXT NOT NULL,
    model_digest TEXT,
    prompt_version TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    config_json TEXT NOT NULL CHECK(json_valid(config_json)),
    status TEXT NOT NULL CHECK(status IN ('pending', 'running', 'completed', 'failed')),
    owner TEXT,
    lease_until TEXT,
    retry_at TEXT,
    detail TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE qwen_chunks (
    task_id TEXT NOT NULL REFERENCES qwen_tasks(id),
    position INTEGER NOT NULL,
    input_json TEXT NOT NULL CHECK(json_valid(input_json)),
    input_hash TEXT NOT NULL,
    result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
    PRIMARY KEY(task_id, position)
);
CREATE TABLE qwen_attempts (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES qwen_tasks(id),
    chunk_position INTEGER,
    model_digest TEXT,
    outcome TEXT NOT NULL CHECK(outcome IN ('validated', 'invalid_response', 'invalid_evidence', 'unavailable', 'timeout', 'model_missing', 'model_changed')),
    response_hash TEXT,
    metrics_json TEXT NOT NULL CHECK(json_valid(metrics_json)),
    elapsed_seconds REAL NOT NULL CHECK(elapsed_seconds >= 0),
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE qwen_claims (
    task_id TEXT NOT NULL REFERENCES qwen_tasks(id),
    claim_id TEXT NOT NULL REFERENCES claims(id),
    extraction_run_id TEXT NOT NULL REFERENCES extraction_runs(id),
    metadata_json TEXT NOT NULL CHECK(json_valid(metadata_json)),
    PRIMARY KEY(task_id, claim_id)
);
CREATE INDEX qwen_attempt_lookup ON qwen_attempts(task_id, chunk_position);
CREATE TRIGGER qwen_attempt_no_update BEFORE UPDATE ON qwen_attempts
BEGIN
    SELECT RAISE(ABORT, 'Inference attempts are immutable');
END;
CREATE TRIGGER qwen_attempt_no_delete BEFORE DELETE ON qwen_attempts
BEGIN
    SELECT RAISE(ABORT, 'Inference attempts are immutable');
END;
CREATE TRIGGER qwen_claim_no_update BEFORE UPDATE ON qwen_claims
BEGIN
    SELECT RAISE(ABORT, 'Inference claim provenance is immutable');
END;
CREATE TRIGGER qwen_claim_no_delete BEFORE DELETE ON qwen_claims
BEGIN
    SELECT RAISE(ABORT, 'Inference claim provenance is immutable');
END;
