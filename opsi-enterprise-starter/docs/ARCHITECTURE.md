# Opsi 3.0 solution architecture

## Logical services
```
Browser React shell (SSO, dashboards, incident explorer, metadata pages)
  + CopilotKit v2: CopilotKitProvider / CopilotSidebar / Popup / chat portal
       |  AG-UI actions & state; user authenticated at the gateway
       v
  Copilot runtime/proxy (Node as required by CopilotKit's current V2 contract)
       | AG-UI SSE
       v
  Existing Python FastAPI API + agent adapter
       |---- PostgreSQL (Opsi app, chat, snapshots, ontology edges; pgvector optional)
       |---- OpenMetadata REST/MCP (entities, schema/column lineage, teams/domains)
       |---- OpenSearch (catalog search; separate operational indexes/clusters when needed)
       |---- Elastic / Dynatrace live adapters; optional Broadcom OI
       |---- S3 Bronze Parquet + evidence objects; Silver/Gold normalization
       |---- RAG: exact/keyword -> SQL -> optional vector -> rerank -> evidence/citations
       +---- Portkey policy/gateway -> Amazon Bedrock LLM
                  ^
                  | OpenTelemetry + OpenLLMetry traces (redacted)

EC2 Python collectors (cron initially)
  Elastic scan / Dynatrace Problems v2 / Dynatrace Grail DQL / future Broadcom adapter
       -> bounded window + retry + state checkpoint
       -> S3 immutable-ish Bronze Parquet (raw JSON preserved)
       -> Opsi curated PostgreSQL incident/event index (small bounded subset)
       -> optional OpenSearch separate operational indexes
       -> curated incident summaries and long-lived knowledge / pgvector
```

## Domain boundaries
- **OpenMetadata** is source of truth for *catalog metadata* (assets, schema, owners, domains, data lineage). Use official APIs; do not write directly to its application database.
- **Opsi PostgreSQL** is source of truth for *application state and operational ontology*: Incident--affects-->Service, Service--runs_on-->Host, Evidence--supports-->Hypothesis, Thread--investigates-->Incident, etc. Link `external_catalog_id` to OpenMetadata when an entity is cataloged there. Typed time-bounded edges require provenance and access scope. Do not assume OpenMetadata native lineage models RCA causality.
- **OpenSearch** is an asynchronous index of catalog/searchable operational documents. Keep catalog and high-volume logs in **separate indexes; prefer separate clusters at enterprise scale**. No claim of direct cross-cluster query compatibility with Elasticsearch.
- **PostgreSQL pgvector** indexes select runbooks, RCA summaries, incident descriptions. Do not embed every raw log line.
- **S3** is the durable evidence/archive layer. Store original records, UTC timestamps, source identifiers, schema version, capture time, and object checksums; enforce retention and privacy classification. Aggregated event data to PostgreSQL only, not all 6+ TB.
- **CopilotKit V2** is presentation/AG-UI integration, not the owner of authentication, source permissions or incidents. UI app state is a hint; server resolves permissions.
- **Bedrock via Portkey** provides inference; no production mutation may occur from unverified LLM text. All actions are allowlisted and authorized server-side.

## Independent data flows
1. `Elastic/Dynatrace -> EC2 collector -> S3 Bronze -> transforms -> optional PG/OpenSearch`.
2. `Opsi PostgreSQL -> read-only catalog ingestion -> OpenMetadata; catalog indexed by OpenSearch`.
3. `React question + allowlisted UI context -> authorized FastAPI plan -> exact SQL/Elastic/OpenSearch + OpenMetadata API -> RAG -> Bedrock -> cited AG-UI events`.
4. `React approval -> FastAPI action service -> audit -> allowed incident changes`.
5. `OTEL/OpenLLMetry -> OTLP collector -> existing observability backend` (not blindly mirrored back into model prompts).
6. `Future microphone -> STT -> Opsi conversational stream -> TTS` via an independently permissioned voice adapter.

## Storage model
- `opsi_ingest`: normalized operational events, source checkpoints kept at worker initially. Eventually move watermarks + outbox into durable store.
- `opsi_knowledge`: catalog references, `entities`, `edges`, annotations, provenance.
- `opsi_chat`: folders, threads, tags, messages, attachments, message evidence, actions.
- OpenMetadata dedicated PostgreSQL database / DB role; separate catalog indexes in OpenSearch.

## Search route
- exact time/error/service: query live Elastic, normalized PG, or OpenSearch.
- historical incident similarity: PG full-text + pgvector + selective OpenSearch BM25.
- ownership/schema/lineage: OpenMetadata catalog REST/MCP; operational incident graph from Opsi.
- dashboard/trends: SQL aggregate or OpenSearch aggregation; render ECharts/Perses.
- always include tenant, service permission, time range, query limits, citation source identifiers.

## Growth strategy
- Phase 1: existing Opsi + OpenMetadata lab + CopilotKit V2 single app + S3 collectors.
- Phase 2: harden SSO/RBAC, event normalization, read/write approval, backup, recovery.
- Phase 3: dedicated OpenSearch operational search, trace correlation, vector knowledge, agent canvas.
- Phase 4: streaming ingestion, lakehouse, scalable orchestration, speech interaction.
