# Elasticsearch / OpenSearch

Set once: `ES=https://elastic.corp.example:9200; H="Authorization: ApiKey $ELASTIC_API_KEY"` (never echo the key).

```bash
curl -s -H "$H" $ES | jq '.version.number'                 # cluster major -> pick python client major
curl -s -H "$H" "$ES/_cat/indices/logs-*?v&s=index:desc&h=index,docs.count,store.size" | head
curl -s -H "$H" "$ES/_resolve/index/logs-*" | jq '.data_streams[].name' | head
curl -s -H "$H" "$ES/logs-*/_mapping/field/@timestamp,service.name,log.level,message" | jq 'to_entries[0].value.mappings'
# count one window (reconcile with the manifest)
curl -s -H "$H" -H 'Content-Type: application/json' "$ES/logs-*/_count" -d '{"query":{"range":{"@timestamp":{"gte":"2026-10-24T10:00:00Z","lt":"2026-10-24T10:05:00Z"}}}}'
# PIT by hand
PIT=$(curl -s -H "$H" -X POST "$ES/logs-*/_pit?keep_alive=1m" | jq -r .id)
curl -s -H "$H" -H 'Content-Type: application/json' "$ES/_search" -d "{\"size\":2,\"pit\":{\"id\":\"$PIT\",\"keep_alive\":\"1m\"},\"sort\":[{\"@timestamp\":\"asc\"},{\"_shard_doc\":\"asc\"}]}" | jq '.hits.hits[].sort'
curl -s -H "$H" -X DELETE "$ES/_pit" -H 'Content-Type: application/json' -d "{\"id\":\"$PIT\"}"
# what the API's exact_logs sends: see apps/opsi-api/app/modules/search/routes/exact_logs.py build_body()
```

## Least-privilege API key (ask Elastic admins; Kibana Dev Tools)
```json
POST /_security/api_key
{"name": "opsi-collector", "expiration": "90d",
 "role_descriptors": {"opsi_reader": {"indices": [{"names": ["logs-*"], "privileges": ["read", "view_index_metadata"]}]}}}
```
Invalidate on rotation: `DELETE /_security/api_key {"name": "opsi-collector"}` (or by id).

## OpenSearch (Opsi operational index)
```bash
OS=https://opsi-ops-search.corp.example; A="-u $OS_USER:$OS_PASS"
curl -s $A -X PUT "$OS/_index_template/opsi-incidents" -H 'Content-Type: application/json' -d @infrastructure/opensearch/opsi-incidents-template.json
curl -s $A "$OS/opsi-incidents/_count"
curl -s $A "$OS/opsi-incidents/_search?q=kind:error_signature&size=3" | jq '.hits.hits[]._source'
curl -s $A "$OS/_cluster/health" | jq '{status, number_of_nodes}'
```
Elastic and OpenSearch APIs diverged after 7.10 - don't assume cross-cluster search between them (ADR-0012).
