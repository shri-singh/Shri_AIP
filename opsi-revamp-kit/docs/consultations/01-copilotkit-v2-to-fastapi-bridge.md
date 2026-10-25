# 01 - CopilotKit V2 <-> FastAPI: how the bridge works and how to debug it

## The question
"Our backend is Python/FastAPI. CopilotKit's React provider wants a `runtimeUrl`. How do we connect them properly,
keep auth, stream answers, run UI actions and restore threads - without faking the protocol?"

## Short answer
Browser `CopilotKitProvider runtimeUrl="/api/copilotkit"` -> NGINX -> **Node CopilotKit V2 runtime** (`CopilotRuntime` with
one `HttpAgent` per agent) -> **FastAPI AG-UI endpoint** `POST /api/v2/agents/<agentId>` streaming AG-UI events. The runtime
forwards the user's `Authorization` header; FastAPI validates it. History lives in PostgreSQL; the UI restores it with
`agent.setMessages()`. Verified with real packages (1.79.1) and an end-to-end test.

## The three protocols in play
1. **Browser <-> runtime**: CopilotKit's runtime protocol (multi-route: `GET {base}/info`, `POST {base}/agent/{id}/run`,
   `connect`, `stop`, threads...). The run body is an AG-UI `RunAgentInput`; the response is an SSE stream of AG-UI events.
2. **Runtime <-> agent**: AG-UI over HTTP. `HttpAgent` POSTs `RunAgentInput` (camelCase JSON, `Accept: text/event-stream`)
   to its URL and parses `data: {...}` events.
3. **Agent <-> model/tools**: our business (Portkey, routes).

Why not point the provider at FastAPI directly? The provider speaks protocol 1, FastAPI speaks protocol 2; the only
browser-to-agent option (`agents__unsafe_dev_only`) is documented as dev-only. The runtime also gives hooks
(auth precheck, request ids, route allowlist), keep-alives and header policy.

## Request walk-through (what to look at when debugging)

| Hop | What happens | Where to look |
|---|---|---|
| Browser | provider's `headers` builder adds `Authorization: Bearer <token>` + `x-request-id` | DevTools -> Network -> `.../agent/opsi-investigator/run` request headers |
| NGINX | `/api/copilotkit/` -> 127.0.0.1:4000, buffering off | `access.log` (status 200 and long duration for streams) |
| Runtime `onRequest` | 401 if no auth header; adds `x-request-id` | runtime log `runtime_request` |
| Runtime `onBeforeHandler` | 404 unless route in {info, agent/run, agent/connect, agent/stop} and agent allowlisted | same |
| Runtime -> FastAPI | `HttpAgent` POST with forwarded headers (allowlist) | FastAPI access log `POST /api/v2/agents/...` |
| FastAPI pre-checks | 401/403 auth, 404 agent/thread, 400 thread id, 422 body | HTTP status in runtime log `agent_http_error` |
| FastAPI stream | RUN_STARTED ... RUN_FINISHED/RUN_ERROR | `curl -N` the agent directly (below) |

Direct agent test (on the host, bypassing runtime; needs a valid token):
```bash
curl -N -s http://127.0.0.1:8000/api/v2/agents/opsi-investigator \
  -H "Authorization: Bearer $TOKEN" -H "Accept: text/event-stream" -H "Content-Type: application/json" \
  -d '{"threadId":"'"$(uuidgen)"'","runId":"r1","state":{},"tools":[],"context":[],"forwardedProps":{},
       "messages":[{"id":"u1","role":"user","content":"hello"}]}'
```
Through the runtime: same body to `http://127.0.0.1:4000/api/copilotkit/agent/opsi-investigator/run`.

## Auth propagation options

| Opsi today | Do | Runtime settings |
|---|---|---|
| SPA holds an access token (bearer) | provider `headers={async () => ({Authorization: ...})}` | default (`authorization` forwarded) |
| HttpOnly session cookie | let the browser send it same-origin; forward it | `RUNTIME_FORWARD_HEADERS=authorization,cookie,x-request-id,...`; FastAPI `OPSI_AUTH_MODE=existing` adapter reads the cookie |
| NGINX/oauth2-proxy does SSO and injects headers | have the proxy inject a signed JWT (not a plain user header) | forward that header; FastAPI validates the JWT |
Never trust an unsigned `X-User` header coming from the network.

## Tools: who executes what
- **Server tools** (retrieval routes): model -> orchestrator executes -> `TOOL_CALL_START/ARGS/END` + `TOOL_CALL_RESULT`.
  The UI renders them via `useDefaultRenderTool`/`useRenderTool`.
- **Frontend tools** (UI actions): registered in React with `useFrontendTool` (sent to the agent in `RunAgentInput.tools`).
  The orchestrator validates arguments, streams the call **without** a result and ends the run; CopilotKit executes the
  handler and starts a new run containing the tool result (the orchestrator accepts it only if that call is pending).
- **Human-in-the-loop**: `useHumanInTheLoop` renders a component with `respond()`; approval itself goes through REST
  with the user's session (`/api/v2/actions/{id}/decision`), then `respond()` returns the outcome to the agent.

## State
Server emits `STATE_SNAPSHOT` at run start and `STATE_DELTA` (JSON Patch) as evidence accumulates. The client state is
display-only; the server ignores client `state`. Read it in React with `useAgent()` -> `agent.state` (re-renders on
`OnStateChanged`).

## Threads and restore
CopilotKit's `useThreads`/`CopilotThreadsDrawer` need CopilotKit Intelligence; Opsi uses its own store:
`chatApi.restore(id)` -> `agent.threadId = id; agent.setMessages(messages); agent.setState(state)` -> `<CopilotChat threadId={id}/>`.
The browser could tamper with the restored transcript - harmless, because the server reloads history from PostgreSQL.

## Cancellation
User presses stop -> runtime `agent/stop` / the fetch is aborted -> Starlette cancels the streaming task -> orchestrator
records `cancelled` (tested with a slow fake LLM). Make sure NGINX doesn't buffer (otherwise disconnects arrive late).

## Pitfalls (all seen during verification)
- `@ag-ui/client` version must equal the runtime's dependency (duplicate class types otherwise).
- Runtime telemetry must be disabled before import (`env-guard.ts`); npm install pings Scarf unless `SCARF_ANALYTICS=false`.
- Runtime default errors include upstream bodies/messages -> keep the sanitizing fetch and `onError`.
- Forward allowlist mode bypasses the default denylist - never allow `x-forwarded-*`/`host` (config guard rejects some).
- `TEXT_MESSAGE_CONTENT` with empty `delta` is invalid - the orchestrator skips empty deltas.
- SSE through NGINX needs `proxy_buffering off` and long read timeouts; the runtime sends keep-alive comments every 15 s.

## Verify
`make runtime` (7 tests), `make e2e`, `pytest tests/api/test_agui_contract.py`, browser DevTools EventStream tab.
