-- Rollback 0003: DROPS all chat history, attachments metadata and audit events.
-- Export first: scripts/backup_restore_drill.sh export opsi_chat
DO $$ BEGIN
  IF current_setting('opsi.allow_destructive', true) IS DISTINCT FROM 'yes' THEN
    RAISE EXCEPTION 'Refusing destructive rollback. Take a snapshot first, then run: SET opsi.allow_destructive = ''yes'';';
  END IF;
END $$;

DROP TABLE IF EXISTS opsi_chat.feedback, opsi_chat.action_approvals, opsi_chat.evidence_refs, opsi_chat.tool_runs,
  opsi_chat.agent_runs, opsi_chat.attachments, opsi_chat.thread_tags, opsi_chat.tags, opsi_chat.messages,
  opsi_chat.threads, opsi_chat.folders, opsi_audit.events;
