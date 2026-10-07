CREATE TRIGGER immutable_document_versions_update BEFORE UPDATE ON document_versions
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_document_versions_delete BEFORE DELETE ON document_versions
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_claims_update BEFORE UPDATE ON claims
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_claims_delete BEFORE DELETE ON claims
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_claim_evidence_update BEFORE UPDATE ON claim_evidence
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_claim_evidence_delete BEFORE DELETE ON claim_evidence
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_extraction_runs_update BEFORE UPDATE ON extraction_runs
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_extraction_runs_delete BEFORE DELETE ON extraction_runs
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_record_versions_update BEFORE UPDATE ON record_versions
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_record_versions_delete BEFORE DELETE ON record_versions
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_record_championships_update BEFORE UPDATE ON record_championships
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_record_championships_delete BEFORE DELETE ON record_championships
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_record_entities_update BEFORE UPDATE ON record_entities
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_record_entities_delete BEFORE DELETE ON record_entities
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_record_claims_update BEFORE UPDATE ON record_claims
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_record_claims_delete BEFORE DELETE ON record_claims
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_claim_entities_update BEFORE UPDATE ON claim_entities
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_claim_entities_delete BEFORE DELETE ON claim_entities
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_claim_extraction_runs_update BEFORE UPDATE ON claim_extraction_runs
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_claim_extraction_runs_delete BEFORE DELETE ON claim_extraction_runs
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_claim_assessments_update BEFORE UPDATE ON claim_assessments
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_claim_assessments_delete BEFORE DELETE ON claim_assessments
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_record_links_update BEFORE UPDATE ON record_links
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
CREATE TRIGGER immutable_record_links_delete BEFORE DELETE ON record_links
BEGIN
    SELECT RAISE(ABORT, 'Historical records are immutable');
END;
