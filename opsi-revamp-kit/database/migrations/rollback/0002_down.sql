-- Rollback 0002: DROPS collector state and curated tables (bronze data in S3 is unaffected;
-- re-run the index stage to rebuild curated tables from manifests).
DO $$ BEGIN
  IF current_setting('opsi.allow_destructive', true) IS DISTINCT FROM 'yes' THEN
    RAISE EXCEPTION 'Refusing destructive rollback. Take a snapshot first, then run: SET opsi.allow_destructive = ''yes'';';
  END IF;
END $$;

DROP VIEW IF EXISTS opsi_ingest.error_signatures_hourly;
DROP TABLE IF EXISTS opsi_ingest.evidence_samples, opsi_ingest.error_signature_windows, opsi_ingest.problems,
  opsi_ingest.window_index_state, opsi_ingest.operator_actions, opsi_ingest.runs, opsi_ingest.outbox,
  opsi_ingest.window_ledger, opsi_ingest.watermarks;
