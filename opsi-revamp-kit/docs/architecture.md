# Architecture - Opsi 3.0 observability intelligence workbench

Audience: engineers and reviewers. Diagrams are Mermaid (render on GitHub/GitLab or VS Code with a
Mermaid extension). Decisions are justified in [adr/](adr/README.md); threats in [threat-model.md](threat-model.md).

## 1. System context (C4 level 1)

```mermaid
flowchart LR
    SRE(["SRE / incident commander"]) -->|"browser, corporate SSO"| OPSI["Opsi 3.0 workbench"]
    ADMIN(["Opsi admin"]) --> OPSI
    OPSI -->|"read logs"| ELASTIC[("Existing Elasticsearch<br/>log cluster")]
    OPSI -->|"problems v2, Grail DQL"| DT["Dynatrace SaaS/Managed"]
    OPSI -->|"catalog REST / MCP"| OM["OpenMetadata 2.x catalog"]
    OPSI -->|"chat completions"| PK["Portkey gateway"]
    PK --> BR["Amazon Bedrock"]
    OPSI -->|"Parquet, attachments"| S3[("Amazon S3<br/>SSE-KMS")]
    OPSI -->|"OTLP"| OBS["Dynatrace / Elastic<br/>observability backend"]
    IDP["Corporate IdP - OIDC"] -->|"tokens"| OPSI
    BOI["Broadcom DX OI - future"] -.->|"stub"| OPSI
```

Out of scope: changing the existing Opsi production app, its database, NGINX routing or network policy.

## 2. Containers (C4 level 2)

```mermaid
flowchart TB
  subgraph Browser
    WEB["Existing Opsi React app<br/>+ chat-v2, metadata, incident-graph, reports<br/>CopilotKitProvider V2"]
  end
  subgraph HOST["Opsi EC2 host - private subnet"]
    NGX["NGINX<br/>TLS, routing, SSE without buffering"]
    RT["copilot-runtime<br/>Node, CopilotKit V2 runtime<br/>127.0.0.1:4000"]
    API["Existing FastAPI app<br/>+ revamp modules /api/v2/*<br/>AG-UI agent endpoint - loopback only"]
    COL["Collectors<br/>systemd timers<br/>bronze + index stages"]
    OTC["OTel Collector<br/>127.0.0.1:4317 and 4318"]
  end
  subgraph AWS["Data plane - AWS"]
    PG[("Aurora/RDS PostgreSQL<br/>Opsi app DB + opsi_chat,<br/>opsi_knowledge, opsi_ingest")]
    S3[("S3 bronze Parquet,<br/>quarantine, attachments")]
    OS[("OpenSearch - Opsi operational<br/>index opsi-incidents, optional")]
  end
  subgraph CAT["Catalog - separate host/project"]
    OMS["OpenMetadata server"]
    OMDB[("Dedicated PostgreSQL 15+<br/>OpenMetadata DB")]
    OMOS[("Dedicated OpenSearch 3.x<br/>catalog indices")]
  end
  ELASTIC[("Existing Elastic")]
  DT["Dynatrace"]
  PK["Portkey"]
  BR["Bedrock"]
  OBSB["Observability backend"]
  OMI["metadata CLI - scheduled"]
  WEB -->|"HTTPS /api/copilotkit - SSE"| NGX
  WEB -->|"HTTPS /api/v2/*"| NGX
  NGX --> RT
  NGX --> API
  RT -->|"AG-UI POST /api/v2/agents/id<br/>Authorization forwarded"| API
  API --> PG
  API -->|"presign"| S3
  API -->|"_search read-only"| ELASTIC
  API -->|"REST, bot token"| OMS
  API -->|"Portkey SDK"| PK
  PK --> BR
  COL -->|"PIT + search_after"| ELASTIC
  COL -->|"Problems v2, Grail"| DT
  COL -->|"Parquet + manifest"| S3
  COL -->|"curated upserts"| PG
  COL -->|"bulk curated docs"| OS
  OMS --> OMDB
  OMS --> OMOS
  OMI -->|"read-only role"| PG
  OMI --> OMS
  API -.->|"OTLP"| OTC
  RT -.-> OTC
  COL -.-> OTC
  OTC -->|"OTLP/HTTP, redacted"| OBSB
```

### Responsibilities (who owns what)

| Concern | Owner | Never |
|---|---|---|
| Catalog metadata: tables, columns, owners, domains, tags, data lineage | **OpenMetadata** (via its API) | write to OpenMetadata's DB; share its DB/schema/indices with Opsi |
| Operational knowledge: incidents, services, hosts, dependencies, evidence, hypotheses (time-scoped, with provenance) | **Opsi PostgreSQL** `opsi_knowledge` | assume OM lineage = incident causality |
| Raw operational events | **S3 bronze** (Parquet, immutable runs) | bulk-load into PostgreSQL |
| Curated subset (problems, error signatures, evidence samples) | `opsi_ingest` (+ optional OpenSearch `opsi-incidents`) | raw payloads |
| Chat threads, messages, citations, tool runs, approvals, feedback | `opsi_chat` (RLS) | CopilotKit Intelligence / browser storage as the system of record |
| Identity & authorization | Existing Opsi auth or OIDC validation in FastAPI | trust tenant/user from client body, AG-UI state or context |
| Model inference | Portkey -> Bedrock, server-side only | model keys in the browser; parallel model clients |
| Presentation & UI actions | CopilotKit V2 in React (frontend tools, HITL, renderers) | execute model-generated code/HTML; mutate records without approval |

## 3. Components inside the API (C4 level 3)

```mermaid
flowchart LR
  subgraph MOD["app.modules"]
    ID["identity<br/>OIDC or existing adapter<br/>Principal, RBAC"]
    AG["agents<br/>AG-UI endpoint, Orchestrator,<br/>ui_actions, approvals, state"]
    SR["search<br/>SearchRouter + 6 routes"]
    RAG["rag<br/>citations, prompt fencing"]
    LLM["llm<br/>PortkeyGateway"]
    CH["chat<br/>repository with RLS, attachments, REST"]
    CAT["catalog<br/>OpenMetadata client + proxy"]
    ONT["ontology<br/>repository + REST"]
    VO["voice<br/>Transcribe, Polly - feature flag"]
    SH["_shared<br/>settings, tenant_tx, audit,<br/>redaction, telemetry, container"]
  end
  ES[("Elastic")]
  PGI[("opsi_ingest")]
  PGV[("opsi_knowledge.documents")]
  AG --> ID
  AG --> SR
  AG --> RAG
  AG --> LLM
  AG --> CH
  SR --> CAT
  SR --> ONT
  SR -->|"exact_logs"| ES
  SR -->|"historical, sql_aggregation"| PGI
  SR -->|"vector_knowledge"| PGV
```

Route catalogue (tools the model can call; all read-only, validated, budgeted, cited):

| Route | Backend | Limits | Citation |
|---|---|---|---|
| `exact_logs` | existing Elasticsearch `_search` (index from tenant map, allowlisted) | 24 h window, 50 hits, no wildcard/fuzzy operators | `elastic://<index>/_doc/<id>` |
| `metadata_search` | OpenMetadata search / table-by-FQN / lineage | 10 entities, lineage depth <= 3 | `om://<type>/<fqn>` |
| `historical_incident_search` | `opsi_ingest.problems` FTS | 90 days, 20 rows | `dynatrace-problem://<id>` |
| `service_graph` | `opsi_knowledge.neighborhood()` | depth <= 3, 80 edges, scope-filtered | `ontology://edge/<id>` |
| `sql_aggregation` | named SQL templates only | 30 days, 200 rows | `sql://opsi_ingest/<template>?...` |
| `vector_knowledge` (optional) | pgvector HNSW | 8 docs, similarity floor | runbook `source_ref` |

## 4. Key flows

### 4.1 "Why is this incident happening?" (agent run)

```mermaid
sequenceDiagram
  autonumber
  participant B as Browser - CopilotKit V2
  participant N as NGINX
  participant R as copilot-runtime
  participant A as FastAPI agent
  participant DB as PostgreSQL with RLS
  participant T as Retrieval routes
  participant M as Portkey to Bedrock
  B->>N: POST /api/copilotkit/agent/opsi-investigator/run - Bearer token, RunAgentInput
  N->>R: proxy with buffering off
  R->>R: onRequest - auth header present, x-request-id, route and agent allowlist
  R->>A: POST /api/v2/agents/opsi-investigator - Authorization forwarded
  A->>A: validate JWT to Principal, check thread ownership
  A-->>B: RUN_STARTED, STATE_SNAPSHOT
  A->>DB: load history, accept only NEW user messages and pending tool results
  loop up to AGENT_MAX_LLM_TURNS
    A->>M: system prompt + fenced context + history + tool specs
    M-->>A: streamed text and tool calls
    A-->>B: TEXT_MESSAGE events, streamed
    A->>T: validated tool call - scope, budget, timeout
    T-->>A: items + citations
    A-->>B: TOOL_CALL_START, ARGS, END, RESULT, STATE_DELTA
  end
  A->>DB: persist messages, tool runs, evidence, state
  A-->>B: CUSTOM opsi.answer_check, RUN_FINISHED
```

### 4.2 UI action and human approval

1. Model calls `set_dashboard_filter` -> server validates args + scope -> streams TOOL_CALL_* (no result) -> run ends.
2. CopilotKit runs the registered `useFrontendTool` handler -> page listener applies the filter -> new run with the tool result.
3. For `draft_incident_update` the server first creates an `action_approvals` row; the HITL card calls
   `POST /api/v2/actions/{id}/decision` **with the user's own session**; only then does an executor run.

### 4.3 Ingestion

```mermaid
flowchart LR
  T["systemd timer every 5 min"] --> C["collect --source X"]
  C --> P["plan grid windows<br/>+ final re-scans"]
  P --> F["source.fetch window<br/>PIT, pages, Grail poll"]
  F -->|"WindowTooLarge"| SPLIT["split window recursively"]
  SPLIT --> F
  F --> NRM["normalize + redact<br/>quarantine bad rows"]
  NRM --> W["Parquet parts<br/>fixed schema, SHA-256"]
  W --> MF["_manifest.json<br/>commit marker"]
  MF --> L[("ledger + outbox<br/>same transaction")]
  L --> WM["advance watermark<br/>over contiguous windows"]
  T2["timer offset 2 min"] --> IX["index stage"]
  IX -->|"outbox"| RD["read manifest<br/>verify checksums"]
  RD --> PGS[("curated PostgreSQL")]
  RD --> OSS[("opsi-incidents index")]
  IX -->|"failure"| RETRY["backoff then dead-letter"]
```

### 4.4 Thread restore after re-login
Browser `GET /api/v2/chat/threads?...` -> select -> `GET /threads/{id}/messages` (AG-UI wire messages, evidence,
state) -> `agent.setMessages()` + `agent.setState()` -> `<CopilotChat threadId=...>`. The server re-reads history
from PostgreSQL on every run, so a tampered browser transcript cannot change what the model sees.

## 5. Network view

```mermaid
flowchart LR
  U["Corporate network / VPN"] -->|"443"| ALB["Internal ALB or NGINX 443"]
  subgraph VPC["VPC private subnets"]
    H["Opsi EC2<br/>NGINX to 127.0.0.1:4000 runtime<br/>127.0.0.1:8000 API, 127.0.0.1:4318 OTel"]
    RDS[("RDS / Aurora")]
    OSD[("OpenSearch domain")]
    VPCE["VPC endpoints<br/>S3, KMS, Secrets Manager, STS"]
    OMH["OpenMetadata host<br/>127.0.0.1:8585 behind proxy"]
    OMRDS[("OpenMetadata PostgreSQL")]
    OMOS2[("OpenMetadata OpenSearch")]
  end
  SAAS["Dynatrace, Portkey SaaS if used,<br/>Elastic Cloud if used"]
  ALB --> H
  H -->|"5432 TLS"| RDS
  H -->|"443"| OSD
  H -->|"443"| VPCE
  OMH -->|"5432 TLS"| OMRDS
  OMH -->|"443"| OMOS2
  H -->|"443 egress via proxy allowlist"| SAAS
```
Rules: no public IPs; security groups allow only listed ports from listed sources; Docker ports bound to
127.0.0.1 (Docker bypasses host firewalls); egress allowlisted by FQDN. *Bedrock is reached by Portkey -
from wherever Portkey runs (self-hosted gateway in the VPC is preferred for data residency).

## 6. Data model summary
- `opsi_ingest`: watermarks, window_ledger, outbox, runs, operator_actions (collector state) + problems,
  error_signature_windows, evidence_samples, window_index_state (curated).
- `opsi_chat`: folders, threads, messages, tags, thread_tags, attachments, agent_runs, tool_runs, evidence_refs,
  action_approvals, feedback. `opsi_audit.events` append-only.
- `opsi_knowledge`: entity_kinds, relation_types, entities, edges (valid_from/valid_to, confidence, provenance,
  evidence_ref), catalog_xrefs (OpenMetadata FQN/UUID), documents (pgvector, optional).
Details: [data-contracts.md](data-contracts.md) and `database/migrations/`.

## 7. Quality attributes and how they are met

| Attribute | Mechanism |
|---|---|
| Tenant isolation | Principal from token; `tenant_tx` sets `opsi.tenant_id`; RESTRICTIVE RLS; tests for cross-tenant/user denial |
| No data loss in ingestion | grid ledger, manifest commit marker, watermark over contiguous windows, outbox, final re-scan, split-not-truncate |
| Explainability | citations on every route result; `[cN]` validation; evidence persisted per message |
| Safety of actions | allowlisted UI actions, schema validation, scope checks, approvals with expiry/four-eyes, audit |
| Prompt-injection resistance | fenced untrusted data, server-owned history, tools cannot write, no code execution |
| Privacy | redaction at ingest and in API, content-free telemetry, collector redaction, no voice retention |
| Operability | systemd timers + OnFailure alerts, status/gap reports, runbooks, health script |
| Evolvability | contracts (event schema, route args, AG-UI), pinned versions, verify scripts, ADRs |

## 8. Growth path
Phase 1 lab -> Phase 2 hardening (SSO, RLS, backups) -> Phase 3 dedicated OpenSearch, trace correlation, vector
knowledge, agent canvas -> Phase 4 streaming ingestion (Kinesis/MSK), lakehouse (Iceberg on S3 + Athena), voice.
See [consultations/12-release-rollout-rollback.md](consultations/12-release-rollout-rollback.md).
