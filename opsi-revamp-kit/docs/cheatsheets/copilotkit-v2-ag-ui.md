# CopilotKit V2 + AG-UI (verified against 1.79.1 / AG-UI 1.0)

## React (V2 only)
```tsx
import { CopilotKitProvider, CopilotChat, CopilotSidebar, CopilotPopup,
         useAgent, useAgentContext, useFrontendTool, useHumanInTheLoop, useRenderTool, useDefaultRenderTool }
  from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";

<CopilotKitProvider runtimeUrl="/api/copilotkit" agentId="opsi-investigator"
  headers={async () => ({ Authorization: `Bearer ${await getToken()}` })} credentials="same-origin"
  enableInspector={false} onError={({ error, code }) => report(code)}>
  ...
  <CopilotSidebar defaultOpen={false} width={420} labels={{ chatInputPlaceholder: "Ask..." }} />
</CopilotKitProvider>

<CopilotChat agentId="opsi-investigator" threadId={threadId} />
useAgentContext({ description: "opsi.ui_context", value: { page: "incident", incident_id } });
useFrontendTool({ name: "set_dashboard_filter", description: "...", parameters: zodSchema, handler: async (args) => "ok" });
useHumanInTheLoop({ name: "draft_incident_update", description: "...", parameters: zodSchema, render: ApprovalCard });
useRenderTool({ name: "render_chart", parameters: zodSchema, render: ({ status, parameters, result }) => <Chart/> });
const { agent, isReady } = useAgent({ agentId: "opsi-investigator" }); agent.setMessages(msgs); agent.setState(state);
agent.subscribe({ onCustomEvent: ({ event }) => ... });
```
V1 names to avoid: `<CopilotKit>` (compat wrapper), `@copilotkit/react-ui`, `useCopilotAction`, `useCopilotReadable`, `useCopilotChat`.

## Runtime (Node)
```ts
import { CopilotRuntime, createCopilotRuntimeHandler } from "@copilotkit/runtime/v2";
import { createCopilotNodeHandler } from "@copilotkit/runtime/v2/node";
import { HttpAgent } from "@ag-ui/client";       // pin to the runtime's dependency version
const runtime = new CopilotRuntime({ agents: { "opsi-investigator": new HttpAgent({ url, fetch }) },
                                     forwardHeaders: { allow: ["authorization", "x-request-id"] } });
const handler = createCopilotRuntimeHandler({ runtime, basePath: "/api/copilotkit", hooks: { onRequest, onBeforeHandler, onError } });
http.createServer(createCopilotNodeHandler(handler)).listen(4000, "127.0.0.1");
```
Routes: `GET {base}/info`, `POST {base}/agent/{id}/run|connect`, `POST {base}/agent/{id}/stop/{threadId}`, threads/*, memories/*, transcribe (blocked in Opsi).
Env: `COPILOTKIT_TELEMETRY_DISABLED=true`, `DO_NOT_TRACK=1`; npm installs: `SCARF_ANALYTICS=false`.

## AG-UI events (wire = camelCase)
| Event | Required fields |
|---|---|
| RUN_STARTED / RUN_FINISHED | threadId, runId |
| RUN_ERROR | message (+ code) |
| TEXT_MESSAGE_START / CONTENT / END | messageId (+ role) / messageId, delta (non-empty) / messageId |
| TOOL_CALL_START / ARGS / END | toolCallId, toolCallName (+ parentMessageId) / toolCallId, delta / toolCallId |
| TOOL_CALL_RESULT | messageId, toolCallId, content (+ role "tool") |
| STATE_SNAPSHOT / STATE_DELTA | snapshot / delta (RFC 6902 ops) |
| MESSAGES_SNAPSHOT | messages |
| CUSTOM | name, value |
Order: RUN_STARTED first; START -> CONTENT/ARGS -> END; TOOL_CALL_RESULT after TOOL_CALL_END; nothing after RUN_ERROR.

Python: `from ag_ui.core import RunAgentInput, RunStartedEvent, ...`; `from ag_ui.encoder import EventEncoder`;
`EventEncoder(accept=...).encode(event)` -> `data: {...}\n\n`, media type `text/event-stream`.

## curl tests
```bash
B='{"threadId":"8f4b655f-a696-4b8d-9601-61b57fc00001","runId":"r1","state":{},"tools":[],"context":[],"forwardedProps":{},"messages":[{"id":"u1","role":"user","content":"hi"}]}'
curl -N -s -X POST http://127.0.0.1:4000/api/copilotkit/agent/opsi-investigator/run -H "Authorization: Bearer $T" -H 'Content-Type: application/json' -H 'Accept: text/event-stream' -d "$B"
curl -s http://127.0.0.1:4000/api/copilotkit/info -H "Authorization: Bearer $T" | jq .
```
