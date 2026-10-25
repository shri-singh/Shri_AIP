-- 0005 - Row-level security. Defence in depth: the API already scopes every query,
-- RLS guarantees a missed WHERE clause cannot leak another tenant's or user's data.
--
-- Per request, inside the transaction, the API runs:
--   SELECT set_config('opsi.tenant_id', $tenant, true), set_config('opsi.user_id', $user, true);
-- ('true' = transaction-local, safe with connection pools). Unset => NULL => no rows (fail closed).
--
-- Policy model:
--   RESTRICTIVE tenant_isolation  : tenant_id must equal the session tenant (ANDed with everything)
--   PERMISSIVE  owner_or_shared   : chat rows visible to their owner, or tenant-visible threads
-- FORCE ROW LEVEL SECURITY makes the table owner subject to policies as well.

SET ROLE opsi_owner;

CREATE OR REPLACE FUNCTION opsi_meta.current_tenant() RETURNS text LANGUAGE sql STABLE
SET search_path = pg_catalog AS $$ SELECT nullif(current_setting('opsi.tenant_id', true), '') $$;
CREATE OR REPLACE FUNCTION opsi_meta.current_user_id() RETURNS text LANGUAGE sql STABLE
SET search_path = pg_catalog AS $$ SELECT nullif(current_setting('opsi.user_id', true), '') $$;

DO $$
DECLARE
  t text;
  tenant_tables text[] := ARRAY[
    'opsi_chat.folders', 'opsi_chat.threads', 'opsi_chat.messages', 'opsi_chat.tags', 'opsi_chat.thread_tags',
    'opsi_chat.attachments', 'opsi_chat.agent_runs', 'opsi_chat.tool_runs', 'opsi_chat.evidence_refs',
    'opsi_chat.action_approvals', 'opsi_chat.feedback', 'opsi_audit.events',
    'opsi_knowledge.entities', 'opsi_knowledge.edges', 'opsi_knowledge.catalog_xrefs',
    'opsi_ingest.problems', 'opsi_ingest.error_signature_windows', 'opsi_ingest.evidence_samples',
    'opsi_ingest.window_index_state'];
BEGIN
  FOREACH t IN ARRAY tenant_tables LOOP
    EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %s', t);
    EXECUTE format('CREATE POLICY tenant_isolation ON %s AS RESTRICTIVE FOR ALL '
                   'USING (tenant_id = opsi_meta.current_tenant()) WITH CHECK (tenant_id = opsi_meta.current_tenant())', t);
  END LOOP;
END $$;

-- ---------------------------------------------------------------- per-user visibility (chat)
DROP POLICY IF EXISTS owner_only ON opsi_chat.folders;
CREATE POLICY owner_only ON opsi_chat.folders FOR ALL
  USING (owner_id = opsi_meta.current_user_id()) WITH CHECK (owner_id = opsi_meta.current_user_id());

DROP POLICY IF EXISTS owner_only ON opsi_chat.tags;
CREATE POLICY owner_only ON opsi_chat.tags FOR ALL
  USING (owner_id = opsi_meta.current_user_id()) WITH CHECK (owner_id = opsi_meta.current_user_id());

DROP POLICY IF EXISTS owner_or_shared ON opsi_chat.threads;
CREATE POLICY owner_or_shared ON opsi_chat.threads FOR SELECT
  USING (owner_id = opsi_meta.current_user_id() OR visibility = 'tenant');
DROP POLICY IF EXISTS owner_writes ON opsi_chat.threads;
CREATE POLICY owner_writes ON opsi_chat.threads FOR INSERT WITH CHECK (owner_id = opsi_meta.current_user_id());
DROP POLICY IF EXISTS owner_updates ON opsi_chat.threads;
CREATE POLICY owner_updates ON opsi_chat.threads FOR UPDATE
  USING (owner_id = opsi_meta.current_user_id()) WITH CHECK (owner_id = opsi_meta.current_user_id());
DROP POLICY IF EXISTS owner_deletes ON opsi_chat.threads;
CREATE POLICY owner_deletes ON opsi_chat.threads FOR DELETE USING (owner_id = opsi_meta.current_user_id());

-- Child tables inherit visibility from their thread (threads' own RLS applies inside EXISTS).
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['opsi_chat.messages', 'opsi_chat.thread_tags', 'opsi_chat.attachments',
                           'opsi_chat.agent_runs', 'opsi_chat.tool_runs', 'opsi_chat.evidence_refs',
                           'opsi_chat.action_approvals', 'opsi_chat.feedback'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS via_thread_read ON %s', t);
    EXECUTE format('CREATE POLICY via_thread_read ON %s FOR SELECT USING (EXISTS ('
                   'SELECT 1 FROM opsi_chat.threads th WHERE th.id = thread_id))', t);
    EXECUTE format('DROP POLICY IF EXISTS via_thread_write ON %s', t);
    EXECUTE format('CREATE POLICY via_thread_write ON %s FOR INSERT WITH CHECK (EXISTS ('
                   'SELECT 1 FROM opsi_chat.threads th WHERE th.id = thread_id AND th.owner_id = opsi_meta.current_user_id()))', t);
    EXECUTE format('DROP POLICY IF EXISTS via_thread_update ON %s', t);
    EXECUTE format('CREATE POLICY via_thread_update ON %s FOR UPDATE USING (EXISTS ('
                   'SELECT 1 FROM opsi_chat.threads th WHERE th.id = thread_id AND th.owner_id = opsi_meta.current_user_id()))', t);
    EXECUTE format('DROP POLICY IF EXISTS via_thread_delete ON %s', t);
    EXECUTE format('CREATE POLICY via_thread_delete ON %s FOR DELETE USING (EXISTS ('
                   'SELECT 1 FROM opsi_chat.threads th WHERE th.id = thread_id AND th.owner_id = opsi_meta.current_user_id()))', t);
  END LOOP;
END $$;

-- Feedback on a shared thread may be written by any tenant member who can see it, for themselves only.
DROP POLICY IF EXISTS via_thread_write ON opsi_chat.feedback;
CREATE POLICY via_thread_write ON opsi_chat.feedback FOR INSERT WITH CHECK (
  user_id = opsi_meta.current_user_id() AND EXISTS (SELECT 1 FROM opsi_chat.threads th WHERE th.id = thread_id));

-- ---------------------------------------------------------------- tenant-wide tables
-- (tenant_isolation is RESTRICTIVE; a PERMISSIVE policy must also exist or nothing is visible)
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['opsi_audit.events', 'opsi_knowledge.entities', 'opsi_knowledge.edges',
                           'opsi_knowledge.catalog_xrefs', 'opsi_ingest.problems',
                           'opsi_ingest.error_signature_windows', 'opsi_ingest.evidence_samples',
                           'opsi_ingest.window_index_state'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS tenant_members ON %s', t);
    EXECUTE format('CREATE POLICY tenant_members ON %s FOR ALL USING (true) WITH CHECK (true)', t);
  END LOOP;
END $$;

GRANT EXECUTE ON FUNCTION opsi_meta.current_tenant(), opsi_meta.current_user_id() TO opsi_app, opsi_ingest_writer, opsi_readonly;

RESET ROLE;
