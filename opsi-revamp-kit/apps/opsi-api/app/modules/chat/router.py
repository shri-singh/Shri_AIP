"""REST API for persistent chat: folders, threads, messages (restore after login), tags,
search, evidence, attachments and feedback. Mounted under ``/api/v2/chat``.

The React app calls these with the user's normal session/token; the agent
endpoint writes messages during runs. Every handler derives tenant/user from the
authenticated principal only.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status

from .._shared.container import OpsiServices, services
from .._shared.errors import Conflict, Forbidden, NotFound
from ..identity.deps import require
from ..identity.principal import Principal
from .models import (
    AttachmentInitIn,
    AttachmentInitOut,
    Evidence,
    FeedbackIn,
    Folder,
    FolderIn,
    SearchHit,
    Tag,
    TagIn,
    Thread,
    ThreadCreate,
    ThreadQuery,
    ThreadTagsIn,
    ThreadUpdate,
)

router = APIRouter(prefix="/api/v2/chat", tags=["chat"])
CHAT = require("chat:use")


# ---------------------------------------------------------------- folders
@router.post("/folders", response_model=Folder, status_code=status.HTTP_201_CREATED)
async def create_folder(body: FolderIn, p: Principal = Depends(CHAT), svc: OpsiServices = Depends(services)):
    try:
        return await svc.chat.create_folder(p, body.name, body.parent_id)
    except ValueError:
        raise Conflict("a folder with this name already exists here") from None
    except LookupError:
        raise NotFound("parent folder") from None


@router.get("/folders", response_model=list[Folder])
async def list_folders(p: Principal = Depends(CHAT), svc: OpsiServices = Depends(services)):
    return await svc.chat.list_folders(p)


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(folder_id: uuid.UUID, p: Principal = Depends(CHAT), svc: OpsiServices = Depends(services)):
    if not await svc.chat.delete_folder(p, folder_id):
        raise NotFound("folder")


# ---------------------------------------------------------------- threads
@router.post("/threads", response_model=Thread, status_code=status.HTTP_201_CREATED)
async def create_thread(body: ThreadCreate, p: Principal = Depends(CHAT), svc: OpsiServices = Depends(services)):
    if body.linked_service_id and not p.can_access_service(body.linked_service_id):
        raise NotFound("service")
    thread_id = body.id or uuid.uuid4()
    try:
        return await svc.chat.create_thread(p, thread_id, title=body.title or "New investigation",
                                            folder_id=body.folder_id, linked_incident_id=body.linked_incident_id,
                                            linked_service_id=body.linked_service_id,
                                            agent_id=svc.settings.copilot_agent_ids[0])
    except ValueError:
        raise Conflict("thread id already exists") from None
    except LookupError:
        raise NotFound("folder") from None


@router.get("/threads", response_model=list[Thread])
async def list_threads(
    folder_id: uuid.UUID | None = None, tag: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=200), incident_id: str | None = Query(default=None, max_length=200),
    include_archived: bool = False, include_shared: bool = False, limit: int = Query(default=50, ge=1, le=200),
    before: datetime | None = None, p: Principal = Depends(CHAT), svc: OpsiServices = Depends(services),
):
    query = ThreadQuery(folder_id=folder_id, tag=tag, q=q, incident_id=incident_id, include_archived=include_archived,
                        include_shared=include_shared, limit=limit, before=before)
    return await svc.chat.list_threads(p, query)


@router.get("/threads/{thread_id}", response_model=Thread)
async def get_thread(thread_id: uuid.UUID, p: Principal = Depends(CHAT), svc: OpsiServices = Depends(services)):
    thread = await svc.chat.get_thread(p, thread_id)
    if not thread:
        raise NotFound("thread")
    return thread


@router.patch("/threads/{thread_id}", response_model=Thread)
async def update_thread(thread_id: uuid.UUID, body: ThreadUpdate, request: Request,
                        p: Principal = Depends(CHAT), svc: OpsiServices = Depends(services)):
    changes: dict[str, Any] = {}
    if body.title is not None:
        changes["title"] = body.title
    if body.clear_folder:
        changes["folder_id"] = None
    elif body.folder_id is not None:
        changes["folder_id"] = body.folder_id
    if body.visibility is not None:
        if body.visibility == "tenant" and not p.can("chat:share"):
            raise Forbidden("sharing a thread requires the chat:share permission")
        changes["visibility"] = body.visibility
    if body.archived is not None:
        changes["archived_at"] = datetime.now(timezone.utc) if body.archived else None
    try:
        thread = await svc.chat.update_thread(p, thread_id, changes)
    except LookupError:
        raise NotFound("folder") from None
    if not thread:
        raise NotFound("thread")
    if "visibility" in changes:
        await svc.audit.record(tenant_id=p.tenant_id, actor_id=p.user_id, action="thread.visibility",
                               target=str(thread_id), outcome="allowed",
                               request_id=request.headers.get("x-request-id"), detail={"to": body.visibility})
    return thread


@router.get("/threads/{thread_id}/messages")
async def list_messages(thread_id: uuid.UUID, limit: int = Query(default=500, ge=1, le=2000),
                        p: Principal = Depends(CHAT), svc: OpsiServices = Depends(services)) -> dict[str, Any]:
    """Messages in AG-UI wire format (camelCase) for ``agent.setMessages(...)`` after login."""
    thread = await svc.chat.get_thread(p, thread_id)
    if not thread:
        raise NotFound("thread")
    messages = await svc.chat.list_messages(p, thread_id, limit)
    return {
        "thread": thread.model_dump(mode="json"),
        "messages": [m.content_json for m in messages],
        "evidence": [e.model_dump(mode="json") for e in await svc.chat.list_evidence(p, thread_id)],
        "state": await svc.chat.get_agent_state(p, thread_id),
    }


@router.get("/threads/{thread_id}/evidence", response_model=list[Evidence])
async def list_evidence(thread_id: uuid.UUID, p: Principal = Depends(CHAT), svc: OpsiServices = Depends(services)):
    if not await svc.chat.get_thread(p, thread_id):
        raise NotFound("thread")
    return await svc.chat.list_evidence(p, thread_id)


@router.put("/threads/{thread_id}/tags", response_model=Thread)
async def set_thread_tags(thread_id: uuid.UUID, body: ThreadTagsIn, p: Principal = Depends(CHAT),
                          svc: OpsiServices = Depends(services)):
    try:
        ok = await svc.chat.set_thread_tags(p, thread_id, body.tag_ids)
    except LookupError:
        raise NotFound("tag") from None
    if not ok:
        raise NotFound("thread")
    return await svc.chat.get_thread(p, thread_id)


# ---------------------------------------------------------------- tags & search
@router.post("/tags", response_model=Tag, status_code=status.HTTP_201_CREATED)
async def create_tag(body: TagIn, p: Principal = Depends(CHAT), svc: OpsiServices = Depends(services)):
    return await svc.chat.create_tag(p, body.name, body.color)


@router.get("/tags", response_model=list[Tag])
async def list_tags(p: Principal = Depends(CHAT), svc: OpsiServices = Depends(services)):
    return await svc.chat.list_tags(p)


@router.get("/search", response_model=list[SearchHit])
async def search(q: str = Query(min_length=2, max_length=200), limit: int = Query(default=20, ge=1, le=100),
                 p: Principal = Depends(CHAT), svc: OpsiServices = Depends(services)):
    return await svc.chat.search(p, q, limit)


# ---------------------------------------------------------------- attachments
@router.post("/threads/{thread_id}/attachments", response_model=AttachmentInitOut,
             status_code=status.HTTP_201_CREATED)
async def init_attachment(thread_id: uuid.UUID, body: AttachmentInitIn,
                          p: Principal = Depends(require("attachment:upload")), svc: OpsiServices = Depends(services)):
    return await svc.attachments.init(p, thread_id, body)


@router.post("/attachments/{attachment_id}/finalize")
async def finalize_attachment(attachment_id: uuid.UUID, p: Principal = Depends(require("attachment:upload")),
                              svc: OpsiServices = Depends(services)) -> dict[str, Any]:
    att = await svc.attachments.finalize(p, attachment_id)
    return {"id": str(att.id), "status": att.status}


@router.get("/attachments/{attachment_id}/download")
async def download_attachment(attachment_id: uuid.UUID, request: Request, p: Principal = Depends(CHAT),
                              svc: OpsiServices = Depends(services)) -> dict[str, Any]:
    try:
        result = await svc.attachments.download_url(p, attachment_id)
        outcome = "allowed"
        return result
    except Exception:
        outcome = "denied"
        raise
    finally:
        await svc.audit.record(tenant_id=p.tenant_id, actor_id=p.user_id, action="attachment.download",
                               target=str(attachment_id), outcome=outcome,
                               request_id=request.headers.get("x-request-id"))


# ---------------------------------------------------------------- feedback
@router.post("/threads/{thread_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def feedback(thread_id: uuid.UUID, body: FeedbackIn, p: Principal = Depends(require("feedback:write")),
                   svc: OpsiServices = Depends(services)):
    from .._shared.redaction import Redactor

    if body.comment:
        body = body.model_copy(update={"comment": Redactor("strict").redact_text(body.comment).text})
    if not await svc.chat.upsert_feedback(p, thread_id, body):
        raise NotFound("thread")
