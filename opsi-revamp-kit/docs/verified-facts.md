# Verified facts (as of 2026-10-24) and how to re-verify them

Everything the kit depends on that could drift. Re-check before each phase; vendors move fast.
"Verified" means the fact was read from the installed package/type definitions, a registry, or the
vendor's reference docs on the date above - not remembered.

## Versions pinned by the kit

| Component | Version | Verified how | Re-verify |
|---|---|---|---|
| `@copilotkit/react-core` / `@copilotkit/runtime` | 1.79.1 | npm registry + type definitions in the tarball | `npm view @copilotkit/runtime version` |
| `@ag-ui/client` | **1.0.2** (must equal what the runtime depends on) | `npm ls @ag-ui/client`; 1.0.3 caused duplicate `AbstractAgent` types | `npm view @copilotkit/runtime@<v> dependencies` |
| `ag-ui-protocol` (Python) | 1.0.0 | wheel inspected (`ag_ui/core`, `ag_ui/encoder`) | `pip download ag-ui-protocol==X --no-deps` |
| OpenMetadata server | 2.0.6 (2026-10-21); 1.13.6 last 1.x | GitHub releases API | `curl -s https://api.github.com/repos/open-metadata/OpenMetadata/releases?per_page=5` |
| OpenMetadata minimums | PostgreSQL >= 15; OpenSearch 3.x (>= 3.0, 3.3 recommended) or Elasticsearch 9.x | docs v2.0.x deployment/minimum-requirements | docs for your exact version |
| `portkey-ai` (Python) | 2.3.4 | wheel inspected: ctor has `api_key, base_url, provider, config, trace_id, metadata, request_timeout, aws_*` | `pip download portkey-ai==X` and read `api_resources/client.py` |
| FastAPI / pydantic / Starlette | 0.162.0 / 2.14.1 / 1.9.0 | tests ran | `pip freeze` |
| pyarrow | 26.0.0 (**requires Python >= 3.11**) | PyPI `requires_python` | `pip index versions pyarrow` |
| elasticsearch-py | 8.19.3 in tests | Elastic docs: 9.x client is NOT compatible with 8.x servers | `curl -s -H "Authorization: ApiKey ..." $ELASTIC_URL` -> `version.number` |
| otelcol-contrib | 0.137.0 | `validate` ran on both configs | `otelcol-contrib validate --config=...` |
| Docker Compose | >= 2.24 needed (`!reset` / `!override`); tested with v5.3.1 | `docker compose config` ran | `docker compose version` |

## Facts that shaped the design (each one is a trap if forgotten)

### CopilotKit V2
- React V2 API lives at `@copilotkit/react-core/v2`: `CopilotKitProvider` (props incl. `runtimeUrl`, `agentId`,
  `headers` (record or async builder), `credentials`, `onError`, `enableInspector`), `CopilotChat`, `CopilotSidebar`,
  `CopilotPopup`; hooks `useAgent`, `useAgentContext`, `useFrontendTool(s)`, `useHumanInTheLoop`, `useRenderTool`,
  `useDefaultRenderTool`, `useInterrupt`, `useThreads`. Styles: `@copilotkit/react-core/v2/styles.css`.
  `<CopilotKit>` is the V1 **compatibility wrapper** - not the V2 baseline.
- `useThreads` / `CopilotThreadsDrawer` are tied to **CopilotKit Intelligence** (hosted). The kit keeps thread history in
  Opsi PostgreSQL instead and restores with `agent.setMessages()` / `agent.setState()` (verified on `AbstractAgent`).
- Runtime V2: `CopilotRuntime({agents, forwardHeaders, sseKeepAliveIntervalSeconds})`, `createCopilotRuntimeHandler({runtime,
  basePath, mode, hooks})`, Node adapter `createCopilotNodeHandler` from `@copilotkit/runtime/v2/node`. Routes (multi-route
  mode): `POST {base}/agent/{id}/run` (body = AG-UI `RunAgentInput`), `GET {base}/info`, plus connect/stop/threads/... .
- The runtime forwards `authorization` and `x-*` headers to agents by default; `forwardHeaders: {allow: [...]}` switches to
  allowlist mode (default denylist then no longer applies).
- The runtime has a **telemetry client** (Segment) -> set `COPILOTKIT_TELEMETRY_DISABLED=true` / `DO_NOT_TRACK=1` **before** the
  module loads. `@copilotkit/react-core` depends on `@scarf/scarf` (install-time ping) -> `SCARF_ANALYTICS=false` for npm.
- On an agent HTTP error the runtime streams `RUN_ERROR` whose message contains the upstream response body; on handler
  errors its default 500 body contains `error.message`. The kit masks both (sanitizing `fetch`, `onError` hook) - tested.
- Connecting the browser directly to an agent (`agents__unsafe_dev_only` / `selfManagedAgents`) is dev-only.

### AG-UI protocol (1.0)
- Event types used: `RUN_STARTED/FINISHED/ERROR`, `TEXT_MESSAGE_START/CONTENT/END`, `TOOL_CALL_START/ARGS/END/RESULT`,
  `STATE_SNAPSHOT/DELTA` (RFC 6902 JSON Patch), `MESSAGES_SNAPSHOT`, `CUSTOM`. `THINKING_*` was replaced by `REASONING_*` in 1.0.
- Wire format is camelCase; Python models accept snake_case attributes. `RunAgentInput` = `threadId, runId, state, messages,
  tools, context, forwardedProps, resume?, parentRunId?`. `TextMessageContent.delta` must be non-empty.
- `EventEncoder` (Python 1.0.0) always emits SSE `data: <json>\n\n` with `text/event-stream`.

### Dynatrace
- Grail: `POST /platform/storage/query/v1/query:execute` (200 = done, 202 = poll), `GET query:poll?request-token=&request-timeout-milliseconds=`,
  `POST query:cancel`. States: NOT_STARTED, RUNNING, SUCCEEDED, RESULT_GONE, CANCELLED, FAILED. Results kept ~1 minute after
  completion. Body fields incl. `defaultTimeframeStart/End`, `maxResultRecords`, `requestTimeoutMilliseconds`,
  `defaultScanLimitGbytes`, `timezone`, `locale`. Exceeding `maxResultRecords` adds a notification (not an error).
- Grail auth is a platform token or OAuth2 client-credentials bearer (`https://sso.dynatrace.com/sso/oauth2/token`, typical
  `expires_in` 300 s). A static bearer in `.env` (starter design) expires within minutes. Classic `Api-Token` works only
  for the classic API (Problems v2).
- Problems v2: `GET /api/v2/problems`, `pageSize` <= 500, follow-up pages send **only** `nextPageKey`.

### OpenMetadata
- Server repo is Apache-2.0, but the **`openmetadata-ingestion` Python package (and `ingestion/` dir) is under the Collate
  Community License Agreement 1.0** (use allowed; "Excluded Purpose" = competing SaaS; notices required). Legal review needed.
- 2.0 breaking changes: Suggestions API removed, announcements moved to `/v1/announcements`, sessions DB-backed (default
  5 per user), reindex always recreates indices, ingestion images on Python 3.12, **no automated downgrade** after migration.
- The 2.0.6 *dev* compose (`docker/development/docker-compose-postgres.yml`) uses OpenSearch 3.4.0 with
  `plugins.security.disabled=true`, publishes 5432/9200/9300/8585/8586/**5005 (JDWP)**/8080 on all interfaces, fixed passwords
  and `FERNET_KEY`, and fixed `container_name`s (so `-p` does not isolate two copies). The quickstart compose uses Elasticsearch 9.3.0.
- OpenMetadata's UI (2.0.6) is React 18 + antd 4.24 + react-router 7 + @rjsf 5 + reactflow 11 + i18next; 113 runtime deps
  (licences in [reference/openmetadata-ui-2.0.6-dependency-licenses.tsv](reference/openmetadata-ui-2.0.6-dependency-licenses.tsv)).
- An MCP server exists at `{OM}/mcp` (Streamable HTTP; tools such as `search_metadata`); parameter names differ between versions.

### Platform behaviours verified by tests in this kit
- psycopg server-side prepared statements break behind PgBouncer/RDS Proxy in transaction mode -> `prepare_threshold=None`.
- PostgreSQL superusers and BYPASSRLS roles ignore RLS even with `FORCE ROW LEVEL SECURITY`.
- boto3 may produce SigV2 presigned URLs unless `signature_version="s3v4"` - SigV2 fails for SSE-KMS objects.
- Docker Compose override files **append** `ports:`; use `!reset []` / `!override`.
- psycopg async cannot use the Windows Proactor event loop (irrelevant on Linux EC2).
- OpenLLMetry instrumentations capture prompt/completion content **by default** (`TRACELOOP_TRACE_CONTENT=false` to stop).

## How to re-verify an API name yourself (no AI needed)

```bash
# What does a JS package export?
npm pack @copilotkit/runtime@1.79.1 && tar -xzf copilotkit-runtime-1.79.1.tgz
grep -n "export {" package/dist/v2/index.d.mts | head
# Which props does a component take?
grep -n -A40 "interface CopilotKitProviderProps" package/dist/*.d.mts
# What does a Python package contain?
pip download ag-ui-protocol==1.0.0 --no-deps -d /tmp/w && python3 -m zipfile -l /tmp/w/*.whl
python3 -c "import ag_ui.core as c; print([n for n in dir(c) if n.endswith('Event')])"
```
See also [handbook/SELF_HELP_WITHOUT_AI.md](handbook/SELF_HELP_WITHOUT_AI.md).

## Sources consulted
- https://docs.copilotkit.ai/reference/v2 ; unpkg `@copilotkit/runtime@1.66.1/files/skills/runtime/references/wiring-pydantic-ai.md`
- https://docs.ag-ui.com/concepts/events ; https://docs.ag-ui.com/quickstart/server
- https://docs.dynatrace.com/docs/dynatrace-api/platform-api/platform-storage-query-v1/query-execute-post ;
  https://developer.dynatrace.com/develop/platform-services/services/grail-service/ ;
  https://docs.dynatrace.com/docs/manage/identity-access-management/access-tokens-and-oauth-clients/oauth-clients
- https://docs.open-metadata.org/v2.0.x/deployment/upgrade/breaking-changes/overview ;
  https://docs.open-metadata.org/v2.0.x/deployment/minimum-requirements ; https://docs.open-metadata.org/v2.0.x/connectors/database/postgres/yaml ;
  https://docs.open-metadata.org/v2.0.x/how-to-guides/mcp/connect
- https://portkey.ai/docs/api-reference/sdk/python ; https://portkey.ai/docs/support/upgrade-to-model-catalog
- https://www.elastic.co/docs/reference/elasticsearch/clients/python (compatibility table)
- OpenLLMetry Bedrock instrumentation (PyPI `opentelemetry-instrumentation-bedrock`) - content capture default
