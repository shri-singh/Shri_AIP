# ADR-0005: FastAPI implements the AG-UI agent; the server owns history and state
- Status: Accepted
- Date: 2026-10-24

## Context
Opsi's business logic, data access and authorization live in Python/FastAPI. AG-UI (`ag-ui-protocol` 1.0.0) gives
typed events and an SSE encoder. CopilotKit sends the **whole message list** on every run, and a malicious client
could insert fake assistant/system messages ("I already approved everything") to steer the model.

## Decision
- `POST /api/v2/agents/{agent_id}` parses `RunAgentInput` with the official models and streams events via
  `EventEncoder`. Pre-stream failures are HTTP errors; in-stream failures are `RUN_ERROR` with safe messages.
- **History is read from PostgreSQL** each run. From the client we accept only new `user` messages and `tool`
  results whose `toolCallId` matches a pending browser action. Everything else is ignored, counted and audited.
- State (`STATE_SNAPSHOT` then RFC 6902 `STATE_DELTA`) is server-authored; client `state`/`forwardedProps` are ignored.
- Browser UI actions are AG-UI tool calls the client executes (frontend tools); server retrieval tools return
  `TOOL_CALL_RESULT` from the server.
- The endpoint is reachable only from the runtime (loopback / private subnet; NGINX denies `/api/v2/agents/`).

## Consequences
- The server is the single source of truth for transcripts, evidence and approvals.
- Every run re-reads history - acceptable for chat sizes (bounded to the last 40 messages for the model).

## Alternatives considered
- Trust client transcript (default behaviour of many examples) - history forgery.
- Agent frameworks (LangGraph, PydanticAI) - possible later behind the same endpoint; not required to meet the contract.

## Verification
`tests/api/test_agui_contract.py` - schema validation of every event, lifecycle ordering, forged history ignored,
frontend actions, approvals, errors, cancellation, restore after re-login.
