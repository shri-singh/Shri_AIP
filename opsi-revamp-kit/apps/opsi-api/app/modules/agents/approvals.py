"""Human approval of agent-proposed actions (HITL).

Flow:
1. The model calls an approval-gated UI action (e.g. ``draft_incident_update``).
2. The orchestrator validates it, stores a *pending* approval (15 min expiry) and streams the
   tool call to the browser, where ``useHumanInTheLoop`` renders Approve / Reject.
3. The browser calls ``POST /api/v2/actions/{approval_id}/decision`` with the user's own session.
   This endpoint - not the model - checks permission (``action:approve``), expiry, optional
   four-eyes, and runs the registered executor with the *deciding user's* authority.
4. The browser answers the tool call (``respond(result)``) so the agent can continue.

``EXECUTORS`` ships with a record-only executor. Wire the real call into the existing
Opsi incident service (its own authorization applies) - see docs/handbook/FAQ.md
"How do I make draft_incident_update actually save?".
"""
from __future__ import annotations

import os
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from .._shared.container import OpsiServices, services
from .._shared.errors import Conflict, Forbidden, NotFound
from ..identity.deps import require
from ..identity.principal import Principal

UTC = timezone.utc


class Approval(BaseModel):
    id: uuid.UUID
    thread_id: uuid.UUID
    run_id: str
    tool_call_id: str
    action_kind: str
    action_args: dict[str, Any]
    requested_for: str
    status: Literal["pending", "approved", "rejected", "expired", "executed", "failed"] = "pending"
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None
    execution_result: dict[str, Any] | None = None
    expires_at: datetime


class ApprovalStore(Protocol):
    async def create(self, p: Principal, approval: Approval) -> Approval: ...
    async def get(self, p: Principal, approval_id: uuid.UUID) -> Approval | None: ...
    async def update(self, p: Principal, approval_id: uuid.UUID, **changes: Any) -> None: ...


class MemoryApprovalStore:
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, tuple[str, Approval]] = {}

    async def create(self, p, approval):
        self.items[approval.id] = (p.tenant_id, approval)
        return approval

    async def get(self, p, approval_id):
        item = self.items.get(approval_id)
        return item[1] if item and item[0] == p.tenant_id else None

    async def update(self, p, approval_id, **changes):
        item = self.items.get(approval_id)
        if item and item[0] == p.tenant_id:
            self.items[approval_id] = (item[0], item[1].model_copy(update=changes))


class PgApprovalStore:
    def __init__(self, db) -> None:
        self.db = db

    async def create(self, p, approval):
        from psycopg.types.json import Jsonb

        async with self.db.tenant_tx(p) as conn:
            await conn.execute(
                "INSERT INTO opsi_chat.action_approvals (id, tenant_id, thread_id, run_id, tool_call_id, action_kind, "
                "action_args, requested_for, status, expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s)",
                (approval.id, p.tenant_id, approval.thread_id, approval.run_id, approval.tool_call_id,
                 approval.action_kind, Jsonb(approval.action_args), approval.requested_for, approval.expires_at))
        return approval

    async def get(self, p, approval_id):
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute(
                "SELECT id, thread_id, run_id, tool_call_id, action_kind, action_args, requested_for, status, "
                "decided_by, decided_at, decision_reason, execution_result, expires_at "
                "FROM opsi_chat.action_approvals WHERE id = %s", (approval_id,))
            row = await cur.fetchone()
            return Approval(**row) if row else None

    async def update(self, p, approval_id, **changes):
        from psycopg.types.json import Jsonb

        allowed = {k: (Jsonb(v) if k == "execution_result" and v is not None else v) for k, v in changes.items()
                   if k in {"status", "decided_by", "decided_at", "decision_reason", "execution_result", "executed_at"}}
        if allowed:
            sets = ", ".join(f"{k} = %s" for k in allowed)
            async with self.db.tenant_tx(p) as conn:
                await conn.execute(f"UPDATE opsi_chat.action_approvals SET {sets} WHERE id = %s",
                                   (*allowed.values(), approval_id))


ActionExecutor = Callable[[Principal, Approval], Awaitable[dict[str, Any]]]


async def record_only_executor(p: Principal, approval: Approval) -> dict[str, Any]:
    return {"saved": False, "note": "Approved and recorded. Executor not yet integrated with the Opsi incident API."}


EXECUTORS: dict[str, ActionExecutor] = {"draft_incident_update": record_only_executor}

router = APIRouter(prefix="/api/v2/actions", tags=["actions"])


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=500)


def _store(svc: OpsiServices) -> ApprovalStore:
    store = (svc.extras or {}).get("approvals")
    if store is None:
        raise NotFound("approvals")
    return store


@router.get("/{approval_id}", response_model=Approval)
async def get_approval(approval_id: uuid.UUID, p: Principal = Depends(require("chat:use")),
                       svc: OpsiServices = Depends(services)):
    approval = await _store(svc).get(p, approval_id)
    if not approval or approval.requested_for != p.user_id and not p.can("action:approve"):
        raise NotFound("approval")
    return approval


@router.post("/{approval_id}/decision", response_model=Approval)
async def decide(approval_id: uuid.UUID, body: DecisionIn, request: Request,
                 p: Principal = Depends(require("action:approve")), svc: OpsiServices = Depends(services)):
    store = _store(svc)
    approval = await store.get(p, approval_id)
    if not approval:
        raise NotFound("approval")
    if approval.status != "pending":
        raise Conflict(f"approval already {approval.status}")
    now = datetime.now(UTC)
    if approval.expires_at <= now:
        await store.update(p, approval_id, status="expired")
        raise Conflict("approval expired; ask the assistant to propose it again")
    four_eyes = os.environ.get("OPSI_APPROVAL_FOUR_EYES", "false").lower() == "true"
    if four_eyes and approval.requested_for == p.user_id:
        raise Forbidden("four-eyes policy: someone else must approve this action")
    outcome: dict[str, Any] = {"status": "rejected"}
    if body.decision == "reject":
        await store.update(p, approval_id, status="rejected", decided_by=p.user_id, decided_at=now,
                           decision_reason=body.reason)
    else:
        executor = EXECUTORS.get(approval.action_kind)
        if executor is None:
            raise Conflict("no executor registered for this action")
        await store.update(p, approval_id, status="approved", decided_by=p.user_id, decided_at=now,
                           decision_reason=body.reason)
        try:
            result = await executor(p, approval)
            await store.update(p, approval_id, status="executed", execution_result=result, executed_at=now)
            outcome = {"status": "executed"}
        except Exception as exc:  # noqa: BLE001
            await store.update(p, approval_id, status="failed", execution_result={"error": type(exc).__name__})
            outcome = {"status": "failed"}
    await svc.audit.record(tenant_id=p.tenant_id, actor_id=p.user_id, action=f"approval.{body.decision}",
                           target=str(approval_id), outcome="allowed", request_id=request.headers.get("x-request-id"),
                           detail={"action_kind": approval.action_kind, **outcome})
    return await store.get(p, approval_id)
