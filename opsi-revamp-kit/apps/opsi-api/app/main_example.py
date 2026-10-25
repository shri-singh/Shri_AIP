"""How to graft the revamp into the EXISTING Opsi FastAPI app (do not replace its main.py).

Add roughly this to the existing app factory / startup code::

    from contextlib import asynccontextmanager
    from app.modules._shared.settings import get_settings
    from app.modules.install import build_services, install_revamp
    from app.modules.identity.deps import set_existing_auth_adapter

    @asynccontextmanager
    async def lifespan(app):
        # Option A (recommended first): reuse Opsi's existing auth
        # set_existing_auth_adapter(my_adapter)   # returns a Principal from Opsi's current user
        container = await build_services(get_settings())
        install_revamp(app, container, tracing=True)
        yield
        await container.extras["db"].close()

    app = FastAPI(lifespan=lifespan)   # or merge into the existing lifespan

Below is a runnable *lab* app (in-memory stores + scripted model, no AWS/DB) used by
the E2E smoke test and for exploring the API locally:

    cd apps/opsi-api && OPSI_ENV=lab OPSI_AUTH_MODE=dev uvicorn app.main_example:lab_app --factory --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI

from .modules._shared.settings import get_settings
from .modules.install import build_memory_services, install_revamp
from .modules.llm.gateway import ScriptedLLM, ScriptedTurn
from .modules.search.stores import MemoryIncidentStore


def create_lab_app() -> FastAPI:
    settings = get_settings()
    if settings.env not in ("dev", "lab"):
        raise RuntimeError("the lab app only runs with OPSI_ENV=dev or lab")
    now = datetime.now(timezone.utc)
    incidents = MemoryIncidentStore(problems=[{
        "tenant_id": settings.default_tenant_id, "problem_id": "P-1", "display_id": "P-24102",
        "title": "Failure rate increase on payments", "status": "OPEN", "severity_level": "ERROR",
        "start_time": now - timedelta(hours=1), "end_time": None, "root_cause_entity_id": "payments",
        "affected_entity_ids": ["payments"], "evidence_ref": "dynatrace-problem://P-1"}])
    llm = ScriptedLLM([
        ScriptedTurn(tool_calls=[("historical_incident_search", {
            "query": "failure rate", "time_from": (now - timedelta(days=1)).isoformat(),
            "time_to": now.isoformat()})]),
        ScriptedTurn(text="Payments has an open failure-rate problem P-24102 [c1]. "
                          "This is a scripted lab answer; configure PORTKEY_* for real reasoning."),
    ])
    app = FastAPI(title="Opsi revamp lab")
    install_revamp(app, build_memory_services(settings, llm, incidents=incidents))
    return app


def lab_app() -> FastAPI:  # uvicorn factory: uvicorn app.main_example:lab_app --factory
    return create_lab_app()
