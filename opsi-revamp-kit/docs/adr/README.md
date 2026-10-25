# Architecture Decision Records

Each ADR records one decision: context, the decision, consequences, rejected alternatives and how
to verify it still holds. Change a decision by adding a new ADR that supersedes the old one - do not
edit history.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-separate-revamp-repository.md) | Separate revamp repository; baseline + revamp clones; legacy push disabled | Accepted |
| [0002](0002-openmetadata-via-api-separate-stores.md) | OpenMetadata is the catalog, used only via its API, with its own DB and search cluster | Accepted |
| [0003](0003-opsi-owned-incident-graph.md) | Incident causality graph is Opsi-owned in PostgreSQL with provenance and time validity | Accepted |
| [0004](0004-copilotkit-v2-node-runtime-bridge.md) | CopilotKit V2 with a minimal Node runtime bridge to FastAPI (no direct browser-to-agent) | Accepted |
| [0005](0005-fastapi-agui-agent-server-owned-history.md) | FastAPI implements the AG-UI agent; server-owned history; frontend tools for UI actions | Accepted |
| [0006](0006-s3-bronze-parquet-curated-postgres.md) | Raw data to S3 Parquet; only a curated subset to PostgreSQL | Accepted |
| [0007](0007-grid-windows-ledger-outbox.md) | Grid-aligned windows, ledger, manifest commit marker, outbox-driven index stage | Accepted |
| [0008](0008-typed-search-router-budgets-citations.md) | Typed search routes as LLM tools, with budgets, scope checks and mandatory citations | Accepted |
| [0009](0009-portkey-bedrock-server-side.md) | All inference via Portkey -> Bedrock, server-side only, no model ids hard-coded | Accepted |
| [0010](0010-identity-from-token-rls.md) | Identity only from verified tokens; PostgreSQL RLS as defence in depth | Accepted |
| [0011](0011-content-free-telemetry.md) | OpenTelemetry with GenAI conventions and no prompt/response content | Accepted |
| [0012](0012-separate-search-clusters.md) | Catalog indices and operational indices in separate OpenSearch clusters | Accepted |
| [0013](0013-allowlisted-ui-actions-no-generated-code.md) | Allowlisted, schema-validated UI actions; declarative charts; no generated code | Accepted |
| [0014](0014-chat-persistence-in-opsi.md) | Chat persistence in Opsi PostgreSQL, not CopilotKit Intelligence | Accepted |
| [0015](0015-pgvector-curated-knowledge-only.md) | pgvector optional and only for curated documents | Accepted |
| [0016](0016-systemd-timers-over-cron.md) | Cron for the first lab runs, systemd timers for anything shared | Accepted |
| [0017](0017-pin-versions-verify-scripts.md) | Exact version pins + export-verification scripts for fast-moving vendors | Accepted |
| [0018](0018-openmetadata-ingestion-license-review.md) | OpenMetadata ingestion package needs legal review (Collate Community License) | Proposed |
| [0019](0019-voice-as-adapter.md) | Voice is an adapter over the same agent; text stays the universal path | Accepted |
| [0020](0020-mirrors-packages-selective-vendoring.md) | Private mirrors not forks; components as packages; selective vendoring with provenance; one clean product repo | Accepted |

## Template

```markdown
# ADR-NNNN: <decision in one line>
- Status: Proposed | Accepted | Superseded by ADR-XXXX
- Date: YYYY-MM-DD
- Deciders: <names/roles>

## Context
What forces are at play (requirements, constraints, facts with sources).

## Decision
What we do. Be specific enough that a reviewer can check compliance.

## Consequences
Positive, negative, follow-ups.

## Alternatives considered
Option - why not.

## Verification
Test, script or review step that shows the decision is still being followed.
```
