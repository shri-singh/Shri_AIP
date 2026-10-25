-- 0001 - group roles and schemas for the revamp. DBA REVIEW REQUIRED.
--
-- Roles are NOLOGIN *groups*. The DBA creates LOGIN users (passwords from
-- Secrets Manager / IAM auth) and grants them a group, e.g.:
--   CREATE ROLE opsi_api_svc LOGIN PASSWORD '...' IN ROLE opsi_app;
--   CREATE ROLE opsi_collector_svc LOGIN PASSWORD '...' IN ROLE opsi_ingest_writer;
-- Requires CREATEROLE (on RDS/Aurora: run as the master user / rds_superuser member).
--
-- Separation of duties:
--   opsi_owner          owns schemas/tables; used only by migrations (via SET ROLE)
--   opsi_app            FastAPI runtime: chat + knowledge DML, read curated ingest; subject to RLS
--   opsi_ingest_writer  collectors' index stage: write opsi_ingest only
--   opsi_readonly       reporting/analysts: read curated data; subject to RLS
-- None of these roles has BYPASSRLS.

DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['opsi_owner', 'opsi_app', 'opsi_ingest_writer', 'opsi_readonly'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS', r);
    END IF;
  END LOOP;
END $$;

-- The migrating user must be able to SET ROLE opsi_owner.
DO $$
BEGIN
  IF NOT pg_has_role(current_user, 'opsi_owner', 'MEMBER') THEN
    EXECUTE format('GRANT opsi_owner TO %I', current_user);
  END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS opsi_ingest    AUTHORIZATION opsi_owner;
CREATE SCHEMA IF NOT EXISTS opsi_chat      AUTHORIZATION opsi_owner;
CREATE SCHEMA IF NOT EXISTS opsi_knowledge AUTHORIZATION opsi_owner;
CREATE SCHEMA IF NOT EXISTS opsi_audit     AUTHORIZATION opsi_owner;

-- Nobody gets implicit CREATE in these schemas.
REVOKE ALL ON SCHEMA opsi_ingest, opsi_chat, opsi_knowledge, opsi_audit FROM PUBLIC;

-- opsi_meta (created in 0000) holds the RLS helper functions; owner may create there, others only use.
GRANT USAGE, CREATE ON SCHEMA opsi_meta TO opsi_owner;
GRANT USAGE ON SCHEMA opsi_meta TO opsi_app, opsi_ingest_writer, opsi_readonly;

GRANT USAGE ON SCHEMA opsi_chat, opsi_knowledge, opsi_audit TO opsi_app;
GRANT USAGE ON SCHEMA opsi_ingest TO opsi_app, opsi_ingest_writer, opsi_readonly;
GRANT USAGE ON SCHEMA opsi_knowledge TO opsi_readonly;

-- Session settings consumed by RLS policies (set per request with SET LOCAL / set_config(..., true)).
COMMENT ON SCHEMA opsi_chat IS 'Chat persistence. RLS keyed on current_setting(''opsi.tenant_id'') and ''opsi.user_id''.';
COMMENT ON SCHEMA opsi_knowledge IS 'Operational ontology + catalog cross-references. RLS keyed on opsi.tenant_id.';
COMMENT ON SCHEMA opsi_ingest IS 'Collector state + CURATED subset only. Never raw log payloads.';
COMMENT ON SCHEMA opsi_audit IS 'Append-only audit trail.';
