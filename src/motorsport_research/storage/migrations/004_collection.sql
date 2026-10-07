CREATE TABLE source_configurations (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    config_hash TEXT NOT NULL,
    config_json TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE(source_id, config_hash)
);
CREATE TABLE collection_runs (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    configuration_id TEXT NOT NULL REFERENCES source_configurations(id),
    requested_url TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    next_due_at TEXT NOT NULL,
    outcome TEXT NOT NULL,
    detail TEXT,
    document_version_id TEXT REFERENCES document_versions(id)
);
CREATE INDEX collection_run_latest ON collection_runs(source_id, finished_at DESC);
CREATE TABLE collection_requests (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES collection_runs(id) DEFERRABLE INITIALLY DEFERRED,
    requested_url TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    outcome TEXT NOT NULL,
    http_status INTEGER CHECK(http_status BETWEEN 100 AND 599),
    received_bytes INTEGER NOT NULL CHECK(received_bytes >= 0),
    content_hash TEXT,
    etag TEXT,
    last_modified TEXT,
    detail TEXT
);
CREATE TABLE collection_cache (
    source_id TEXT NOT NULL REFERENCES sources(id),
    config_hash TEXT NOT NULL,
    requested_url TEXT NOT NULL,
    effective_url TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    document_version_id TEXT NOT NULL REFERENCES document_versions(id),
    etag TEXT,
    last_modified TEXT,
    checked_at TEXT NOT NULL,
    PRIMARY KEY(source_id, config_hash, requested_url)
);
CREATE TABLE collection_hosts (
    host TEXT PRIMARY KEY,
    next_allowed_epoch REAL NOT NULL
);
CREATE TABLE discovered_links (
    document_version_id TEXT NOT NULL REFERENCES document_versions(id),
    position INTEGER NOT NULL CHECK(position >= 0),
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    item_key TEXT,
    published_at TEXT,
    source_timezone TEXT,
    PRIMARY KEY(document_version_id, position)
);
CREATE TRIGGER source_configuration_no_update BEFORE UPDATE ON source_configurations
BEGIN
    SELECT RAISE(ABORT, 'Source configuration history is immutable');
END;
CREATE TRIGGER source_configuration_no_delete BEFORE DELETE ON source_configurations
BEGIN
    SELECT RAISE(ABORT, 'Source configuration history is immutable');
END;
CREATE TRIGGER collection_run_no_update BEFORE UPDATE ON collection_runs
BEGIN
    SELECT RAISE(ABORT, 'Collection history is immutable');
END;
CREATE TRIGGER collection_run_no_delete BEFORE DELETE ON collection_runs
BEGIN
    SELECT RAISE(ABORT, 'Collection history is immutable');
END;
CREATE TRIGGER collection_request_no_update BEFORE UPDATE ON collection_requests
BEGIN
    SELECT RAISE(ABORT, 'Collection history is immutable');
END;
CREATE TRIGGER collection_request_no_delete BEFORE DELETE ON collection_requests
BEGIN
    SELECT RAISE(ABORT, 'Collection history is immutable');
END;
CREATE TRIGGER discovery_no_update BEFORE UPDATE ON discovered_links
BEGIN
    SELECT RAISE(ABORT, 'Discovery history is immutable');
END;
CREATE TRIGGER discovery_no_delete BEFORE DELETE ON discovered_links
BEGIN
    SELECT RAISE(ABORT, 'Discovery history is immutable');
END;
