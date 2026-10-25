# copilot-runtime (CopilotKit V2 runtime bridge)

Browser `CopilotKitProvider runtimeUrl="/api/copilotkit"` -> NGINX -> **this service (127.0.0.1:4000)** -> FastAPI AG-UI
agent at `OPSI_AGENT_BASE_URL/<agentId>`. Design: ADR-0004, consultation 01.

```
src/env-guard.ts   disables CopilotKit telemetry before the runtime module loads
src/config.ts      env -> config (validates URL, header allowlist)
src/server.ts      CopilotRuntime + HttpAgent(s) + hooks (auth precheck, request id, route/agent allowlist, error masking)
                   + sanitizingFetch (upstream error bodies never reach the browser)
src/main.ts        process entrypoint (127.0.0.1:4000, /healthz)
test/bridge.test.mjs        7 contract tests against a recording AG-UI upstream
scripts/verify-runtime-exports.mjs   fails if the installed packages lack the APIs used here
Dockerfile         non-root image (compose stack alternative to systemd)
```

## Build, test, run
```bash
export SCARF_ANALYTICS=false
npm ci                       # first time on a new box: npm install, then commit package-lock.json
npm run build && npm test && npm run check:exports
RUNTIME_PORT=4000 OPSI_AGENT_BASE_URL=http://127.0.0.1:8000/api/v2/agents npm start
curl -s http://127.0.0.1:4000/healthz
```
Service: `infrastructure/systemd/opsi-copilot-runtime.service` (env in `/etc/opsi/copilot-runtime.env`).
End-to-end with the FastAPI lab app: `python tests/e2e/bridge_smoke.py --runtime-dir apps/copilot-runtime`.

## Configuration
| Env | Default | Notes |
|---|---|---|
| `RUNTIME_HOST` / `RUNTIME_PORT` | 127.0.0.1 / 4000 | never bind 0.0.0.0 |
| `RUNTIME_BASE_PATH` | /api/copilotkit | must match the provider `runtimeUrl` |
| `OPSI_AGENT_BASE_URL` | http://127.0.0.1:8000/api/v2/agents | FastAPI agent prefix |
| `OPSI_COPILOT_AGENT_IDS` | opsi-investigator | comma list; also the allowlist |
| `RUNTIME_FORWARD_HEADERS` | authorization,x-request-id,traceparent,tracestate | allowlist mode; add `cookie` only for cookie auth |
| `RUNTIME_REQUIRE_AUTH_HEADERS` | authorization,cookie | at least one must be present |
| `RUNTIME_ALLOW_SUGGESTIONS` | false | `agent/suggest` runs a full agent run - keep off |
| `RUNTIME_MAX_BODY_BYTES` | 2097152 | |
| `RUNTIME_SSE_KEEPALIVE_SECONDS` | 15 | keeps proxies from closing idle streams |

## Upgrading CopilotKit
Bump `@copilotkit/runtime`, set `@ag-ui/client` to `npm view @copilotkit/runtime@<v> dependencies` value, `npm install`,
`npm ls @ag-ui/client` (single version), `npm run build && npm test && npm run check:exports`, run the E2E smoke, update
`docs/verified-facts.md`.
