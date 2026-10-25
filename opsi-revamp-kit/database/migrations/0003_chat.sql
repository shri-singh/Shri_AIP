-- 0003 - persistent chat: folders, threads, messages, tags, attachments, tool runs,
-- evidence/citations, action approvals, feedback, agent runs.
-- Identity columns (tenant_id, owner_id, user_id) are ALWAYS set by the API from the
-- authenticated principal, never from client input. RLS in 0005 enforces it again.

SET ROLE opsi_owner;

CREATE TABLE IF NOT EXISTS opsi_chat.folders (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  text NOT NULL,
    owner_id   text NOT NULL,
    parent_id  uuid REFERENCES opsi_chat.folders (id) ON DELETE CASCADE,
    name       text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
-- one name per parent per user (portable alternative to PG15 NULLS NOT DISTINCT)
CREATE UNIQUE INDEX IF NOT EXISTS ux_folders_name ON opsi_chat.folders
    (tenant_id, owner_id, coalesce(parent_id, '00000000-0000-0000-0000-000000000000'::uuid), lower(name));

CREATE TABLE IF NOT EXISTS opsi_chat.threads (
    id                uuid PRIMARY KEY,               -- also the AG-UI threadId
    tenant_id         text NOT NULL,
    owner_id          text NOT NULL,
    folder_id         uuid REFERENCES opsi_chat.folders (id) ON DELETE SET NULL,
    agent_id          text NOT NULL DEFAULT 'opsi-investigator',
    title             text NOT NULL DEFAULT 'New investigation' CHECK (length(title) <= 300),
    visibility        text NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'tenant')),
    linked_incident_id text,
    linked_service_id text,
    ui_context        jsonb NOT NULL DEFAULT '{}'::jsonb,  -- last allowlisted UI context (page, time range...)
    agent_state       jsonb NOT NULL DEFAULT '{}'::jsonb,  -- last AG-UI state snapshot (server-authored)
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    last_message_at   timestamptz,
    archived_at       timestamptz,
    deleted_at        timestamptz,
    search_tsv        tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(title, ''))) STORED
);
CREATE INDEX IF NOT EXISTS ix_threads_owner_recent ON opsi_chat.threads (tenant_id, owner_id, last_message_at DESC NULLS LAST)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_threads_folder ON opsi_chat.threads (tenant_id, folder_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_threads_incident ON opsi_chat.threads (tenant_id, linked_incident_id)
    WHERE linked_incident_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_threads_tsv ON opsi_chat.threads USING gin (search_tsv);

CREATE TABLE IF NOT EXISTS opsi_chat.messages (
    seq          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,   -- total order within the DB
    tenant_id    text NOT NULL,
    thread_id    uuid NOT NULL REFERENCES opsi_chat.threads (id) ON DELETE CASCADE,
    message_id   text NOT NULL CHECK (length(message_id) <= 128),   -- AG-UI message id
    role         text NOT NULL CHECK (role IN ('user', 'assistant', 'tool', 'system', 'developer', 'activity', 'reasoning')),
    content_text text,                 -- plain text used for display/search (redacted for tool output)
    content_json jsonb NOT NULL,       -- full AG-UI message (tool_calls, content parts, tool_call_id)
    run_id       text,
    author_id    text NOT NULL,        -- user id, or 'agent:<agentId>'
    created_at   timestamptz NOT NULL DEFAULT now(),
    search_tsv   tsvector GENERATED ALWAYS AS (to_tsvector('simple', coalesce(content_text, ''))) STORED,
    UNIQUE (thread_id, message_id)
);
CREATE INDEX IF NOT EXISTS ix_messages_thread ON opsi_chat.messages (thread_id, seq);
CREATE INDEX IF NOT EXISTS ix_messages_tsv ON opsi_chat.messages USING gin (search_tsv);

CREATE TABLE IF NOT EXISTS opsi_chat.tags (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  text NOT NULL,
    owner_id   text NOT NULL,
    name       text NOT NULL CHECK (length(name) BETWEEN 1 AND 64),
    color      text CHECK (color ~ '^#[0-9a-fA-F]{6}$'),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tags_name ON opsi_chat.tags (tenant_id, owner_id, lower(name));

CREATE TABLE IF NOT EXISTS opsi_chat.thread_tags (
    tenant_id text NOT NULL,
    thread_id uuid NOT NULL REFERENCES opsi_chat.threads (id) ON DELETE CASCADE,
    tag_id    uuid NOT NULL REFERENCES opsi_chat.tags (id) ON DELETE CASCADE,
    PRIMARY KEY (thread_id, tag_id)
);
CREATE INDEX IF NOT EXISTS ix_thread_tags_tag ON opsi_chat.thread_tags (tag_id);

CREATE TABLE IF NOT EXISTS opsi_chat.attachments (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    text NOT NULL,
    owner_id     text NOT NULL,
    thread_id    uuid NOT NULL REFERENCES opsi_chat.threads (id) ON DELETE CASCADE,
    message_id   text,
    s3_key       text NOT NULL UNIQUE,
    filename     text NOT NULL CHECK (length(filename) <= 255),
    mime_type    text NOT NULL,
    size_bytes   bigint CHECK (size_bytes >= 0),
    sha256       text CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    status       text NOT NULL DEFAULT 'pending_upload'
                 CHECK (status IN ('pending_upload', 'uploaded', 'clean', 'infected', 'scan_error', 'rejected', 'deleted')),
    scan_detail  text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    finalized_at timestamptz,
    deleted_at   timestamptz
);
CREATE INDEX IF NOT EXISTS ix_attachments_thread ON opsi_chat.attachments (tenant_id, thread_id);

CREATE TABLE IF NOT EXISTS opsi_chat.agent_runs (
    run_id        text PRIMARY KEY,
    tenant_id     text NOT NULL,
    thread_id     uuid NOT NULL REFERENCES opsi_chat.threads (id) ON DELETE CASCADE,
    user_id       text NOT NULL,
    status        text NOT NULL CHECK (status IN ('running', 'finished', 'error', 'cancelled', 'interrupted')),
    model_ref     text,                -- Portkey model/route reference (no keys)
    input_tokens  integer,
    output_tokens integer,
    tool_calls    integer NOT NULL DEFAULT 0,
    cost_units    numeric(12, 3) NOT NULL DEFAULT 0,
    trace_id      text,
    error_code    text,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz
);
CREATE INDEX IF NOT EXISTS ix_agent_runs_thread ON opsi_chat.agent_runs (tenant_id, thread_id, started_at DESC);

CREATE TABLE IF NOT EXISTS opsi_chat.tool_runs (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      text NOT NULL,
    thread_id      uuid NOT NULL REFERENCES opsi_chat.threads (id) ON DELETE CASCADE,
    run_id         text NOT NULL,
    tool_call_id   text NOT NULL,
    tool_name      text NOT NULL,
    executor       text NOT NULL CHECK (executor IN ('server', 'frontend', 'human')),
    args_json      jsonb NOT NULL,      -- validated + redacted arguments
    status         text NOT NULL CHECK (status IN ('ok', 'error', 'denied', 'budget_exceeded', 'cancelled', 'pending')),
    result_summary jsonb,               -- counts/ids, never raw payloads
    citations      integer NOT NULL DEFAULT 0,
    cost_units     numeric(12, 3) NOT NULL DEFAULT 0,
    latency_ms     integer,
    error_code     text,
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz,
    UNIQUE (thread_id, tool_call_id)
);

CREATE TABLE IF NOT EXISTS opsi_chat.evidence_refs (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    text NOT NULL,
    thread_id    uuid NOT NULL REFERENCES opsi_chat.threads (id) ON DELETE CASCADE,
    message_id   text,                  -- assistant message that cites it
    tool_run_id  uuid REFERENCES opsi_chat.tool_runs (id) ON DELETE SET NULL,
    citation_key text NOT NULL,         -- e.g. c3 (unique per thread)
    source_type  text NOT NULL CHECK (source_type IN ('elastic_log', 'grail_log', 'dynatrace_problem', 'error_signature',
                                                      'om_entity', 'ontology', 'runbook', 'sql_aggregate', 'incident')),
    source_ref   text NOT NULL,         -- elastic://idx/_doc/id, dynatrace-problem://..., om://table/<fqn> ...
    title        text,
    event_time   timestamptz,
    snippet      text,                  -- redacted excerpt shown in the UI
    url          text,                  -- deep link (relative or approved internal host)
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (thread_id, citation_key)
);
CREATE INDEX IF NOT EXISTS ix_evidence_message ON opsi_chat.evidence_refs (thread_id, message_id);

CREATE TABLE IF NOT EXISTS opsi_chat.action_approvals (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        text NOT NULL,
    thread_id        uuid NOT NULL REFERENCES opsi_chat.threads (id) ON DELETE CASCADE,
    run_id           text NOT NULL,
    tool_call_id     text NOT NULL,
    action_kind      text NOT NULL,
    action_args      jsonb NOT NULL,
    requested_for    text NOT NULL,     -- user who must decide
    status           text NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'approved', 'rejected', 'expired', 'executed', 'failed')),
    decided_by       text,
    decided_at       timestamptz,
    decision_reason  text,
    executed_at      timestamptz,
    execution_result jsonb,
    expires_at       timestamptz NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (thread_id, tool_call_id)
);

CREATE TABLE IF NOT EXISTS opsi_chat.feedback (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   text NOT NULL,
    thread_id   uuid NOT NULL REFERENCES opsi_chat.threads (id) ON DELETE CASCADE,
    message_id  text NOT NULL,
    user_id     text NOT NULL,
    rating      smallint NOT NULL CHECK (rating IN (-1, 1)),
    reason_code text CHECK (reason_code IN ('wrong', 'incomplete', 'bad_citation', 'unsafe', 'slow', 'helpful', 'other')),
    comment     text CHECK (length(comment) <= 2000),
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (thread_id, message_id, user_id)
);

-- ---------------------------------------------------------------- audit (append-only)
CREATE TABLE IF NOT EXISTS opsi_audit.events (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    at         timestamptz NOT NULL DEFAULT now(),
    tenant_id  text NOT NULL,
    actor_id   text NOT NULL,
    action     text NOT NULL,            -- e.g. attachment.download, approval.decide, thread.share
    target     text,
    outcome    text NOT NULL CHECK (outcome IN ('allowed', 'denied', 'error')),
    request_id text,
    detail     jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS ix_audit_tenant_time ON opsi_audit.events (tenant_id, at DESC);

-- ---------------------------------------------------------------- grants
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA opsi_chat TO opsi_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA opsi_chat TO opsi_app;
GRANT INSERT, SELECT ON opsi_audit.events TO opsi_app;   -- no UPDATE/DELETE: append-only
GRANT USAGE ON ALL SEQUENCES IN SCHEMA opsi_audit TO opsi_app;

RESET ROLE;
