# ADR-0004: CopilotKit V2 UI with a minimal Node runtime bridge to the FastAPI agent
- Status: Accepted
- Date: 2026-10-24

## Context
The master prompt mandates CopilotKit **V2** (`@copilotkit/react-core/v2`, `CopilotKitProvider`, `CopilotSidebar`,
`CopilotPopup`) and warns that the React `runtimeUrl` is not automatically a Python AG-UI endpoint. Verified in
1.79.1: the supported production path is `CopilotRuntime` (Node) whose agents can be `HttpAgent`s pointing at any
AG-UI-compliant HTTP endpoint; connecting the browser directly to an agent is a dev-only option
(`agents__unsafe_dev_only`). The runtime forwards `authorization` and `x-*` headers to agents, has lifecycle hooks
(`onRequest`, `onBeforeHandler`, `onError`), ships telemetry (opt-out env vars) and exposes many routes
(threads, memories, transcribe, inspector) that Opsi does not use.

## Decision
- `apps/copilot-runtime`: a ~150-line Node service using `CopilotRuntime` + `createCopilotRuntimeHandler` +
  `createCopilotNodeHandler`, one `HttpAgent` per allowlisted agent id -> `http://127.0.0.1:8000/api/v2/agents/<id>`.
- Bind to 127.0.0.1:4000; NGINX exposes it at `/api/copilotkit/` with buffering off.
- Hooks: require an auth header, add `x-request-id`, allow only `info`, `agent/run|connect|stop` for known agents,
  mask error bodies (`onError`); `HttpAgent` gets a sanitizing `fetch` so upstream error bodies never reach the browser.
- `forwardHeaders: {allow: [authorization, x-request-id, traceparent, tracestate]}`; add `cookie` only if Opsi auth is cookie-based.
- Telemetry disabled before the runtime module loads (`env-guard.ts`).
- Pin `@ag-ui/client` to the exact version the runtime depends on.

## Consequences
- One more small process to run (systemd unit or compose), but no business logic lives in Node.
- Upgrades of CopilotKit must re-run `npm run check:exports` and the bridge tests.

## Alternatives considered
- Direct browser -> FastAPI AG-UI (`agents__unsafe_dev_only`) - unsupported for production; loses runtime features.
- Python-only CopilotKit runtime - not the supported V2 runtime path verified here.
- Hand-written "SSE that looks like AG-UI" - explicitly forbidden ("no fake interfaces").

## Verification
`apps/copilot-runtime/test/bridge.test.mjs` (7 tests: header allowlist, auth precheck, route allowlist, error
masking, info) and `tests/e2e/bridge_smoke.py` (real runtime <-> real FastAPI). `scripts/verify-runtime-exports.mjs`.
