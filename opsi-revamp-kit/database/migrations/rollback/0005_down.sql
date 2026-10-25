-- Rollback 0005: disables RLS (no data loss, but REMOVES a security control).
DO $$ BEGIN
  IF current_setting('opsi.allow_destructive', true) IS DISTINCT FROM 'yes' THEN
    RAISE EXCEPTION 'Refusing destructive rollback. Take a snapshot first, then run: SET opsi.allow_destructive = ''yes'';';
  END IF;
END $$;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['opsi_chat.folders','opsi_chat.threads','opsi_chat.messages','opsi_chat.tags',
    'opsi_chat.thread_tags','opsi_chat.attachments','opsi_chat.agent_runs','opsi_chat.tool_runs',
    'opsi_chat.evidence_refs','opsi_chat.action_approvals','opsi_chat.feedback','opsi_audit.events',
    'opsi_knowledge.entities','opsi_knowledge.edges','opsi_knowledge.catalog_xrefs','opsi_ingest.problems',
    'opsi_ingest.error_signature_windows','opsi_ingest.evidence_samples','opsi_ingest.window_index_state'] LOOP
    EXECUTE format('ALTER TABLE %s NO FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %s DISABLE ROW LEVEL SECURITY', t);
  END LOOP;
END $$;
