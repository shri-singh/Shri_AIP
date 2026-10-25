"""PostgreSQL implementation of ChatRepository (schema: database/migrations/0003_chat.sql).

RLS already restricts rows to the caller's tenant/visibility; the explicit
``owner_id = %s`` predicates below make write paths fail as "not found" instead
of raising RLS errors, and keep query plans index-friendly.
"""
from __future__ import annotations

import uuid
from typing import Any

from psycopg.types.json import Jsonb

from .._shared.db import Database
from ..identity.principal import Principal
from .models import Attachment, Evidence, FeedbackIn, Folder, SearchHit, StoredMessage, Tag, Thread, ThreadQuery

_THREAD_COLS = ("t.id, t.owner_id, t.title, t.agent_id, t.folder_id, t.visibility, t.linked_incident_id, "
                "t.linked_service_id, t.created_at, t.updated_at, t.last_message_at, t.archived_at, "
                "coalesce((SELECT array_agg(g.name ORDER BY g.name) FROM opsi_chat.thread_tags tt "
                "JOIN opsi_chat.tags g ON g.id = tt.tag_id WHERE tt.thread_id = t.id), '{}') AS tags")


def _thread(row: dict[str, Any]) -> Thread:
    return Thread(**{**row, "tags": list(row.get("tags") or [])})


class PgChatRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- folders -------------------------------------------------------------------------
    async def create_folder(self, p: Principal, name, parent_id):
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute(
                "INSERT INTO opsi_chat.folders (tenant_id, owner_id, name, parent_id) VALUES (%s,%s,%s,%s) "
                "RETURNING id, name, parent_id, created_at", (p.tenant_id, p.user_id, name, parent_id))
            return Folder(**await cur.fetchone())

    async def list_folders(self, p):
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute("SELECT id, name, parent_id, created_at FROM opsi_chat.folders "
                                     "WHERE owner_id = %s ORDER BY lower(name)", (p.user_id,))
            return [Folder(**r) for r in await cur.fetchall()]

    async def delete_folder(self, p, folder_id):
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute("DELETE FROM opsi_chat.folders WHERE id = %s AND owner_id = %s",
                                     (folder_id, p.user_id))
            return cur.rowcount == 1

    # -- threads -------------------------------------------------------------------------
    async def create_thread(self, p, thread_id, *, title, folder_id, linked_incident_id, linked_service_id, agent_id):
        async with self.db.tenant_tx(p) as conn:
            await conn.execute(
                "INSERT INTO opsi_chat.threads (id, tenant_id, owner_id, title, folder_id, linked_incident_id, "
                "linked_service_id, agent_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (thread_id, p.tenant_id, p.user_id, title, folder_id, linked_incident_id, linked_service_id, agent_id))
            cur = await conn.execute(f"SELECT {_THREAD_COLS} FROM opsi_chat.threads t WHERE t.id = %s", (thread_id,))
            return _thread(await cur.fetchone())

    async def get_thread(self, p, thread_id):
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute(
                f"SELECT {_THREAD_COLS} FROM opsi_chat.threads t WHERE t.id = %s AND t.deleted_at IS NULL", (thread_id,))
            row = await cur.fetchone()
            return _thread(row) if row else None

    async def update_thread(self, p, thread_id, changes):
        allowed = {"title", "folder_id", "visibility", "archived_at"}
        sets = {k: v for k, v in changes.items() if k in allowed}
        if not sets:
            return await self.get_thread(p, thread_id)
        assignments = ", ".join(f"{k} = %s" for k in sets)
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute(
                f"UPDATE opsi_chat.threads SET {assignments}, updated_at = now() "
                "WHERE id = %s AND owner_id = %s AND deleted_at IS NULL",
                (*sets.values(), thread_id, p.user_id))
            if cur.rowcount != 1:
                return None
            cur = await conn.execute(f"SELECT {_THREAD_COLS} FROM opsi_chat.threads t WHERE t.id = %s", (thread_id,))
            return _thread(await cur.fetchone())

    async def list_threads(self, p, query: ThreadQuery):
        where = ["t.deleted_at IS NULL"]
        params: list[Any] = []
        if not query.include_shared:
            where.append("t.owner_id = %s")
            params.append(p.user_id)
        if not query.include_archived:
            where.append("t.archived_at IS NULL")
        if query.folder_id:
            where.append("t.folder_id = %s")
            params.append(query.folder_id)
        if query.incident_id:
            where.append("t.linked_incident_id = %s")
            params.append(query.incident_id)
        if query.tag:
            where.append("EXISTS (SELECT 1 FROM opsi_chat.thread_tags tt JOIN opsi_chat.tags g ON g.id = tt.tag_id "
                         "WHERE tt.thread_id = t.id AND lower(g.name) = lower(%s))")
            params.append(query.tag)
        if query.q:
            where.append("(t.search_tsv @@ websearch_to_tsquery('simple', %s) OR EXISTS (SELECT 1 FROM "
                         "opsi_chat.messages m WHERE m.thread_id = t.id AND m.search_tsv @@ websearch_to_tsquery('simple', %s)))")
            params += [query.q, query.q]
        if query.before:
            where.append("coalesce(t.last_message_at, t.created_at) < %s")
            params.append(query.before)
        params.append(query.limit)
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute(
                f"SELECT {_THREAD_COLS} FROM opsi_chat.threads t WHERE {' AND '.join(where)} "
                "ORDER BY coalesce(t.last_message_at, t.created_at) DESC LIMIT %s", params)
            return [_thread(r) for r in await cur.fetchall()]

    async def save_agent_state(self, p, thread_id, state, ui_context):
        async with self.db.tenant_tx(p) as conn:
            await conn.execute("UPDATE opsi_chat.threads SET agent_state = %s, ui_context = %s, updated_at = now() "
                               "WHERE id = %s AND owner_id = %s", (Jsonb(state), Jsonb(ui_context), thread_id, p.user_id))

    async def get_agent_state(self, p, thread_id):
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute("SELECT agent_state FROM opsi_chat.threads WHERE id = %s", (thread_id,))
            row = await cur.fetchone()
            return dict(row["agent_state"]) if row else {}

    # -- messages ------------------------------------------------------------------------
    async def append_messages(self, p, thread_id, messages):
        if not messages:
            return 0
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute("SELECT 1 FROM opsi_chat.threads WHERE id = %s AND owner_id = %s FOR UPDATE",
                                     (thread_id, p.user_id))
            if not await cur.fetchone():
                raise LookupError("thread not found")
            added = 0
            for m in messages:
                cur = await conn.execute(
                    "INSERT INTO opsi_chat.messages (tenant_id, thread_id, message_id, role, content_text, "
                    "content_json, run_id, author_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (thread_id, message_id) DO NOTHING",
                    (p.tenant_id, thread_id, m.message_id, m.role, m.content_text, Jsonb(m.content_json), m.run_id,
                     m.author_id))
                added += cur.rowcount
            if added:
                await conn.execute("UPDATE opsi_chat.threads SET last_message_at = now(), updated_at = now() "
                                   "WHERE id = %s", (thread_id,))
            return added

    async def list_messages(self, p, thread_id, limit=500):
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute(
                "SELECT message_id, role, content_text, content_json, run_id, author_id, created_at FROM ("
                " SELECT * FROM opsi_chat.messages WHERE thread_id = %s ORDER BY seq DESC LIMIT %s) x ORDER BY seq",
                (thread_id, limit))
            return [StoredMessage(**r) for r in await cur.fetchall()]

    async def search(self, p, q, limit=20):
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute(
                "SELECT m.thread_id, t.title AS thread_title, m.message_id, "
                "ts_headline('simple', coalesce(m.content_text, ''), websearch_to_tsquery('simple', %s), "
                "'MaxWords=30, MinWords=10') AS snippet, m.created_at AS at "
                "FROM opsi_chat.messages m JOIN opsi_chat.threads t ON t.id = m.thread_id "
                "WHERE t.owner_id = %s AND t.deleted_at IS NULL AND m.search_tsv @@ websearch_to_tsquery('simple', %s) "
                "ORDER BY m.created_at DESC LIMIT %s", (q, p.user_id, q, limit))
            return [SearchHit(**r) for r in await cur.fetchall()]

    # -- tags ------------------------------------------------------------------------------
    async def create_tag(self, p, name, color):
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute(
                "INSERT INTO opsi_chat.tags AS g (tenant_id, owner_id, name, color) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (tenant_id, owner_id, lower(name)) DO UPDATE SET color = coalesce(excluded.color, g.color) "
                "RETURNING id, name, color", (p.tenant_id, p.user_id, name, color))
            return Tag(**await cur.fetchone())

    async def list_tags(self, p):
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute("SELECT id, name, color FROM opsi_chat.tags WHERE owner_id = %s "
                                     "ORDER BY lower(name)", (p.user_id,))
            return [Tag(**r) for r in await cur.fetchall()]

    async def set_thread_tags(self, p, thread_id, tag_ids):
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute("SELECT 1 FROM opsi_chat.threads WHERE id = %s AND owner_id = %s",
                                     (thread_id, p.user_id))
            if not await cur.fetchone():
                return False
            if tag_ids:
                cur = await conn.execute("SELECT count(*) AS n FROM opsi_chat.tags WHERE id = ANY(%s) AND owner_id = %s",
                                         (list(tag_ids), p.user_id))
                if (await cur.fetchone())["n"] != len(set(tag_ids)):
                    raise LookupError("tag not found")
            await conn.execute("DELETE FROM opsi_chat.thread_tags WHERE thread_id = %s", (thread_id,))
            for tag_id in set(tag_ids):
                await conn.execute("INSERT INTO opsi_chat.thread_tags (tenant_id, thread_id, tag_id) VALUES (%s,%s,%s)",
                                   (p.tenant_id, thread_id, tag_id))
            return True

    # -- runs / tools / evidence -----------------------------------------------------------
    async def start_run(self, p, thread_id, run_id, model_ref, trace_id):
        async with self.db.tenant_tx(p) as conn:
            await conn.execute(
                "INSERT INTO opsi_chat.agent_runs (run_id, tenant_id, thread_id, user_id, status, model_ref, trace_id) "
                "VALUES (%s,%s,%s,%s,'running',%s,%s)", (run_id, p.tenant_id, thread_id, p.user_id, model_ref, trace_id))

    async def finish_run(self, p, run_id, status, *, input_tokens=None, output_tokens=None, tool_calls=0,
                         cost_units=0, error_code=None):
        async with self.db.tenant_tx(p) as conn:
            await conn.execute(
                "UPDATE opsi_chat.agent_runs SET status=%s, input_tokens=%s, output_tokens=%s, tool_calls=%s, "
                "cost_units=%s, error_code=%s, finished_at=now() WHERE run_id=%s",
                (status, input_tokens, output_tokens, tool_calls, cost_units, error_code, run_id))

    async def record_tool_run(self, p, thread_id, run_id, tool_call_id, tool_name, executor, args, status,
                              result_summary, citations, cost_units, latency_ms, error_code):
        async with self.db.tenant_tx(p) as conn:
            await conn.execute(
                "INSERT INTO opsi_chat.tool_runs (tenant_id, thread_id, run_id, tool_call_id, tool_name, executor, "
                "args_json, status, result_summary, citations, cost_units, latency_ms, error_code, finished_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now()) "
                "ON CONFLICT (thread_id, tool_call_id) DO UPDATE SET status = excluded.status, "
                "result_summary = excluded.result_summary, finished_at = now()",
                (p.tenant_id, thread_id, run_id, tool_call_id, tool_name, executor, Jsonb(args), status,
                 Jsonb(result_summary) if result_summary is not None else None, citations, cost_units, latency_ms,
                 error_code))

    async def add_evidence(self, p, thread_id, items):
        async with self.db.tenant_tx(p) as conn:
            for e in items:
                await conn.execute(
                    "INSERT INTO opsi_chat.evidence_refs (tenant_id, thread_id, message_id, citation_key, source_type, "
                    "source_ref, title, event_time, snippet, url) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (thread_id, citation_key) DO NOTHING",
                    (p.tenant_id, thread_id, e.message_id, e.citation_key, e.source_type, e.source_ref, e.title,
                     e.event_time, e.snippet, e.url))

    async def list_evidence(self, p, thread_id):
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute(
                "SELECT citation_key, source_type, source_ref, title, event_time, snippet, url, message_id "
                "FROM opsi_chat.evidence_refs WHERE thread_id = %s ORDER BY created_at, citation_key", (thread_id,))
            return [Evidence(**r) for r in await cur.fetchall()]

    # -- attachments -----------------------------------------------------------------------
    async def create_attachment(self, p, att: Attachment):
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute("SELECT 1 FROM opsi_chat.threads WHERE id = %s AND owner_id = %s",
                                     (att.thread_id, p.user_id))
            if not await cur.fetchone():
                raise LookupError("thread not found")
            await conn.execute(
                "INSERT INTO opsi_chat.attachments (id, tenant_id, owner_id, thread_id, message_id, s3_key, filename, "
                "mime_type, size_bytes, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (att.id, p.tenant_id, p.user_id, att.thread_id, att.message_id, att.s3_key, att.filename,
                 att.mime_type, att.size_bytes, att.status))
            return att

    async def get_attachment(self, p, attachment_id):
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute(
                "SELECT id, thread_id, owner_id, s3_key, filename, mime_type, size_bytes, status, message_id, created_at "
                "FROM opsi_chat.attachments WHERE id = %s AND deleted_at IS NULL", (attachment_id,))
            row = await cur.fetchone()
            return Attachment(**row) if row else None

    async def update_attachment(self, p, attachment_id, **changes):
        allowed = {k: v for k, v in changes.items() if k in {"status", "size_bytes", "sha256", "scan_detail",
                                                              "finalized_at", "message_id", "deleted_at"}}
        if not allowed:
            return
        assignments = ", ".join(f"{k} = %s" for k in allowed)
        async with self.db.tenant_tx(p) as conn:
            await conn.execute(f"UPDATE opsi_chat.attachments SET {assignments} WHERE id = %s AND owner_id = %s",
                               (*allowed.values(), attachment_id, p.user_id))

    # -- feedback --------------------------------------------------------------------------
    async def upsert_feedback(self, p, thread_id, fb: FeedbackIn):
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute("SELECT 1 FROM opsi_chat.threads WHERE id = %s", (thread_id,))
            if not await cur.fetchone():
                return False
            await conn.execute(
                "INSERT INTO opsi_chat.feedback (tenant_id, thread_id, message_id, user_id, rating, reason_code, comment) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (thread_id, message_id, user_id) DO UPDATE SET "
                "rating = excluded.rating, reason_code = excluded.reason_code, comment = excluded.comment, created_at = now()",
                (p.tenant_id, thread_id, fb.message_id, p.user_id, fb.rating, fb.reason_code, fb.comment))
            return True


def new_thread_id() -> uuid.UUID:
    return uuid.uuid4()
