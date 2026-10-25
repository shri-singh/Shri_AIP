-- 0007 - OPTIONAL: least-privilege role for OpenMetadata's PostgreSQL connector
-- to read *metadata* (schemas/tables/columns) of the Opsi application database.
--
-- Strategy: grant USAGE on the schemas to catalog + REFERENCES on their tables.
-- REFERENCES makes tables/columns visible in information_schema without granting
-- SELECT on the data. pg_catalog is readable by everyone anyway.
-- Disable profiler, sample data, data quality and query-usage/lineage workflows for
-- this service in OpenMetadata - they need SELECT / pg_stat_statements.
-- If the connector still cannot see objects, escalate with the DBA case by case;
-- do not jump to pg_read_all_data.
--
-- Edit the schema list below (default: the Opsi app schemas + 'public').
-- DBA then: CREATE ROLE om_ingest_svc LOGIN PASSWORD '...' IN ROLE om_catalog_reader CONNECTION LIMIT 2;
--           ALTER ROLE om_ingest_svc SET statement_timeout = '60s';

DO $$
DECLARE s text;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'om_catalog_reader') THEN
    CREATE ROLE om_catalog_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO om_catalog_reader', current_database());
  FOREACH s IN ARRAY ARRAY['public', 'opsi_chat', 'opsi_knowledge', 'opsi_ingest'] LOOP
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = s) THEN
      EXECUTE format('GRANT USAGE ON SCHEMA %I TO om_catalog_reader', s);
      EXECUTE format('GRANT REFERENCES ON ALL TABLES IN SCHEMA %I TO om_catalog_reader', s);
    END IF;
  END LOOP;
END $$;

-- Future tables created by opsi_owner become visible too.
ALTER DEFAULT PRIVILEGES FOR ROLE opsi_owner IN SCHEMA opsi_chat, opsi_knowledge, opsi_ingest
  GRANT REFERENCES ON TABLES TO om_catalog_reader;
