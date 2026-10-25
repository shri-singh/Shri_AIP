-- 0004 - Opsi-owned operational ontology with provenance and time-scoped edges,
-- plus cross-references to OpenMetadata catalog entities.
--
-- OpenMetadata remains the source of truth for catalog metadata (tables, columns,
-- owners, domains, data lineage). This graph models *operations and causality*
-- (incident affects service, service runs_on host, evidence supports hypothesis),
-- which OpenMetadata lineage does not provide. See ADR-0003.

SET ROLE opsi_owner;

CREATE TABLE IF NOT EXISTS opsi_knowledge.entity_kinds (
    kind        text PRIMARY KEY,
    description text NOT NULL
);
INSERT INTO opsi_knowledge.entity_kinds (kind, description) VALUES
  ('service', 'Runtime service (Dynatrace SERVICE-*, k8s workload, etc.)'),
  ('host', 'Compute host / node / VM'),
  ('process_group', 'Dynatrace process group'),
  ('application', 'Business application'),
  ('database', 'Database instance (catalog entity in OpenMetadata)'),
  ('table', 'Table (catalog entity in OpenMetadata)'),
  ('incident', 'Incident / Dynatrace problem'),
  ('alert', 'Alert or alarm'),
  ('change', 'Deployment / config change'),
  ('runbook', 'Runbook or KB article'),
  ('log_source', 'Log stream / index / Grail bucket'),
  ('team', 'Owning team (mirrors OpenMetadata team)'),
  ('agent', 'AI agent or automation identity'),
  ('evidence', 'Evidence item (citation) used in an investigation'),
  ('hypothesis', 'Root-cause hypothesis under investigation'),
  ('investigation', 'Chat thread / investigation session')
ON CONFLICT (kind) DO NOTHING;

CREATE TABLE IF NOT EXISTS opsi_knowledge.relation_types (
    relation    text PRIMARY KEY,
    src_kinds   text[] NOT NULL,
    dst_kinds   text[] NOT NULL,
    is_causal   boolean NOT NULL DEFAULT false,
    description text NOT NULL
);
INSERT INTO opsi_knowledge.relation_types (relation, src_kinds, dst_kinds, is_causal, description) VALUES
  ('affects',       '{incident,alert}',          '{service,host,application,database,process_group}', false, 'Incident impact'),
  ('runs_on',       '{service,process_group}',   '{host}',                     false, 'Placement'),
  ('depends_on',    '{service,application}',     '{service,database,application}', false, 'Runtime dependency'),
  ('calls',         '{service}',                 '{service}',                  false, 'Observed call (trace topology)'),
  ('reads_from',    '{service,application}',     '{table,database}',           false, 'Data access'),
  ('writes_to',     '{service,application}',     '{table,database}',           false, 'Data access'),
  ('owned_by',      '{service,application,database,table,runbook}', '{team}',  false, 'Ownership (prefer OpenMetadata as source)'),
  ('documented_by', '{service,application,incident,alert}', '{runbook}',       false, 'Runbook link'),
  ('emits',         '{service,host}',            '{log_source}',               false, 'Log source'),
  ('changed_by',    '{service,application,host}', '{change}',                  false, 'Change applied to target'),
  ('triggered',     '{alert,change}',            '{incident}',                 true,  'Temporal/causal trigger (needs evidence)'),
  ('caused_by',     '{incident}',                '{change,incident,host,service,database}', true, 'Confirmed root cause'),
  ('supports',      '{evidence}',                '{hypothesis}',               false, 'Evidence supports hypothesis'),
  ('refutes',       '{evidence}',                '{hypothesis}',               false, 'Evidence refutes hypothesis'),
  ('explains',      '{hypothesis}',              '{incident}',                 true,  'Hypothesis explains incident'),
  ('investigates',  '{investigation,agent}',     '{incident,service}',         false, 'Investigation scope')
ON CONFLICT (relation) DO NOTHING;

CREATE TABLE IF NOT EXISTS opsi_knowledge.entities (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            text NOT NULL,
    kind                 text NOT NULL REFERENCES opsi_knowledge.entity_kinds (kind),
    natural_key          text NOT NULL,     -- SERVICE-123..., host FQDN, OM FQN, problem id
    name                 text NOT NULL,
    attributes           jsonb NOT NULL DEFAULT '{}'::jsonb,
    classification       text NOT NULL DEFAULT 'internal-confidential',
    source_system        text NOT NULL CHECK (source_system IN ('dynatrace', 'openmetadata', 'elastic', 'opsi', 'manual', 'agent', 'broadcom')),
    source_ref           text,
    external_catalog_id  uuid,              -- OpenMetadata entity UUID, when cataloged
    external_catalog_fqn text,              -- OpenMetadata fullyQualifiedName
    valid_from           timestamptz NOT NULL DEFAULT now(),
    valid_to             timestamptz,       -- NULL = currently valid
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    search_tsv           tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(name, '') || ' ' || natural_key)) STORED,
    UNIQUE (tenant_id, kind, natural_key),
    CHECK (valid_to IS NULL OR valid_to > valid_from)
);
CREATE INDEX IF NOT EXISTS ix_entities_catalog ON opsi_knowledge.entities (tenant_id, external_catalog_fqn)
    WHERE external_catalog_fqn IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_entities_tsv ON opsi_knowledge.entities USING gin (search_tsv);

CREATE TABLE IF NOT EXISTS opsi_knowledge.edges (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      text NOT NULL,
    src_id         uuid NOT NULL REFERENCES opsi_knowledge.entities (id) ON DELETE CASCADE,
    dst_id         uuid NOT NULL REFERENCES opsi_knowledge.entities (id) ON DELETE CASCADE,
    relation       text NOT NULL REFERENCES opsi_knowledge.relation_types (relation),
    valid_from     timestamptz NOT NULL,
    valid_to       timestamptz,               -- NULL = still true
    confidence     numeric(4, 3) NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    source_system  text NOT NULL CHECK (source_system IN ('dynatrace', 'openmetadata', 'elastic', 'opsi', 'manual', 'agent', 'broadcom')),
    source_ref     text,                      -- e.g. dynatrace smartscape query id, OM lineage edge, chat message
    provenance     jsonb NOT NULL DEFAULT '{}'::jsonb,   -- {method, run_id, actor, model_ref, evidence_keys[]}
    evidence_ref   text,                      -- citation pointer backing this edge
    classification text NOT NULL DEFAULT 'internal-confidential',
    created_by     text NOT NULL,             -- user id, 'collector:<name>' or 'agent:<id>'
    created_at     timestamptz NOT NULL DEFAULT now(),
    CHECK (src_id <> dst_id),
    CHECK (valid_to IS NULL OR valid_to > valid_from),
    -- agent-inferred causal edges must carry evidence and cannot claim certainty
    CHECK (source_system <> 'agent' OR (evidence_ref IS NOT NULL AND confidence < 1.0))
);
-- at most one *open* edge per (src, relation, dst); history is kept as closed rows
CREATE UNIQUE INDEX IF NOT EXISTS ux_edges_open ON opsi_knowledge.edges (tenant_id, src_id, relation, dst_id)
    WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS ix_edges_src ON opsi_knowledge.edges (tenant_id, src_id, relation, valid_from);
CREATE INDEX IF NOT EXISTS ix_edges_dst ON opsi_knowledge.edges (tenant_id, dst_id, relation, valid_from);

-- Bounded, time-scoped neighbourhood. Callers must pass small depth/limit values.
CREATE OR REPLACE FUNCTION opsi_knowledge.neighborhood(
    p_entity uuid, p_at timestamptz DEFAULT now(), p_max_depth int DEFAULT 2, p_limit int DEFAULT 200)
RETURNS TABLE (depth int, edge_id uuid, src_id uuid, relation text, dst_id uuid, confidence numeric,
               source_system text, evidence_ref text)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
  WITH RECURSIVE walk AS (
      SELECT 1 AS depth, e.id AS edge_id, e.src_id, e.relation, e.dst_id, e.confidence, e.source_system,
             e.evidence_ref, ARRAY[e.src_id, e.dst_id] AS path
      FROM opsi_knowledge.edges e
      WHERE (e.src_id = p_entity OR e.dst_id = p_entity)
        AND e.valid_from <= p_at AND (e.valid_to IS NULL OR e.valid_to > p_at)
    UNION ALL
      SELECT w.depth + 1, e.id, e.src_id, e.relation, e.dst_id, e.confidence, e.source_system, e.evidence_ref,
             w.path || CASE WHEN e.src_id = ANY (w.path) THEN e.dst_id ELSE e.src_id END
      FROM walk w
      JOIN opsi_knowledge.edges e
        ON (e.src_id = ANY (ARRAY[w.src_id, w.dst_id]) OR e.dst_id = ANY (ARRAY[w.src_id, w.dst_id]))
       AND e.id <> w.edge_id
       AND e.valid_from <= p_at AND (e.valid_to IS NULL OR e.valid_to > p_at)
      WHERE w.depth < least(p_max_depth, 4)
        AND NOT (e.src_id = ANY (w.path) AND e.dst_id = ANY (w.path))
  )
  SELECT DISTINCT ON (edge_id) depth, edge_id, src_id, relation, dst_id, confidence, source_system, evidence_ref
  FROM walk
  ORDER BY edge_id, depth
  LIMIT least(p_limit, 1000);
$$;

CREATE TABLE IF NOT EXISTS opsi_knowledge.catalog_xrefs (
    tenant_id      text NOT NULL,
    entity_id      uuid NOT NULL REFERENCES opsi_knowledge.entities (id) ON DELETE CASCADE,
    om_entity_type text NOT NULL CHECK (om_entity_type IN ('table', 'database', 'databaseSchema', 'databaseService',
                                        'dashboard', 'pipeline', 'topic', 'glossaryTerm', 'team', 'user', 'domain',
                                        'dataProduct', 'storedProcedure', 'apiEndpoint')),
    om_id          uuid,
    om_fqn         text NOT NULL,
    om_version     numeric,
    last_synced_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, om_entity_type, om_fqn)
);
CREATE INDEX IF NOT EXISTS ix_xrefs_entity ON opsi_knowledge.catalog_xrefs (entity_id);

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA opsi_knowledge TO opsi_app;
GRANT SELECT ON ALL TABLES IN SCHEMA opsi_knowledge TO opsi_readonly;
GRANT EXECUTE ON FUNCTION opsi_knowledge.neighborhood(uuid, timestamptz, int, int) TO opsi_app, opsi_readonly;
REVOKE INSERT, UPDATE, DELETE ON opsi_knowledge.entity_kinds, opsi_knowledge.relation_types FROM opsi_app;

RESET ROLE;
