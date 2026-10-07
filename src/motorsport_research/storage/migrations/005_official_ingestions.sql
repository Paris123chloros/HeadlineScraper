CREATE TABLE official_ingestions (
    id TEXT PRIMARY KEY,
    origin_document_version_id TEXT REFERENCES document_versions(id),
    document_version_id TEXT REFERENCES document_versions(id),
    adapter TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    context_json TEXT NOT NULL CHECK (json_valid(context_json)),
    outcome TEXT NOT NULL CHECK (outcome IN ('success', 'failed')),
    error TEXT,
    record_version_id TEXT REFERENCES record_versions(id),
    created_at TEXT NOT NULL,
    CHECK ((outcome = 'success' AND document_version_id IS NOT NULL AND record_version_id IS NOT NULL AND error IS NULL)
        OR (outcome = 'failed' AND record_version_id IS NULL AND error IS NOT NULL))
);
CREATE INDEX official_ingestions_created ON official_ingestions(created_at, id);
