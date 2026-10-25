-- Rollback 0006: DROPS vector documents (re-embedding required to restore).
DO $$ BEGIN
  IF current_setting('opsi.allow_destructive', true) IS DISTINCT FROM 'yes' THEN
    RAISE EXCEPTION 'Refusing destructive rollback. Take a snapshot first, then run: SET opsi.allow_destructive = ''yes'';';
  END IF;
END $$;

DROP TABLE IF EXISTS opsi_knowledge.documents;
-- The extension is left installed on purpose (other users may depend on it).
