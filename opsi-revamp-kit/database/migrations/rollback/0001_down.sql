-- Rollback 0001: drops the (now empty) schemas and group roles. Fails if objects remain - by design.
DO $$ BEGIN
  IF current_setting('opsi.allow_destructive', true) IS DISTINCT FROM 'yes' THEN
    RAISE EXCEPTION 'Refusing destructive rollback. Take a snapshot first, then run: SET opsi.allow_destructive = ''yes'';';
  END IF;
END $$;

DROP FUNCTION IF EXISTS opsi_meta.current_tenant(), opsi_meta.current_user_id();
DROP SCHEMA IF EXISTS opsi_ingest, opsi_chat, opsi_knowledge, opsi_audit RESTRICT;
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['opsi_readonly', 'opsi_ingest_writer', 'opsi_app', 'opsi_owner'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('DROP OWNED BY %I', r);
      EXECUTE format('DROP ROLE %I', r);
    END IF;
  END LOOP;
END $$;
