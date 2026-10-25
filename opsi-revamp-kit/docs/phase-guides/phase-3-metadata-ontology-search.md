# Phase 3 - metadata, ontology, search

## 3.1 OpenMetadata reachable with a read-only bot
In OpenMetadata: Settings -> Bots -> create `opsi-reader-bot` with a role allowing ViewAll on data assets (no edit),
copy its JWT -> `OPENMETADATA_BOT_TOKEN` (API) and an **ingestion bot** token for the metadata CLI.
```bash
curl -s -H "Authorization: Bearer $OPENMETADATA_BOT_TOKEN" http://127.0.0.1:8585/api/v1/system/version
curl -s -H "Authorization: Bearer $OPENMETADATA_BOT_TOKEN" "http://127.0.0.1:8585/api/v1/search/query?q=*&index=table_search_index&size=1" | head -c 400
```

## 3.2 Catalogue the Opsi database (metadata only)
1. DBA: apply `database/migrations/0007_openmetadata_reader_optional.sql` (edit schema list first), create
   `om_ingest_svc` login in `om_catalog_reader` with `CONNECTION LIMIT 2` and `statement_timeout`.
2. Legal decision on the ingestion package (ADR-0018). If approved:
```bash
python3.12 -m venv /opt/om-ingest-venv
/opt/om-ingest-venv/bin/pip install "openmetadata-ingestion[postgres]==2.0.6.*"     # match the server version
sudo install -m 0600 /dev/null /etc/opsi/om-ingest.env && sudo vi /etc/opsi/om-ingest.env
#  OM_SERVICE_NAME=opsi_app_postgres  OM_PG_USER=om_ingest_svc  OM_PG_PASSWORD=...  OM_PG_HOSTPORT=<rds>:5432
#  OM_PG_DATABASE=opsi  OM_SCHEMA_INCLUDES_JSON=["public","opsi_chat","opsi_knowledge","opsi_ingest"]
#  OM_API_URL=http://127.0.0.1:8585/api  OM_INGESTION_BOT_JWT=...  OM_VERIFY_SSL=ignore (lab http) | validate
infrastructure/openmetadata/run_metadata_ingest.sh
```
3. Verify in the OM UI: service `opsi_app_postgres` with the schemas; assign **owners/teams/domains/tags** in OM
   (that is where ownership lives - Opsi reads it).
4. Schedule daily (systemd timer modelled on `opsi-ingest-status.timer`).

## 3.3 Ontology bootstrap
Sources of entities/edges, in order of reliability:
1. **Dynatrace Smartscape** (services, process groups, hosts, calls/runs_on) - export via the Entities API v2
   (`/api/v2/entities?entitySelector=type(SERVICE)&fields=+fromRelationships,+toRelationships`) or Grail
   `fetch dt.entity.service`; write a small loader that upserts `entities` (source_system `dynatrace`) and edges.
2. **OpenMetadata** tables/teams for `reads_from`/`writes_to`/`owned_by` (`external_catalog_fqn` + `catalog_xrefs`).
3. **Manual/runbooks** via `POST /api/v2/ontology/edges` (role `ontology_editor`).
Seed for demos: `database/samples/synthetic_seed.sql` (lab only).
Rules: close edges when facts stop being true (`/edges/{id}/close`), never delete history; agent edges need evidence.

## 3.4 Retrieval routes
Configure the API env (see `.env.example` "API modules: retrieval backends"):
- `exact_logs`: `SEARCH_ELASTIC_URL`, read-only `SEARCH_ELASTIC_API_KEY`, `SEARCH_ELASTIC_TENANT_INDEX_MAP_JSON`
  (each tenant -> its index patterns; all must match `SEARCH_ELASTIC_INDEX_ALLOWLIST`), field names.
- `metadata_search`: `OPENMETADATA_URL`, `OPENMETADATA_BOT_TOKEN`.
- `historical_incident_search`, `sql_aggregation`, `service_graph`: need the curated tables / ontology (Phase 2/3.3).
- `vector_knowledge`: later (migration 0006 + `OPSI_VECTOR_ENABLED` + `EMBEDDING_MODEL`).
Smoke each route from a Python shell inside the API environment (see [../handbook/FAQ.md](../handbook/FAQ.md#how-do-i-test-one-route-by-hand)).

## 3.5 Service scope mapping
Decide which roles see which services (`OPSI_ROLE_SERVICE_SCOPE_JSON`). Service ids must be the same identifiers
used in curated tables and ontology (`service_id` from the collectors; Dynatrace `SERVICE-...` or service names).
Pick one canonical form and document it - mismatches show up as "denied" or empty results.

## Exit criteria
Catalogue visible in OM with owners; ontology has real services/hosts/edges; each route returns cited results for
a known incident; scope rules tested with two users.
