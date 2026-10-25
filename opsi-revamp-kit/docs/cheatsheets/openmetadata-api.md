# OpenMetadata API (2.0.x)

`OM=http://127.0.0.1:8585; H="Authorization: Bearer $OPENMETADATA_BOT_TOKEN"`. Swagger: `$OM/swagger.html`.

```bash
curl -s -H "$H" $OM/api/v1/system/version
curl -s $OM/healthcheck 2>/dev/null || curl -s http://127.0.0.1:8586/healthcheck
curl -s -H "$H" "$OM/api/v1/search/query?q=orders&index=table_search_index&from=0&size=5" | jq '.hits.hits[]._source | {fullyQualifiedName, owners: [.owners[]?.name], tags: [.tags[]?.tagFQN]}'
FQN=$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1], safe=""))' "opsi_app_postgres.opsi.public.orders")
curl -s -H "$H" "$OM/api/v1/tables/name/$FQN?fields=owners,tags,domains,columns" | jq '{name, owners, domains}'
curl -s -H "$H" "$OM/api/v1/lineage/table/name/$FQN?upstreamDepth=1&downstreamDepth=1" | jq '{nodes: [.nodes[].fullyQualifiedName]}'
curl -s -H "$H" "$OM/api/v1/teams?limit=10" | jq '.data[].name'
curl -s -H "$H" "$OM/api/v1/services/databaseServices?limit=10" | jq '.data[].name'
```
Search index names: `table_search_index`, `dashboard_search_index`, `pipeline_search_index`, `topic_search_index`,
`glossary_term_search_index` (verify after upgrades). 2.0: repeat `search_after` params; owners are a list.

## Bots and tokens
UI: Settings -> Bots -> create bot -> role (read-only for Opsi API; ingestion bot for the CLI) -> copy JWT.
Rotate by revoking/regenerating; update secrets; restart API.

## Metadata ingestion CLI
```bash
/opt/om-ingest-venv/bin/metadata --version
OM_INGEST_ENV=/etc/opsi/om-ingest.env infrastructure/openmetadata/run_metadata_ingest.sh
```
Version of `openmetadata-ingestion` must match the server minor (2.0.x <-> 2.0.x). Licence: Collate Community License (ADR-0018).

## MCP endpoint (optional)
`POST $OM/mcp` (Streamable HTTP, headers `Accept: application/json, text/event-stream`, bearer token/PAT); tools such as
`search_metadata`. Parameter names vary by version - list tools first (`tools/list`).
