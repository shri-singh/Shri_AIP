# 02 - OpenMetadata: deployment, ingestion, API integration, UI reuse

## The question
"How do we run OpenMetadata next to Opsi safely, get Opsi's schema into it, use ownership/lineage in answers, and
can we reuse its admin screens?"

## Short answer
Run OpenMetadata **2.0.x from release images** as its own stack with a **dedicated PostgreSQL >= 15** and a
**dedicated security-enabled OpenSearch 3.x** (or Elasticsearch 9.x). Catalogue Opsi's DB with the `metadata` CLI in
metadata-only mode using a REFERENCES-only role (pending licence review of the ingestion package). Opsi reads catalog
facts through the REST API with a read-only bot token, server-side. Build Opsi-native admin/catalog screens; link to the
OpenMetadata UI for deep catalog work rather than copying its components.

## Deployment options

| Option | Pros | Cons | Use for |
|---|---|---|---|
| Upstream **dev** compose + kit lab override | everything local, source build | heavy build, security disabled internally, fixed container names, not upgradable cleanly | lab exploration only |
| Upstream **quickstart** compose (release images) + override | fast start | bundles DB/search with weak defaults | lab / demo |
| **Release images + external RDS + managed OpenSearch** (kit template) | supportable, backups, security, upgrades via migrate step | more AWS setup | staging/prod |
| Kubernetes Helm (`openmetadata-helm-charts`) | standard for k8s shops | needs EKS | if Opsi moves to k8s |
| Collate SaaS | no ops | data leaves your boundary; licence/contract | only with approvals |

## 2.0 upgrade facts to plan around
Migrations rename/rewrite tables (no automated downgrade) -> snapshot first; reindex always recreates indices (plan a
window); ingestion images use Python 3.12; Suggestions API removed; announcements moved; sessions are DB-backed with
5 concurrent sessions per user by default; `search_after` must be sent as repeated query params.

## Ingesting Opsi's database (metadata only)
- Role: `om_catalog_reader` with `USAGE` + `REFERENCES` (migration 0007) - tables/columns visible, data not readable.
- Disable profiler, sample data, data quality, usage/lineage-from-query-logs (they need SELECT / `pg_read_all_stats`).
- Workflow YAML: `infrastructure/openmetadata/opsi-postgres-metadata.template.yaml` (fields per v2.0 docs; `type: PostgreSQL`).
- Run via `run_metadata_ingest.sh` daily; the script renders secrets into a 0600 temp file and deletes it.
- Licence: `openmetadata-ingestion` is Collate Community License -> legal sign-off (ADR-0018). Fallback: push metadata via
  REST with your own code (`PUT /api/v1/services/databaseServices`, `/databases`, `/databaseSchemas`, `/tables`).

## Using catalog facts in Opsi
- Search: `GET /api/v1/search/query?q=&index=table_search_index&from=0&size=10` -> owners, domains, tags, description.
- Entity: `GET /api/v1/tables/name/{fqn}?fields=owners,tags,domains,columns` (URL-encode the FQN).
- Lineage: `GET /api/v1/lineage/table/name/{fqn}?upstreamDepth=1&downstreamDepth=1` - **data** lineage only.
- Owners field: `owners` (list) since 1.5; the client also handles legacy `owner`.
- MCP: `{OM}/mcp` (Streamable HTTP; tools like `search_metadata`) - useful later if the agent should browse the catalog via
  MCP; parameter names vary by version, so the kit uses REST.
- Cross-references: `opsi_knowledge.entities.external_catalog_fqn` + `catalog_xrefs` (om id, fqn, version, synced at).
  A small nightly job can refresh `om_id/om_version` and flag FQNs that disappeared (sketch below).

```python
# xref refresh sketch (run with the API's Database + OpenMetadataClient)
for row in await conn.execute("SELECT entity_id, om_fqn FROM opsi_knowledge.catalog_xrefs WHERE om_entity_type='table'"):
    table = await om.get_table(row["om_fqn"])
    if table is None:   # renamed/deleted in the catalog
        log.warning("catalog FQN gone: %s", row["om_fqn"]); continue
    await conn.execute("UPDATE opsi_knowledge.catalog_xrefs SET om_id=%s, last_synced_at=now() WHERE entity_id=%s",
                       (table["id"], row["entity_id"]))
```

## Admin UI: reuse matrix (OpenMetadata 2.0.6 UI)
Facts: React 18, antd 4.24, react-router 7, @rjsf 5 (JSON-schema forms), reactflow 11, i18next 21, own auth providers
(MSAL/Okta/Auth0/oidc-client), zustand + react-query, 79 component directories.

| Need in Opsi | OM component area | Decision | Why |
|---|---|---|---|
| Connector/settings forms | connection forms driven by JSON Schema (`@rjsf`) + OM's `openmetadata-spec` schemas | **Adapt the pattern**: use `@rjsf/core` (Apache-2.0) with Opsi's own JSON Schemas for connector settings | reuse the idea and library, not antd-bound components |
| Users / teams / roles | `Settings`, team pages | **Link/wrap**: manage catalog teams in OM; Opsi users/roles come from IdP groups | single source of truth for identity is the IdP |
| SSO settings | `SettingsSso` | **Rebuild minimal** or keep in IdP | Opsi doesn't need runtime-editable SSO |
| Domains, glossary, tags | `Domain`, `Glossary`, `Classifications` | **Link** to OM UI; show read-only chips in Opsi | catalog-owned data |
| Lineage view | `Lineage` (reactflow 11) | **Rebuild** with @xyflow/react 12 for operational graph; link to OM for data lineage | different semantics + versions |
| Search bar | `GlobalSearchBar`, `Explore` | **Rebuild** small search calling `/api/v2/catalog/search` | avoid OM state/i18n coupling |
| SMTP/email settings | OM `Settings` (notifications) | **Rebuild** in Opsi (Opsi notifications) | Opsi-owned feature |
| Data quality incidents | `IncidentManager` | **Do not conflate** - DQ test incidents, not operational incidents | semantic mismatch |
Copying any file -> license-inventory section 3 + Apache NOTICE + "modified" marker.

## Pitfalls
- Never point Opsi at OM's tables; never share OM's DB with Opsi or logs.
- The dev compose's fixed `container_name`s: only one copy per Docker host.
- Bot tokens are long-lived JWTs - treat as secrets; rotate.
- Large reindex on a shared search cluster hurts neighbours (ADR-0012).

## Verify
`/api/v1/system/version`, catalog search returns owners, `metadata_search` route test against the real server,
`scripts/compose_safe.sh openmetadata config` passes.
