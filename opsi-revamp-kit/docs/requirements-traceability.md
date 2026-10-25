# Requirements traceability - master prompt -> kit

Status legend: **Done** = implemented + tested here; **Ready** = implemented, needs your environment to run;
**Template** = documented/scaffolded, needs completion with real identifiers; **Open** = blocked on information.

## Business outcomes

| # | Requirement | Kit artefacts | Tests / evidence | Status |
|---|---|---|---|---|
| B1 | Admin UI: connectors, settings, SMTP, users, SSO, teams, domains, access rules (reuse OpenMetadata selectively) | consultation 02 (UI reuse matrix), ADR-0002, `docs/reference/openmetadata-ui-*`; catalog proxy API | licence analysis of 113 OM UI deps | Template (UI pages to build in Opsi) |
| B2 | Metadata catalog via OpenMetadata API, not its DB | `catalog/openmetadata.py`, `catalog/router.py`, `metadata_search` route, `infrastructure/openmetadata/*`, migration 0007 | `test_metadata_search_against_mock_openmetadata` | Ready |
| B3 | Operational ontology with provenance, time-scoped links, catalog xrefs | migration 0004, `ontology/*`, `service_graph` route, seed | validator + `test_ontology_and_incident_store_on_seed_data` | Done |
| B4 | CopilotKit V2 UI: provider, sidebar/popup/portal, threads after login, folders/tags/search, attachments, charts, typed UI actions; future canvas | `apps/opsi-web/src/features/*`, chat API, attachments | tsc + V2 scan, API tests, E2E smoke | Ready (graft into Opsi) |
| B5 | RAG routing: exact logs, SQL, catalog graph, optional pgvector, rerank, citations, feedback | `search/*`, `rag/*`, feedback endpoint | `test_search_and_actions.py`, `test_agui_contract.py` | Done (rerank: see consultation 05) |
| B6 | Data foundation: bounded collectors Elastic/Problems v2/Grail/Broadcom stub; S3 Parquet; curated PG; optional OpenSearch | `services/ingestion/*`, migration 0002, OpenSearch template | 93 ingestion tests + integration | Done (Broadcom: Open - contract needed) |
| B7 | LLM: FastAPI -> Portkey -> Bedrock, env-based ids, no hard-coded keys | `llm/gateway.py`, ADR-0009, IAM template | `ScriptedLLM` contract tests | Ready (needs Portkey config) |
| B8 | Instrumentation: OTel + GenAI conventions, safe traces, configurable OTLP | `_shared/telemetry.py`, collector configs | `otelcol-contrib validate` | Ready |
| B9 | Voice: consent, Transcribe, Polly, text-first | `voice/*`, ADR-0019, voice-roadmap | router disabled by default | Template |

## Constraints

| Constraint | Where honoured |
|---|---|
| OpenMetadata != OpenStack | glossary, ADR-0002 (no OpenStack anywhere) |
| Verify release docs before committing API names | [verified-facts.md](verified-facts.md) (versions, sources, re-verify procedure) |
| Dev compose as lab example only, not production | lab override + prod template + `compose_safe.sh` |
| CopilotKit V2 only; `moduleResolution: bundler` | `apps/opsi-web/tsconfig.json`, V1 scanner |
| Supported V2 runtime/AG-UI bridge with SSE schema/tool results/state/errors/cancellation tests; no fake interfaces | `apps/copilot-runtime`, `tests/api/test_agui_contract.py`, `bridge.test.mjs`, `bridge_smoke.py` |
| OpenMetadata lineage != incident causality | ADR-0003 |
| Separate OM DB/schema; separate catalog vs ops indices | ADR-0002, ADR-0012, deployments |
| Apache/MIT preference, SPDX, notices, legal review | license-inventory, ADR-0018 |
| PHI/PII protection, no public endpoints, no secret logging, per-tenant authz/RLS | redaction, loopback binds, RLS, threat model |
| Starter is scaffold - repair, don't claim | gap-analysis.md |

## Phases

| Phase | Item | Artefact | Status |
|---|---|---|---|
| 0.1 | Inventory lockfiles, React, build, router, FastAPI, migrations, auth, proxy, integrations | `scripts/phase0/inventory_opsi.py`, `inventory_host.sh` | Ready (run on the real source) |
| 0.2 | OpenMetadata UI dependency graph + reuse matrix with licences | consultation 02, `docs/reference/` | Done (for 2.0.6) |
| 0.3 | CopilotKit V2 exports, Node/React/TS requirements, AG-UI bridge | verified-facts, verify scripts | Done |
| 0.4 | Dependency/licence/security matrix + decisions | license-inventory, threat-model, ADRs | Done |
| 1.1 | Two clones, new private remote, legacy read-only | `scripts/clone_repos.sh`, `workspace.py verify` (push protection) | Ready |
| 1.2 | Pin upstream SHAs, provenance | `scripts/fetch_upstreams.sh`, `scripts/repo/workspace.py`, `scripts/repo/vendor_component.py`, [repository-strategy.md](repository-strategy.md), ADR-0020 | Ready (tested: `tests/repo`) |
| 1.3 | compose config/up/ps/logs/down, matching versions, probes, no public ports | `scripts/compose_safe.sh`, compose files | Done (config validated) |
| 1.4 | No shared schema between Opsi and OM | ADR-0002 | Done |
| 2.1 | Elastic PIT/search_after, Problems page token, Grail execute/poll OAuth with caps/partitioning, Broadcom stub | `sources/*` | Done |
| 2.2 | S3 Parquet layout, metadata, checksum, classification, quarantine, retries | `sinks/bronze.py`, `objectstore.py` | Done |
| 2.3 | Separate bronze commit from SQL indexing; idempotent replay, duplicates, late arrivals, DLQ, audit metrics | `pipeline.py`, `state.py`, `cli status` | Done |
| 2.4 | Curated PG only; optional OpenSearch indexer | migration 0002, `sinks/*` | Done |
| 2.5 | S3 lifecycle/encryption via IAM; RDS backups/PITR; Parquet != backup | `infrastructure/aws/*`, runbooks | Template |
| 2.6 | Validate shapes, time zones, schema evolution, redaction, completeness with fixtures | tests + data-contracts | Done |
| 3.1 | OM ingestion of Opsi DB read-only, scoped credentials | migration 0007, `infrastructure/openmetadata/*` | Ready (legal review pending) |
| 3.2 | Canonical ids/xrefs OM <-> Opsi | `catalog_xrefs`, entities.external_catalog_* | Done (sync job: consultation 02) |
| 3.3 | Ontology tables with validity, confidence, provenance, classification; OM teams/domains by API | migration 0004 | Done |
| 3.4 | Router routes with validation, windows, RBAC, budgets, citations | `search/*` | Done |
| 3.5 | Elastic retained; no cross-cluster assumptions | ADR-0012, `ElasticReadClient` | Done |
| 4.1 | CopilotKitProvider nested in router; sidebar/popup/full page with verified props | `OpsiCopilotProvider.tsx`, `OpsiChatSurfaces.tsx` | Ready |
| 4.2 | Runtime->AG-UI bridge with SSE, tool results, cancellation, state, approvals, trace ids | runtime + orchestrator | Done |
| 4.3 | PG conversation store, restore on re-login, search, S3 attachments with scan/limits | migration 0003, chat module | Done |
| 4.4 | Allowlisted app state sent to FastAPI; never trust tenant from client | `useOpsiUiContext`, `context.py` | Done |
| 4.5 | Structured outputs chart_spec/incident_summary/evidence_link/suggested_action; no generated code | ChartSpec, ui_actions, citations, renderers | Done (incident_summary = draft_incident_update + citations) |
| 4.6 | Preserve Portkey pipeline; no client-side keys | ADR-0009 | Done |
| 4.7 | Agent canvas later | consultation 11 | Template |
| 5.1 | Instrument endpoints, collectors, retrieval, tools, Bedrock; redact | telemetry.py, spans in router/orchestrator | Ready |
| 5.2 | OTLP to approved backend; no debug exporter in prod | config.prod.yaml | Done |
| 5.3 | Voice stub/design, opt-in, no storage by default | voice module, roadmap | Template |

## Output sequence items
Architecture/assumptions/blockers -> [architecture.md](architecture.md), [gap-analysis.md](gap-analysis.md) "Still open".
Directory tree + ownership -> README + [commit-plan.md](commit-plan.md#code-ownership-suggested-codeowners). Commands -> runbooks/phase guides.
Manual setup list -> [phase-guides/README.md](phase-guides/README.md#manual-setup-checklist-things-only-humans-with-access-can-do). Commit plan + rollback -> [commit-plan.md](commit-plan.md).

## Blocking identifiers to collect (ask the owners)
Enterprise repo URL for `opsi-enterprise-revamp`; approved bucket name(s) + KMS key ARNs; IAM role names; IdP issuer,
audience, JWKS URL, group names; Dynatrace env URL, OAuth client (scopes), Grail bucket permissions; Elastic endpoint +
read API key + index patterns per tenant; Portkey base URL/provider slug/config + Bedrock model/profile ids; OpenMetadata
target release + DB/search endpoints; OTLP backend endpoint + token; EC2 instance ids/SGs; change-management process.
