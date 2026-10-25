"""Chat persistence contract + an in-memory implementation that mirrors the RLS rules.

Visibility rules (identical to database/migrations/0005_rls.sql):
- Everything is tenant-scoped.
- Folders and tags are private to their owner.
- A thread is readable by its owner, or by any tenant member when visibility='tenant';
  only the owner may modify it or append to it.
- Child rows (messages, evidence, attachments, runs) follow their thread.
Methods return ``None``/empty for rows the principal may not see, so callers map
that to 404 and never reveal existence.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from ..identity.principal import Principal
from .models import Attachment, Evidence, FeedbackIn, Folder, SearchHit, StoredMessage, Tag, Thread, ThreadQuery

UTC = timezone.utc


def now() -> datetime:
    return datetime.now(UTC)


class ChatRepository(Protocol):
    # folders
    async def create_folder(self, p: Principal, name: str, parent_id: uuid.UUID | None) -> Folder: ...
    async def list_folders(self, p: Principal) -> list[Folder]: ...
    async def delete_folder(self, p: Principal, folder_id: uuid.UUID) -> bool: ...
    # threads
    async def create_thread(self, p: Principal, thread_id: uuid.UUID, *, title: str, folder_id: uuid.UUID | None,
                            linked_incident_id: str | None, linked_service_id: str | None, agent_id: str) -> Thread: ...
    async def get_thread(self, p: Principal, thread_id: uuid.UUID) -> Thread | None: ...
    async def update_thread(self, p: Principal, thread_id: uuid.UUID, changes: dict[str, Any]) -> Thread | None: ...
    async def list_threads(self, p: Principal, query: ThreadQuery) -> list[Thread]: ...
    async def save_agent_state(self, p: Principal, thread_id: uuid.UUID, state: dict, ui_context: dict) -> None: ...
    async def get_agent_state(self, p: Principal, thread_id: uuid.UUID) -> dict: ...
    # messages
    async def append_messages(self, p: Principal, thread_id: uuid.UUID, messages: list[StoredMessage]) -> int: ...
    async def list_messages(self, p: Principal, thread_id: uuid.UUID, limit: int = 500) -> list[StoredMessage]: ...
    async def search(self, p: Principal, q: str, limit: int = 20) -> list[SearchHit]: ...
    # tags
    async def create_tag(self, p: Principal, name: str, color: str | None) -> Tag: ...
    async def list_tags(self, p: Principal) -> list[Tag]: ...
    async def set_thread_tags(self, p: Principal, thread_id: uuid.UUID, tag_ids: list[uuid.UUID]) -> bool: ...
    # runs, tools, evidence
    async def start_run(self, p: Principal, thread_id: uuid.UUID, run_id: str, model_ref: str | None,
                        trace_id: str | None) -> None: ...
    async def finish_run(self, p: Principal, run_id: str, status: str, *, input_tokens: int | None = None,
                         output_tokens: int | None = None, tool_calls: int = 0, cost_units: float = 0,
                         error_code: str | None = None) -> None: ...
    async def record_tool_run(self, p: Principal, thread_id: uuid.UUID, run_id: str, tool_call_id: str,
                              tool_name: str, executor: str, args: dict, status: str,
                              result_summary: dict | None, citations: int, cost_units: float,
                              latency_ms: int | None, error_code: str | None) -> None: ...
    async def add_evidence(self, p: Principal, thread_id: uuid.UUID, items: list[Evidence]) -> None: ...
    async def list_evidence(self, p: Principal, thread_id: uuid.UUID) -> list[Evidence]: ...
    # attachments
    async def create_attachment(self, p: Principal, att: Attachment) -> Attachment: ...
    async def get_attachment(self, p: Principal, attachment_id: uuid.UUID) -> Attachment | None: ...
    async def update_attachment(self, p: Principal, attachment_id: uuid.UUID, **changes: Any) -> None: ...
    # feedback
    async def upsert_feedback(self, p: Principal, thread_id: uuid.UUID, fb: FeedbackIn) -> bool: ...


@dataclass
class _ThreadRow:
    tenant_id: str
    thread: Thread
    state: dict = field(default_factory=dict)
    ui_context: dict = field(default_factory=dict)
    deleted: bool = False


class MemoryChatRepository:
    """Process-local store for tests and the lab app. Not for production (no durability)."""

    def __init__(self) -> None:
        self.folders: dict[uuid.UUID, tuple[str, str, Folder]] = {}
        self.threads: dict[uuid.UUID, _ThreadRow] = {}
        self.messages: dict[uuid.UUID, list[StoredMessage]] = {}
        self.tags: dict[uuid.UUID, tuple[str, str, Tag]] = {}
        self.thread_tags: dict[uuid.UUID, set[uuid.UUID]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.tool_runs: list[dict[str, Any]] = []
        self.evidence: dict[uuid.UUID, list[Evidence]] = {}
        self.attachments: dict[uuid.UUID, tuple[str, Attachment]] = {}
        self.feedback: dict[tuple[uuid.UUID, str, str], FeedbackIn] = {}

    # -- visibility helpers ------------------------------------------------------------
    def _visible(self, p: Principal, thread_id: uuid.UUID) -> _ThreadRow | None:
        row = self.threads.get(thread_id)
        if not row or row.deleted or row.tenant_id != p.tenant_id:
            return None
        if row.thread.owner_id != p.user_id and row.thread.visibility != "tenant":
            return None
        return row

    def _owned(self, p: Principal, thread_id: uuid.UUID) -> _ThreadRow | None:
        row = self._visible(p, thread_id)
        return row if row and row.thread.owner_id == p.user_id else None

    def _with_tags(self, row: _ThreadRow) -> Thread:
        names = sorted(self.tags[t][2].name for t in self.thread_tags.get(row.thread.id, set()) if t in self.tags)
        return row.thread.model_copy(update={"tags": names})

    # -- folders -------------------------------------------------------------------------
    async def create_folder(self, p, name, parent_id):
        for tenant, owner, f in self.folders.values():
            if (tenant, owner, f.parent_id, f.name.lower()) == (p.tenant_id, p.user_id, parent_id, name.lower()):
                raise ValueError("folder name already exists")
        if parent_id and (parent_id not in self.folders or self.folders[parent_id][:2] != (p.tenant_id, p.user_id)):
            raise LookupError("parent folder not found")
        folder = Folder(id=uuid.uuid4(), name=name, parent_id=parent_id, created_at=now())
        self.folders[folder.id] = (p.tenant_id, p.user_id, folder)
        return folder

    async def list_folders(self, p):
        return sorted((f for t, o, f in self.folders.values() if (t, o) == (p.tenant_id, p.user_id)),
                      key=lambda f: f.name.lower())

    async def delete_folder(self, p, folder_id):
        item = self.folders.get(folder_id)
        if not item or item[:2] != (p.tenant_id, p.user_id):
            return False
        del self.folders[folder_id]
        for row in self.threads.values():
            if row.thread.folder_id == folder_id:
                row.thread = row.thread.model_copy(update={"folder_id": None})
        return True

    # -- threads -------------------------------------------------------------------------
    async def create_thread(self, p, thread_id, *, title, folder_id, linked_incident_id, linked_service_id, agent_id):
        if thread_id in self.threads:
            raise ValueError("thread id already exists")
        if folder_id and (folder_id not in self.folders or self.folders[folder_id][:2] != (p.tenant_id, p.user_id)):
            raise LookupError("folder not found")
        ts = now()
        thread = Thread(id=thread_id, owner_id=p.user_id, title=title, agent_id=agent_id, folder_id=folder_id,
                        linked_incident_id=linked_incident_id, linked_service_id=linked_service_id,
                        created_at=ts, updated_at=ts)
        self.threads[thread_id] = _ThreadRow(p.tenant_id, thread)
        return thread

    async def get_thread(self, p, thread_id):
        row = self._visible(p, thread_id)
        return self._with_tags(row) if row else None

    async def update_thread(self, p, thread_id, changes):
        row = self._owned(p, thread_id)
        if not row:
            return None
        if changes.get("folder_id") and (changes["folder_id"] not in self.folders
                                         or self.folders[changes["folder_id"]][:2] != (p.tenant_id, p.user_id)):
            raise LookupError("folder not found")
        row.thread = row.thread.model_copy(update={**changes, "updated_at": now()})
        return self._with_tags(row)

    async def list_threads(self, p, query):
        out = []
        tag_ids = {tid for tid, (t, o, tag) in self.tags.items()
                   if (t, o) == (p.tenant_id, p.user_id) and query.tag and tag.name.lower() == query.tag.lower()}
        for row in self.threads.values():
            th = row.thread
            if not self._visible(p, th.id):
                continue
            if th.owner_id != p.user_id and not query.include_shared:
                continue
            if th.archived_at and not query.include_archived:
                continue
            if query.folder_id and th.folder_id != query.folder_id:
                continue
            if query.incident_id and th.linked_incident_id != query.incident_id:
                continue
            if query.tag and not (self.thread_tags.get(th.id, set()) & tag_ids):
                continue
            if query.q:
                text = " ".join([th.title] + [m.content_text or "" for m in self.messages.get(th.id, [])]).lower()
                if not all(word in text for word in query.q.lower().split()):
                    continue
            if query.before and (th.last_message_at or th.created_at) >= query.before:
                continue
            out.append(self._with_tags(row))
        out.sort(key=lambda t: t.last_message_at or t.created_at, reverse=True)
        return out[: query.limit]

    async def save_agent_state(self, p, thread_id, state, ui_context):
        row = self._owned(p, thread_id)
        if row:
            row.state, row.ui_context = state, ui_context

    async def get_agent_state(self, p, thread_id):
        row = self._visible(p, thread_id)
        return dict(row.state) if row else {}

    # -- messages ------------------------------------------------------------------------
    async def append_messages(self, p, thread_id, messages):
        row = self._owned(p, thread_id)
        if not row:
            raise LookupError("thread not found")
        existing = {m.message_id for m in self.messages.get(thread_id, [])}
        added = 0
        for m in messages:
            if m.message_id in existing:
                continue
            self.messages.setdefault(thread_id, []).append(m.model_copy(update={"created_at": m.created_at or now()}))
            existing.add(m.message_id)
            added += 1
        if added:
            row.thread = row.thread.model_copy(update={"last_message_at": now(), "updated_at": now()})
        return added

    async def list_messages(self, p, thread_id, limit=500):
        if not self._visible(p, thread_id):
            return []
        return list(self.messages.get(thread_id, []))[-limit:]

    async def search(self, p, q, limit=20):
        words = q.lower().split()
        hits = []
        for thread_id, msgs in self.messages.items():
            row = self._visible(p, thread_id)
            if not row or row.thread.owner_id != p.user_id:
                continue
            for m in msgs:
                if m.content_text and all(w in m.content_text.lower() for w in words):
                    hits.append(SearchHit(thread_id=thread_id, thread_title=row.thread.title,
                                          message_id=m.message_id, snippet=m.content_text[:200], at=m.created_at))
        return hits[:limit]

    # -- tags ------------------------------------------------------------------------------
    async def create_tag(self, p, name, color):
        for t, o, tag in self.tags.values():
            if (t, o) == (p.tenant_id, p.user_id) and tag.name.lower() == name.lower():
                return tag
        tag = Tag(id=uuid.uuid4(), name=name, color=color)
        self.tags[tag.id] = (p.tenant_id, p.user_id, tag)
        return tag

    async def list_tags(self, p):
        return sorted((tag for t, o, tag in self.tags.values() if (t, o) == (p.tenant_id, p.user_id)),
                      key=lambda tg: tg.name.lower())

    async def set_thread_tags(self, p, thread_id, tag_ids):
        if not self._owned(p, thread_id):
            return False
        mine = {tid for tid, (t, o, _) in self.tags.items() if (t, o) == (p.tenant_id, p.user_id)}
        if not set(tag_ids) <= mine:
            raise LookupError("tag not found")
        self.thread_tags[thread_id] = set(tag_ids)
        return True

    # -- runs / tools / evidence -----------------------------------------------------------
    async def start_run(self, p, thread_id, run_id, model_ref, trace_id):
        if not self._owned(p, thread_id):
            raise LookupError("thread not found")
        self.runs[run_id] = {"tenant_id": p.tenant_id, "thread_id": thread_id, "user_id": p.user_id,
                             "status": "running", "model_ref": model_ref, "trace_id": trace_id}

    async def finish_run(self, p, run_id, status, *, input_tokens=None, output_tokens=None, tool_calls=0,
                         cost_units=0, error_code=None):
        run = self.runs.get(run_id)
        if run and run["tenant_id"] == p.tenant_id:
            run.update(status=status, input_tokens=input_tokens, output_tokens=output_tokens,
                       tool_calls=tool_calls, cost_units=cost_units, error_code=error_code)

    async def record_tool_run(self, p, thread_id, run_id, tool_call_id, tool_name, executor, args, status,
                              result_summary, citations, cost_units, latency_ms, error_code):
        self.tool_runs.append({"tenant_id": p.tenant_id, "thread_id": thread_id, "run_id": run_id,
                               "tool_call_id": tool_call_id, "tool_name": tool_name, "executor": executor,
                               "args": args, "status": status, "result_summary": result_summary,
                               "citations": citations, "error_code": error_code})

    async def add_evidence(self, p, thread_id, items):
        if not self._owned(p, thread_id):
            raise LookupError("thread not found")
        current = self.evidence.setdefault(thread_id, [])
        keys = {e.citation_key for e in current}
        current.extend(e for e in items if e.citation_key not in keys)

    async def list_evidence(self, p, thread_id):
        return list(self.evidence.get(thread_id, [])) if self._visible(p, thread_id) else []

    # -- attachments -----------------------------------------------------------------------
    async def create_attachment(self, p, att):
        if not self._owned(p, att.thread_id):
            raise LookupError("thread not found")
        self.attachments[att.id] = (p.tenant_id, att)
        return att

    async def get_attachment(self, p, attachment_id):
        item = self.attachments.get(attachment_id)
        if not item or item[0] != p.tenant_id or not self._visible(p, item[1].thread_id):
            return None
        return item[1]

    async def update_attachment(self, p, attachment_id, **changes):
        item = self.attachments.get(attachment_id)
        if item and item[0] == p.tenant_id and self._owned(p, item[1].thread_id):
            self.attachments[attachment_id] = (item[0], item[1].model_copy(update=changes))

    # -- feedback --------------------------------------------------------------------------
    async def upsert_feedback(self, p, thread_id, fb):
        if not self._visible(p, thread_id):
            return False
        self.feedback[(thread_id, fb.message_id, p.user_id)] = fb
        return True
