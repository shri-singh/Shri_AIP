-- Rollback 0007: removes the OpenMetadata reader role grants (no data loss).
DO $$ BEGIN
  IF current_setting('opsi.allow_destructive', true) IS DISTINCT FROM 'yes' THEN
    RAISE EXCEPTION 'Refusing destructive rollback. Take a snapshot first, then run: SET opsi.allow_destructive = ''yes'';';
  END IF;
END $$;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'om_catalog_reader') THEN
    EXECUTE 'REASSIGN OWNED BY om_catalog_reader TO opsi_owner';
    EXECUTE 'DROP OWNED BY om_catalog_reader';
    EXECUTE 'DROP ROLE om_catalog_reader';
  END IF;
END $$;
