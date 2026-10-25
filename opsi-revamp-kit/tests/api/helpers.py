"""Helpers for API tests: test auth adapter, app factory, SSE parsing, AG-UI validation."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jsonpatch
from ag_ui.core import Event
from app.modules._shared.errors import Unauthorized
from app.modules._shared.settings import ApiSettings
from app.modules.identity.deps import set_existing_auth_adapter
from app.modules.identity.principal import Principal
from app.modules.install import build_memory_services, install_revamp
from app.modules.llm.gateway import ScriptedLLM
from app.modules.search.stores import MemoryIncidentStore
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

EVENT = TypeAdapter(Event)
NOW = datetime.now(timezone.utc)


async def header_auth(request: Request) -> Principal:
    """TEST ONLY: identity from x-test-* headers (simulates the existing-auth adapter)."""
    user = request.headers.get("x-test-user")
    if not user:
        raise Unauthorized()
    scope = request.headers.get("x-test-scope")
    return Principal(user_id=user, tenant_id=request.headers.get("x-test-tenant", "tenant-a"),
                     roles=frozenset(request.headers.get("x-test-roles", "investigator").split(",")),
                     service_scope=frozenset(scope.split(",")) if scope else None, auth_source="test")


def make_settings(**over: Any) -> ApiSettings:
    base = dict(env="lab", auth_mode="existing", attachments_bucket="opsi-unit-attach", attachments_scan_mode="guardduty",
                agent_max_tool_calls=4, agent_max_cost_units=50, agent_max_seconds=60, agent_max_llm_turns=4)
    base.update(over)
    return ApiSettings(**base)


def make_app(llm: ScriptedLLM, *, settings: ApiSettings | None = None, incidents: MemoryIncidentStore | None = None,
             s3_client: Any = None, extra_routes: list | None = None, ontology=None):
    set_existing_auth_adapter(header_auth)
    settings = settings or make_settings()
    container = build_memory_services(settings, llm, incidents=incidents or default_incidents(), s3_client=s3_client,
                                      extra_routes=extra_routes, ontology=ontology)
    app = FastAPI()
    install_revamp(app, container)
    return app, container, TestClient(app)


def default_incidents() -> MemoryIncidentStore:
    return MemoryIncidentStore(problems=[
        {"tenant_id": "tenant-a", "problem_id": "P1", "display_id": "P-24102", "title": "Failure rate increase payments",
         "status": "OPEN", "severity_level": "ERROR", "start_time": NOW - timedelta(hours=2), "end_time": None,
         "root_cause_entity_id": "payments", "affected_entity_ids": ["payments"],
         "evidence_ref": "dynatrace-problem://P1"},
        {"tenant_id": "tenant-b", "problem_id": "PB", "display_id": "P-9", "title": "Failure rate other tenant",
         "status": "OPEN", "severity_level": "ERROR", "start_time": NOW - timedelta(hours=2), "end_time": None,
         "root_cause_entity_id": "x", "affected_entity_ids": [], "evidence_ref": "dynatrace-problem://PB"},
    ])


def user(name: str = "alice", tenant: str = "tenant-a", roles: str = "investigator", scope: str | None = None) -> dict:
    headers = {"x-test-user": name, "x-test-tenant": tenant, "x-test-roles": roles, "accept": "text/event-stream"}
    if scope:
        headers["x-test-scope"] = scope
    return headers


def run_input(thread_id: str | None = None, messages: list[dict] | None = None, tools: list[str] | None = None,
              context: dict | None = None, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "threadId": thread_id or str(uuid.uuid4()), "runId": f"run-{uuid.uuid4().hex[:8]}",
        "state": {}, "messages": messages if messages is not None else
        [{"id": f"u-{uuid.uuid4().hex[:6]}", "role": "user", "content": "Why is payments failing?"}],
        "tools": [{"name": t, "description": t, "parameters": {"type": "object"}} for t in (tools or [])],
        "context": [{"description": "opsi.ui_context", "value": json.dumps(context)}] if context else [],
        "forwardedProps": {},
    }
    body.update(extra)
    return body


def parse_sse(text: str) -> list[dict[str, Any]]:
    events = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block or block.startswith(":"):
            continue
        assert block.startswith("data: "), block[:80]
        payload = json.loads(block[len("data: "):])
        EVENT.validate_python(payload)  # every event must match the AG-UI schema
        events.append(payload)
    return events


def types(events: list[dict]) -> list[str]:
    return [e["type"] for e in events]


def final_state(events: list[dict]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for e in events:
        if e["type"] == "STATE_SNAPSHOT":
            state = e["snapshot"]
        elif e["type"] == "STATE_DELTA":
            state = jsonpatch.apply_patch(state, e["delta"])
    return state


def assert_lifecycle(events: list[dict]) -> None:
    """AG-UI ordering rules this server guarantees."""
    t = types(events)
    assert t[0] == "RUN_STARTED"
    assert t[-1] in ("RUN_FINISHED", "RUN_ERROR")
    assert t.count("RUN_STARTED") == 1 and t.count("RUN_FINISHED") + t.count("RUN_ERROR") == 1
    open_text: set[str] = set()
    open_tools: set[str] = set()
    ended_tools: set[str] = set()
    for e in events:
        if e["type"] == "TEXT_MESSAGE_START":
            open_text.add(e["messageId"])
        elif e["type"] == "TEXT_MESSAGE_CONTENT":
            assert e["messageId"] in open_text and e["delta"]
        elif e["type"] == "TEXT_MESSAGE_END":
            open_text.remove(e["messageId"])
        elif e["type"] == "TOOL_CALL_START":
            open_tools.add(e["toolCallId"])
        elif e["type"] == "TOOL_CALL_ARGS":
            assert e["toolCallId"] in open_tools
        elif e["type"] == "TOOL_CALL_END":
            open_tools.remove(e["toolCallId"])
            ended_tools.add(e["toolCallId"])
        elif e["type"] == "TOOL_CALL_RESULT":
            assert e["toolCallId"] in ended_tools, "result before TOOL_CALL_END"
    assert not open_text and not open_tools
