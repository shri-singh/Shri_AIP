"""Append-only audit trail (opsi_audit.events) with a logging fallback.

Audit what a security reviewer will ask about: approvals, attachment downloads,
thread sharing, denied UI actions, admin changes. Never put payloads or secrets
in ``detail`` - ids and outcomes only.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Protocol

from .redaction import scrub_for_log

log = logging.getLogger("opsi.audit")


class AuditSink(Protocol):
    async def record(self, *, tenant_id: str, actor_id: str, action: str, target: str | None, outcome: str,
                     request_id: str | None = None, detail: dict[str, Any] | None = None) -> None: ...


class LogAuditSink:
    """Writes JSON lines to the 'opsi.audit' logger (ship it to your SIEM)."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []  # kept for tests / debugging

    async def record(self, *, tenant_id: str, actor_id: str, action: str, target: str | None, outcome: str,
                     request_id: str | None = None, detail: dict[str, Any] | None = None) -> None:
        event = {"tenant_id": tenant_id, "actor_id": actor_id, "action": action, "target": target,
                 "outcome": outcome, "request_id": request_id, "detail": detail or {}}
        self.events.append(event)
        log.info(scrub_for_log(json.dumps(event, default=str)))


class PgAuditSink:
    def __init__(self, db) -> None:
        self.db = db

    async def record(self, *, tenant_id: str, actor_id: str, action: str, target: str | None, outcome: str,
                     request_id: str | None = None, detail: dict[str, Any] | None = None) -> None:
        from psycopg.types.json import Jsonb

        from ..identity.principal import Principal

        system = Principal(user_id=actor_id, tenant_id=tenant_id, roles=frozenset())
        async with self.db.tenant_tx(system) as conn:
            await conn.execute(
                "INSERT INTO opsi_audit.events (tenant_id, actor_id, action, target, outcome, request_id, detail) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (tenant_id, actor_id, action, target, outcome, request_id, Jsonb(detail or {})),
            )
