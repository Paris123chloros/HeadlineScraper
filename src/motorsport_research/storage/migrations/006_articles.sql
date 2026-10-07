CREATE TABLE article_parses (
    id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_versions(id),
    parser_version TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    registry_hash TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK(outcome IN ('relevant', 'irrelevant')),
    result_json TEXT NOT NULL CHECK(json_valid(result_json)),
    created_at TEXT NOT NULL,
    UNIQUE(document_version_id, parser_version, rules_version, registry_hash)
);
CREATE INDEX article_body_duplicates ON article_parses(body_hash);
CREATE TABLE article_attempts (
    id TEXT PRIMARY KEY,
    document_version_id TEXT NOT NULL REFERENCES document_versions(id),
    parser_version TEXT NOT NULL,
    rules_version TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK(outcome IN ('relevant', 'irrelevant', 'parser_failure', 'unsupported_format', 'access_denied')),
    article_id TEXT REFERENCES article_parses(id),
    detail TEXT,
    created_at TEXT NOT NULL,
    CHECK((article_id IS NOT NULL AND outcome IN ('relevant', 'irrelevant') AND detail IS NULL)
       OR (article_id IS NULL AND outcome NOT IN ('relevant', 'irrelevant') AND detail IS NOT NULL))
);
CREATE INDEX article_attempts_created ON article_attempts(created_at);
CREATE TRIGGER article_parse_no_update BEFORE UPDATE ON article_parses
BEGIN
    SELECT RAISE(ABORT, 'Article history is immutable');
END;
CREATE TRIGGER article_parse_no_delete BEFORE DELETE ON article_parses
BEGIN
    SELECT RAISE(ABORT, 'Article history is immutable');
END;
CREATE TRIGGER article_attempt_no_update BEFORE UPDATE ON article_attempts
BEGIN
    SELECT RAISE(ABORT, 'Article attempt history is immutable');
END;
CREATE TRIGGER article_attempt_no_delete BEFORE DELETE ON article_attempts
BEGIN
    SELECT RAISE(ABORT, 'Article attempt history is immutable');
END;
