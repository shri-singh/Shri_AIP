# Data contracts - events, storage layout, quality rules, citation lineage

Contracts are code-first; this document explains them. Source of truth:
`services/ingestion/opsi_ingest/contract.py`, `database/migrations/*.sql`, `apps/opsi-api/app/modules/search/contracts.py`,
`apps/opsi-api/app/modules/agents/ui_actions.py`, `apps/opsi-web/src/features/reports/chartSpec.ts`.

## 1. Bronze event `opsi.event.v1` (Parquet, one fixed Arrow schema)

| Column | Type | Null | Meaning / rule |
|---|---|---|---|
| schema_version | string | no | `opsi.event.v1` |
| tenant_id | string | no | from collector config (`OPSI_TENANT_ID`) |
| source | string | no | `elastic`, `dynatrace_problems`, `dynatrace_grail`, ... |
| dataset | string | no | `logs`, `problems`, `alarms` |
| origin_id | string | no | vendor id (`<index>/<_id>`, `problemId`) or `sha256:<redacted payload hash>` |
| event_uid | string | no | `sha256(tenant \x1f source \x1f dataset \x1f origin_id)` - stable across runs |
| record_version | string | no | first 32 hex of the redacted payload hash - changes when the record changes |
| event_time | timestamp(us, UTC) | no | parsed from the source field; **never defaulted to now** |
| ingest_time | timestamp(us, UTC) | no | collector clock |
| window_start / window_end | timestamp(us, UTC) | no | grid window `[start, end)` |
| run_id | string | no | `YYYYmmddTHHMMSSZ-<8hex>`, sortable |
| severity | string | no | `CRITICAL, ERROR, WARN, INFO, DEBUG, UNKNOWN` |
| severity_raw, status, service_id, host_id, trace_id, title | string | yes | mapped via per-source `FieldMap` |
| message | string | yes | redacted, <= `INGEST_MESSAGE_MAX_CHARS` |
| message_fingerprint | string | yes | 16 hex; ids/numbers/IPs/quotes masked before hashing (error signature) |
| classification | string | no | e.g. `internal-confidential` |
| source_ref | string | no | citation pointer (see section 5) |
| redaction_hits | int32 | no | number of redactions applied |
| payload_json | string | no | redacted vendor record, size-capped |
| payload_truncated | bool | no | true if capped |
| payload_sha256 | string | no | hash of `payload_json` as stored |

**Evolution**: additive nullable columns only within v1; renames/type changes -> `opsi.event.v2` written to a new
`dataset=` path, readers handle both. Never rewrite bronze in place.

### Field mappings (defaults; adjust per estate in the source class)

| Source | time | severity | service | message |
|---|---|---|---|---|
| Elastic | `ELASTIC_TIMESTAMP_FIELD`, `@timestamp` | `log.level`, `level`, `severity` | `service.name`, `kubernetes.labels.app` | `message`, `error.message` |
| Problems v2 | `startTime` (epoch ms) | `severityLevel` (AVAILABILITY->CRITICAL, ERROR, PERFORMANCE/RESOURCE_CONTENTION/CUSTOM_ALERT->WARN) | `rootCauseEntity.entityId.id`, `affectedEntities.0.entityId.id` | `title` |
| Grail logs | `timestamp` (ISO, ns) | `loglevel`, `status` | `dt.entity.service`, `service.name` | `content` |

## 2. Quarantine record (`quarantine-*.jsonl.gz`)
`{reason, detail, source_ref, origin_id, payload_json (redacted)}`; reasons are a closed vocabulary:
`timestamp_missing, timestamp_invalid, timestamp_naive, origin_id_missing, payload_not_object, event_outside_window, normalization_error`.
`event_outside_window` is expected occasionally at boundaries (the adjacent window picks it up); a high count means
clock or timezone problems at the source.

## 3. Storage layout (S3)

```
s3://<bucket>/raw/{source}/dataset={dataset}/dt=YYYY-MM-DD/window={start}_{end}/run={run_id}/part-00000.parquet
s3://<bucket>/raw/{source}/dataset={dataset}/dt=YYYY-MM-DD/window={start}_{end}/run={run_id}/_manifest.json
s3://<bucket>/quarantine/{source}/dataset={dataset}/dt=YYYY-MM-DD/window=.../run=.../quarantine-00000.jsonl.gz
```
Object metadata: `schema-version`, `record-count`, `sha256`, `run-id`, `classification`. Upload sets SSE and a SHA-256
checksum verified by S3.

### Manifest (commit marker)
```json
{"manifest_version": 1, "schema_version": "opsi.event.v1", "status": "committed",
 "tenant_id": "...", "source": "elastic", "dataset": "logs",
 "window_start": "2026-10-24T10:00:00Z", "window_end": "2026-10-24T10:05:00Z",
 "run_id": "20261024T100702Z-3f9c2a1b", "scan_kind": "primary|final_rescan|dry_run",
 "created_at": "...", "collector_version": "0.3.0", "classification": "internal-confidential",
 "record_count": 1234, "quarantined_count": 2, "duplicate_count": 5, "quarantine_reasons": {"timestamp_missing": 2},
 "splits": 0, "segments": ["[...)"],
 "parts": [{"key": ".../part-00000.parquet", "rows": 1234, "bytes": 98765, "sha256": "..."}],
 "quarantine": [{"key": "...", "rows": 2, "sha256": "..."}], "source_stats": {}}
```
Reader rules: a run folder is valid only with a committed manifest; verify part checksums; for a window, the newest
`run_id` wins; dedupe by `event_uid` keeping the highest `ingest_time`.

Athena sketch (partition projection on `dt`; read only committed runs via a manifest table or a nightly "latest run"
listing): see [cheatsheets/aws-cli.md](cheatsheets/aws-cli.md#athena-over-bronze).

## 4. Curated PostgreSQL (`opsi_ingest`)

| Table | Grain | Write semantics | Read by |
|---|---|---|---|
| `problems` | tenant x problem_id | upsert; keep row with latest `last_observed_at` | historical_incident_search, sql_aggregation |
| `error_signature_windows` | tenant x source x window x service x fingerprint | replace per window; older runs ignored (`window_index_state`) | sql_aggregation, hourly view |
| `evidence_samples` | tenant x event_uid | insert-ignore; <= N per signature per window | citations to exact lines |
| `window_index_state` | tenant x source x dataset x window | newest run id applied | guard |

Quality rules enforced: `event_count > 0`, CHECKs on statuses, non-null evidence refs, RLS on all tenant tables.

## 5. Citation lineage

```
answer text "[c3]"  ->  opsi_chat.evidence_refs (thread, citation_key=c3, source_type, source_ref, snippet, url, message_id)
                         -> source_ref resolves to:
   elastic://<index>/_doc/<id>                     exact log line in the existing cluster
   grail://logs?timestamp=<iso>                    Grail record (+ payload hash in bronze)
   dynatrace-problem://<problemId>                 Dynatrace problem (UI deep link can be added)
   om://<entityType>/<fqn>  (+ url)                OpenMetadata entity
   ontology://edge/<uuid>                          opsi_knowledge.edges row (with its own source_ref/evidence_ref)
   sql://opsi_ingest/<template>?from=..&to=..      reproducible aggregate
   <runbook source_ref>                            curated document chunk
```
Each bronze row's `source_ref` + `event_uid` link curated rows and citations back to the archived raw record
(`s3://.../run=.../part-*.parquet`, filter `event_uid`).

## 6. API contracts

- **Route args** (pydantic, `extra="forbid"`): see `apps/opsi-api/app/modules/search/routes/*.py`. Time windows are
  UTC ISO-8601; maxima: exact_logs 24 h, historical 90 d, sql_aggregation 30 d.
- **Tool result payload** (TOOL_CALL_RESULT.content, JSON): `{route, items:[{..., cite:"c3"}], notes:[], truncated, total_hint, chart_hint}`
  or `{error: unknown_route|invalid_arguments|denied|timeout|upstream_unavailable|budget_exceeded|unavailable, message}`.
- **UI context** (`useAgentContext` description `opsi.ui_context`): `{page, incident_id?, service_id?, time_from?, time_to?,
  selected_panel_id?, selected_chart_id?, filters?}` <= 8 KB; unknown keys -> dropped.
- **ChartSpec**: `{kind: timeseries|category, title, x_label?, y_label?, unit?, series:[{name, type: line|bar|area|scatter,
  points:[[x, y|null], ...] <= 2000}] <= 10, citations:[cN]}`; labels must not contain `< > { } \` and backslashes.
- **State** (`STATE_SNAPSHOT`): `{phase, incident_id, service_id, time_from, time_to, evidence:[{key,title,source_type}],
  tools_used, budget:{calls,max_calls,cost,max_cost}, pending_approvals}`.
- **Restore** (`GET /api/v2/chat/threads/{id}/messages`): `{thread, messages:[AG-UI wire messages], evidence, state}`.

## 7. Data quality checks to run (and where)

| Check | Where | Alert when |
|---|---|---|
| Window completeness (no gaps, no failed windows) | `opsi_ingest status` daily timer | any failed window or gap > 0 |
| Quarantine ratio per source | manifests / status | > 1 % of records |
| Duplicate ratio | manifests | sudden increase (source replays) |
| Late data volume | final re-scan record delta | sustained growth -> increase lag |
| Curated freshness | `max(window_start)` in `error_signature_windows` | > 30 min behind |
| Outbox dead letters | `status` / `outbox_counts` | > 0 |
| Redaction hits | bronze `redaction_hits` | spikes (new secret leaking into logs - tell the owning team) |
