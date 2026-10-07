CREATE TABLE records (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN (
        'season', 'meeting', 'session', 'classification', 'decision',
        'announcement', 'controversy_case', 'event', 'report_snapshot'
    )),
    record_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(kind, record_key)
);
CREATE TABLE record_versions (
    id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL REFERENCES records(id),
    revision INTEGER NOT NULL CHECK(revision > 0),
    revision_hash TEXT NOT NULL,
    title TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    document_version_id TEXT REFERENCES document_versions(id),
    issuer_entity_id TEXT REFERENCES entities(id),
    jurisdiction TEXT,
    case_status TEXT CHECK(case_status IN ('alleged', 'under_investigation', 'findings_issued', 'under_appeal', 'closed')),
    outcome TEXT CHECK(outcome IN ('sanctioned', 'cleared', 'overturned', 'unresolved')),
    published_at TEXT,
    event_at TEXT,
    effective_at TEXT,
    parser_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK(case_status != 'closed' OR outcome IS NOT NULL),
    UNIQUE(record_id, revision)
);
CREATE TABLE record_championships (
    record_version_id TEXT NOT NULL REFERENCES record_versions(id),
    championship_id TEXT NOT NULL REFERENCES championships(id),
    PRIMARY KEY(record_version_id, championship_id)
);
CREATE TABLE record_entities (
    record_version_id TEXT NOT NULL REFERENCES record_versions(id),
    entity_id TEXT NOT NULL REFERENCES entities(id),
    PRIMARY KEY(record_version_id, entity_id)
);
CREATE TABLE record_claims (
    record_version_id TEXT NOT NULL REFERENCES record_versions(id),
    claim_id TEXT NOT NULL REFERENCES claims(id),
    PRIMARY KEY(record_version_id, claim_id)
);
CREATE TABLE record_links (
    record_version_id TEXT NOT NULL REFERENCES record_versions(id),
    related_version_id TEXT NOT NULL REFERENCES record_versions(id),
    relation TEXT NOT NULL,
    PRIMARY KEY(record_version_id, related_version_id, relation)
);
CREATE TABLE claim_assessments (
    id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES claims(id),
    label TEXT NOT NULL CHECK(label IN (
        'officially_announced', 'independently_corroborated', 'single_source',
        'disputed', 'corrected', 'superseded'
    )),
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    status TEXT NOT NULL CHECK(status IN ('pending', 'running', 'completed', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
    available_at TEXT NOT NULL,
    lease_until TEXT,
    created_at TEXT NOT NULL
);
