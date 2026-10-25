-- 0006 - OPTIONAL vector knowledge (runbooks, RCA summaries, incident write-ups).
-- Apply only after: (1) DBA approves the extension, (2) the embedding model and
-- its dimension are fixed, (3) storage/memory impact is reviewed.
-- Never embed raw log lines. Typical volume: 10^3-10^5 chunks.
--
-- DIMENSION: 1024 matches common Bedrock embedding models at their default/large
-- setting (verify for the model you pick: `aws bedrock get-foundation-model ...`).
-- Changing the dimension later = new column + re-embed; plan for it.
--
-- Requires: CREATE EXTENSION privilege (RDS/Aurora: rds_superuser), pgvector >= 0.5 for HNSW.

CREATE EXTENSION IF NOT EXISTS vector;

SET ROLE opsi_owner;

CREATE TABLE IF NOT EXISTS opsi_knowledge.documents (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       text NOT NULL,
    doc_type        text NOT NULL CHECK (doc_type IN ('runbook', 'rca', 'incident_summary', 'kb', 'postmortem')),
    title           text NOT NULL,
    source_ref      text NOT NULL,             -- e.g. confluence://..., s3://..., opsi://incident/...
    entity_id       uuid REFERENCES opsi_knowledge.entities (id) ON DELETE SET NULL,
    classification  text NOT NULL DEFAULT 'internal-confidential',
    chunk_index     integer NOT NULL DEFAULT 0,
    content_excerpt text NOT NULL,             -- the chunk text (redacted), shown as citation snippet
    content_sha256  text NOT NULL,
    embedding       vector(1024) NOT NULL,
    embedding_model text NOT NULL,             -- record the exact model id/version used
    valid_to        timestamptz,               -- retire superseded runbooks instead of deleting
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, source_ref, chunk_index, embedding_model)
);
CREATE INDEX IF NOT EXISTS ix_documents_hnsw ON opsi_knowledge.documents
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS ix_documents_type ON opsi_knowledge.documents (tenant_id, doc_type) WHERE valid_to IS NULL;

ALTER TABLE opsi_knowledge.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE opsi_knowledge.documents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON opsi_knowledge.documents;
CREATE POLICY tenant_isolation ON opsi_knowledge.documents AS RESTRICTIVE FOR ALL
  USING (tenant_id = opsi_meta.current_tenant()) WITH CHECK (tenant_id = opsi_meta.current_tenant());
DROP POLICY IF EXISTS tenant_members ON opsi_knowledge.documents;
CREATE POLICY tenant_members ON opsi_knowledge.documents FOR ALL USING (true) WITH CHECK (true);

GRANT SELECT, INSERT, UPDATE, DELETE ON opsi_knowledge.documents TO opsi_app;
GRANT SELECT ON opsi_knowledge.documents TO opsi_readonly;

RESET ROLE;
