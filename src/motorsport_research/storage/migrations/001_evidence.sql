CREATE TABLE sources (
    id TEXT PRIMARY KEY,
    source_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('official', 'independent', 'unknown')),
    upstream_source_id TEXT REFERENCES sources(id),
    created_at TEXT NOT NULL
);
CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    canonical_url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(source_id, canonical_url)
);
CREATE TABLE document_versions (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    revision INTEGER NOT NULL CHECK(revision > 0),
    revision_hash TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    extracted_text TEXT NOT NULL,
    title TEXT NOT NULL,
    author TEXT,
    published_at TEXT,
    source_timezone TEXT,
    parser_version TEXT NOT NULL,
    media_type TEXT NOT NULL,
    first_retrieved_at TEXT NOT NULL,
    UNIQUE(document_id, revision)
);
CREATE TABLE retrievals (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    requested_url TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    method TEXT NOT NULL CHECK(method IN ('manual', 'http', 'browser', 'fixture')),
    outcome TEXT NOT NULL CHECK(outcome IN ('success', 'not_modified', 'denied', 'failed')),
    http_status INTEGER CHECK(http_status BETWEEN 100 AND 599),
    error TEXT,
    document_version_id TEXT REFERENCES document_versions(id),
    recorded_at TEXT NOT NULL,
    CHECK(method NOT IN ('manual', 'fixture') OR http_status IS NULL),
    CHECK(outcome != 'success' OR document_version_id IS NOT NULL)
);
CREATE TABLE championships (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
INSERT INTO championships(id, name) VALUES
    ('F1', 'Formula 1'), ('WEC', 'World Endurance Championship'),
    ('WRC', 'World Rally Championship'), ('DTM', 'DTM');
CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    identity_key TEXT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(kind, identity_key)
);
CREATE TABLE entity_aliases (
    entity_id TEXT NOT NULL REFERENCES entities(id),
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    championship_id TEXT REFERENCES championships(id)
);
CREATE UNIQUE INDEX entity_alias_identity ON entity_aliases(
    entity_id, normalized_alias, coalesce(championship_id, '')
);
CREATE INDEX entity_alias_lookup ON entity_aliases(normalized_alias, championship_id);
CREATE TABLE extraction_runs (
    id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_versions(id),
    parser_version TEXT NOT NULL,
    model_tag TEXT,
    model_version TEXT,
    prompt_version TEXT,
    status TEXT NOT NULL CHECK(status IN ('success', 'failed')),
    created_at TEXT NOT NULL
);
CREATE TABLE claims (
    id TEXT PRIMARY KEY,
    identity_hash TEXT NOT NULL UNIQUE,
    statement TEXT NOT NULL,
    assertion_type TEXT NOT NULL,
    asserted_by_entity_id TEXT REFERENCES entities(id),
    supersedes_claim_id TEXT REFERENCES claims(id),
    event_at TEXT,
    effective_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE claim_entities (
    claim_id TEXT NOT NULL REFERENCES claims(id),
    entity_id TEXT NOT NULL REFERENCES entities(id),
    PRIMARY KEY(claim_id, entity_id)
);
CREATE TABLE claim_evidence (
    id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES claims(id),
    document_version_id TEXT NOT NULL REFERENCES document_versions(id),
    quote TEXT NOT NULL CHECK(length(trim(quote)) > 0),
    start_offset INTEGER NOT NULL CHECK(start_offset >= 0),
    end_offset INTEGER NOT NULL CHECK(end_offset > start_offset),
    relation TEXT NOT NULL CHECK(relation IN ('reports', 'supports', 'contradicts', 'response', 'correction')),
    UNIQUE(claim_id, document_version_id, start_offset, end_offset, relation)
);
CREATE TABLE claim_extraction_runs (
    claim_id TEXT NOT NULL REFERENCES claims(id),
    extraction_run_id TEXT NOT NULL REFERENCES extraction_runs(id),
    PRIMARY KEY(claim_id, extraction_run_id)
);
CREATE TRIGGER evidence_span_matches BEFORE INSERT ON claim_evidence
WHEN NEW.quote != (
    SELECT substr(extracted_text, NEW.start_offset + 1, NEW.end_offset - NEW.start_offset)
    FROM document_versions WHERE id = NEW.document_version_id
)
BEGIN
    SELECT RAISE(ABORT, 'Evidence quote does not match its document span');
END;
