"""AG-UI endpoint consumed by the CopilotKit V2 Node runtime (``HttpAgent``).

    POST /api/v2/agents/{agent_id}
    Accept: text/event-stream
    Authorization: Bearer <user access token>      (forwarded by the runtime)
    body: RunAgentInput (camelCase JSON)

Response: ``text/event-stream`` of AG-UI events encoded by ``ag_ui.encoder.EventEncoder``.
Errors detected before streaming (auth, unknown agent, bad thread id, foreign thread)
are plain HTTP errors; errors after streaming starts are RUN_ERROR events.

This route must be reachable ONLY from the copilot-runtime (bind to 127.0.0.1 or a
private subnet and deny it in the public NGINX server block) - browsers talk to
the runtime at /api/copilotkit, never directly to this endpoint.
"""
from __future__ import annotations

import uuid

from ag_ui.core import RunAgentInput
from ag_ui.encoder import EventEncoder
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from .._shared.container import OpsiServices, services
from ..identity.deps import require
from ..identity.principal import Principal
from .orchestrator import Orchestrator, RunRejected

router = APIRouter(prefix="/api/v2/agents", tags=["agents"])
MAX_BODY_BYTES = 2 * 1024 * 1024


@router.post("/{agent_id}")
async def run_agent(agent_id: str, request: Request, p: Principal = Depends(require("chat:use")),
                    svc: OpsiServices = Depends(services)) -> StreamingResponse:
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(413, "request too large")
    try:
        run_input = RunAgentInput.model_validate_json(raw)
    except ValidationError:
        raise HTTPException(422, "body is not a valid AG-UI RunAgentInput") from None
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    orchestrator = Orchestrator(svc, p, request_id)
    try:
        await orchestrator.prepare(run_input, agent_id)
    except RunRejected as exc:
        raise HTTPException(exc.status, exc.message) from None
    encoder = EventEncoder(accept=request.headers.get("accept"))

    async def stream():
        async for event in orchestrator.run(run_input, agent_id):
            yield encoder.encode(event)

    return StreamingResponse(stream(), media_type=encoder.get_content_type(), headers={
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",  # tell NGINX not to buffer SSE
        "X-Request-Id": request_id,
    })
