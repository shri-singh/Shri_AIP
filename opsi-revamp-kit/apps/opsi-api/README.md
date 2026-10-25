# opsi-api revamp modules (FastAPI)

Drop-in modules for the **existing** Opsi FastAPI app. Nothing here replaces Opsi's routes; everything mounts under
`/api/v2/*` and is switched on by one call.

```
app/
  main_example.py            how to graft + a runnable in-memory LAB app (scripted model)
  modules/
    install.py               install_revamp(app, container), build_services(settings), build_memory_services(...)
    _shared/                 settings, db (tenant_tx/RLS), audit, redaction (synced copy), telemetry, errors, container
    identity/                Principal, OIDC validation, existing-auth adapter hook, require(permission)
    chat/                    models, repository (memory + PostgreSQL), attachments (S3 presign + GuardDuty), REST router
    agents/                  AG-UI endpoint, orchestrator, UI action catalogue, approvals (REST), state, context
    search/                  contracts, SearchRouter, clients, stores, routes/{exact_logs, metadata_search,
                             historical_incidents, service_graph, sql_aggregation, vector_knowledge}
    rag/                     citations registry, prompt + untrusted-data fencing
    llm/                     LLMGateway, PortkeyGateway, ScriptedLLM (tests/lab)
    catalog/                 OpenMetadata REST client + read-only proxy router
    ontology/                repository (memory + PostgreSQL) + router
    voice/                   Transcribe/Polly service + router (disabled by default)
```

## Endpoints

| Method + path | Permission | Purpose |
|---|---|---|
| `POST /api/v2/agents/{agent_id}` | chat:use | AG-UI agent (runtime only; never public) |
| `GET/POST /api/v2/chat/threads`, `GET/PATCH /threads/{id}` | chat:use (+chat:share to share) | threads |
| `GET /api/v2/chat/threads/{id}/messages` | chat:use | restore (AG-UI messages + evidence + state) |
| `GET /threads/{id}/evidence`, `PUT /threads/{id}/tags` | chat:use | citations, tags |
| `GET/POST/DELETE /api/v2/chat/folders`, `GET/POST /api/v2/chat/tags`, `GET /api/v2/chat/search?q=` | chat:use | organisation, full-text search |
| `POST /threads/{id}/attachments`, `POST /attachments/{id}/finalize`, `GET /attachments/{id}/download` | attachment:upload / chat:use | files |
| `POST /threads/{id}/feedback` | feedback:write | thumbs + reason |
| `GET /api/v2/actions/{id}`, `POST /api/v2/actions/{id}/decision` | chat:use / action:approve | approvals |
| `GET /api/v2/catalog/search`, `/tables/{fqn}`, `/lineage/table/{fqn}` | catalog:read | OpenMetadata proxy |
| `GET /api/v2/ontology/entities/{key}/neighborhood`, `POST /edges`, `POST /edges/{id}/close` | ontology:read / ontology:write | graph |
| `POST /api/v2/voice/transcribe`, `/synthesize` | chat:use | voice (404 unless enabled) |
| `GET /api/v2/healthz` | - (restrict at NGINX) | health |

## Grafting steps
1. Copy `app/modules` into the Opsi API package. If Opsi's package isn't called `app`, keep the folder as
   `<opsi_pkg>/modules` - all imports inside are relative.
2. Merge `requirements/api.txt`; run Opsi's tests.
3. App factory / lifespan:
```python
import os
from contextlib import asynccontextmanager
from <opsi_pkg>.modules._shared.settings import get_settings
from <opsi_pkg>.modules.install import build_services, install_revamp
from <opsi_pkg>.modules.identity.deps import set_existing_auth_adapter

@asynccontextmanager
async def lifespan(app):
    container = None
    if os.getenv("OPSI_REVAMP_ENABLED") == "true":
        set_existing_auth_adapter(opsi_adapter)          # if OPSI_AUTH_MODE=existing (consultation 07)
        container = await build_services(get_settings())
        install_revamp(app, container, tracing=True)
    yield
    if container:
        await container.extras["db"].close()
```
   FastAPI routes added during lifespan startup work; if Opsi builds routers before startup, call `install_revamp` right
   after app creation and open the DB pool in the lifespan instead (`container.extras["db"].open()`).
4. Env: see `.env.example` "API modules" sections. DB login must be a member of `opsi_app`.
5. Tests: copy `tests/api` and adjust import roots; `pytest tests/api`.

## Lab app (no DB, no AWS, scripted model)
```bash
cd apps/opsi-api && OPSI_ENV=lab OPSI_AUTH_MODE=dev uvicorn app.main_example:lab_app --factory --host 127.0.0.1 --port 8000
```

## Extending
New route -> FAQ "How do I add a new retrieval route?"; new UI action -> FAQ "How do I add a UI action?";
real approval executor -> FAQ "How do I make draft_incident_update actually save?".
