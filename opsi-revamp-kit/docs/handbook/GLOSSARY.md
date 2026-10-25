# Glossary

| Term | Meaning in this project |
|---|---|
| **AG-UI** | Agent-User Interaction protocol: typed events (RUN_STARTED, TEXT_MESSAGE_*, TOOL_CALL_*, STATE_*...) streamed over SSE between agents and UIs. Python package `ag-ui-protocol`, JS `@ag-ui/client`/`@ag-ui/core`. |
| **AbstractAgent / HttpAgent** | AG-UI client classes; `HttpAgent` POSTs `RunAgentInput` to a URL and parses the event stream. Used inside the CopilotKit runtime. |
| **Approval (HITL)** | Human-in-the-loop decision on an agent-proposed action, stored in `opsi_chat.action_approvals`, decided via REST. |
| **Bronze** | Raw-but-normalised, redacted events in S3 Parquet (`opsi.event.v1`), one folder per window run. |
| **Budget (run budget)** | Per-agent-run limits on tool calls, cost units, seconds and LLM turns. |
| **Citation key (`cN`)** | Thread-unique identifier of a piece of evidence; answers reference it as `[cN]`. |
| **CopilotKit V2** | The `@copilotkit/react-core/v2` API (CopilotKitProvider, CopilotChat/Sidebar/Popup, hooks) and `@copilotkit/runtime/v2`. |
| **CopilotKit Intelligence** | CopilotKit's hosted/licensed thread & memory service - not used by Opsi. |
| **copilot-runtime** | Opsi's minimal Node service running the CopilotKit V2 runtime, bridging the browser to the FastAPI agent. |
| **Curated subset** | Small, query-friendly PostgreSQL tables derived from bronze (problems, error signatures, evidence samples). |
| **DQL** | Dynatrace Query Language used with Grail (`fetch logs | filter ...`). |
| **Error signature / fingerprint** | Hash of a log message with variable parts masked; groups "the same error". |
| **event_uid** | Deterministic id `sha256(tenant, source, dataset, origin_id)`; dedupe key. |
| **Final re-scan** | One extra collection of a window after the late-data horizon. |
| **FQN** | OpenMetadata fully qualified name, e.g. `service.database.schema.table`. |
| **Frontend tool** | Tool executed in the browser (UI action) registered with `useFrontendTool`. |
| **Grail** | Dynatrace's data lakehouse; queried via the platform Storage Query API. |
| **Grid window** | Fixed time slice aligned to multiples of `INGEST_WINDOW_MINUTES` from the Unix epoch. |
| **Index stage** | Second ingestion stage that applies committed windows to curated sinks via the outbox. |
| **Inference profile** | Bedrock identifier routing a model across regions; often required instead of a model id. |
| **Ledger** | `window_ledger` table: status, attempts, scans, counts and manifest per window. |
| **Manifest** | `_manifest.json` listing parts + checksums; its presence commits a window run. |
| **MCP** | Model Context Protocol; OpenMetadata exposes an MCP server at `/mcp`. |
| **Mirror (upstream mirror)** | Private corporate copy of a public upstream repo (branches + tags), written only by a sync job. Used instead of a GitHub fork. See repository-strategy.md. |
| **OpenMetadata** | Open-source data catalog (Apache-2.0 server) used for metadata, ownership, lineage. **Not OpenStack.** |
| **OpenLLMetry** | Traceloop's OpenTelemetry instrumentations for LLM SDKs (capture content by default - disabled here). |
| **Outbox** | Table of committed windows waiting for the index stage; decouples bronze from PostgreSQL. |
| **PIT / search_after** | Elasticsearch point-in-time + cursor pagination with a total sort order. |
| **PGlite** | PostgreSQL compiled to WebAssembly; used only for local SQL validation/tests. |
| **Portkey** | AI gateway between Opsi and Bedrock (routing, keys, guardrails, logs). |
| **Principal** | Authenticated caller (user, tenant, roles, service scope) - only from verified identity. |
| **Problems v2** | Dynatrace classic Environment API endpoint `/api/v2/problems`. |
| **Quarantine** | Rows rejected by normalisation, stored with reason codes in S3. |
| **RLS** | PostgreSQL row-level security; enforces tenant/owner isolation in the database. |
| **Route** | Typed, read-only retrieval tool (exact_logs, metadata_search, ...). |
| **Runtime (CopilotKit)** | Server component that the React provider talks to; hosts agents. |
| **Service scope** | Set of services a role may query/act on; `None` = unrestricted. |
| **SSE** | Server-Sent Events, `text/event-stream`, used for AG-UI streaming. |
| **tenant_tx** | DB helper that opens a transaction and sets `opsi.tenant_id`/`opsi.user_id` for RLS. |
| **Upstream study clone** | Read-only, partial clone of an upstream at a pinned tag in `~/workspaces/upstream/`; push disabled by `workspace.py`. |
| **Vendoring (selective)** | Copying chosen upstream files into `third_party/` with provenance (`VENDORED.json`: URL, tag, commit, SHA-256, licence, approval) via `vendor_component.py`. |
| **Workspace manifest** | `~/workspaces/workspace.json`: every repo on the box with its role (product/readonly/upstream/reference); checked by `workspace.py verify`. |
| **UI context** | Allowlisted snapshot of the user's screen sent via `useAgentContext` - a hint, never identity. |
| **Watermark (`committed_until`)** | End of the last contiguous committed window per source/dataset. |
