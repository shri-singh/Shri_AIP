# 04 - Ingestion correctness, completeness, backfills and scaling

## The question
"How do I know the collectors didn't lose or duplicate data, how do I backfill safely, and what changes when volume grows?"

## Short answer
Correctness comes from **deterministic windows + a ledger + a commit marker + idempotent ids**, not from luck. Prove
completeness by reconciling per-window counts against the source. Backfill in day-sized chunks with the `backfill`
command. When volume outgrows 5-minute batch pulls, move to push/streaming (Dynatrace/Elastic exports to Kinesis/MSK)
while keeping the same bronze contract.

## Guarantees and their limits

| Property | Mechanism | Limit |
|---|---|---|
| No silent truncation | caps -> `WindowTooLarge` -> split -> fail at min split | cap must be below vendor hard limits |
| No lost windows | watermark advances only over contiguous committed/skipped windows | data older than source retention when a window stays failed |
| No duplicates downstream | `event_uid` deterministic; curated upserts/replace | bronze keeps one copy per *run* (dedupe on read) |
| Late data | one final re-scan after N minutes | later than N -> backfill |
| Partial failures | manifest written last; index stage separate with outbox | orphan parts possible (ignored) |
| Restart safety | ledger `running` rows are re-processed | none |
| Mutable records (problems) | `record_version` + latest-observation upsert | intermediate states between scans unseen |

## Reconciliation (do this in the first weeks)
```bash
# Elastic: compare counts for one window
curl -s -H "Authorization: ApiKey $KEY" "$ELASTIC_URL/$PATTERN/_count" -H 'Content-Type: application/json' \
  -d '{"query":{"bool":{"filter":[{"range":{"@timestamp":{"gte":"2026-10-24T10:00:00Z","lt":"2026-10-24T10:05:00Z"}}}, <same filter as ELASTIC_QUERY_FILTER_JSON> ]}}}'
# vs manifest record_count + duplicate_count + quarantined_count for that window
```
For Grail use a notebook with the same DQL and timeframe and `| summarize count()`.
Differences: late indexing (wait for the final re-scan), filter mismatch, timestamp field mismatch, quarantine.

## Backfills
- Use `backfill --from --to` (grid-aligned); dry-run first; run per day; watch vendor quotas and Grail scan costs.
- Backfilled windows before the watermark don't move it; windows after it advance it only when contiguous.
- Problems API returns problems relevant to the timeframe - backfills re-observe open problems (harmless upserts).

## Choosing parameters
| Setting | Start | Raise when | Lower when |
|---|---|---|---|
| `INGEST_WINDOW_MINUTES` | 5 | many tiny windows / API call overhead | splits are frequent |
| `INGEST_LAG_SECONDS` | 120 | final re-scans keep finding records | freshness matters more |
| `INGEST_FINAL_RESCAN_AFTER_MINUTES` | 30 | source indexing delays are long | cost of re-scans too high (set 0) |
| `ELASTIC_MAX_DOCS_PER_WINDOW` | 200k | memory/time allow | windows take > 2 min |
| `DYNATRACE_GRAIL_MAX_RECORDS` | 50k | queries are fast | `RESULT_GONE`/timeouts |
| `INGEST_PART_MAX_ROWS` | 5000 | many small parts | memory pressure |

## Adding a source (checklist)
1. Read the API docs; get a read-only credential; capture 3+ real responses in a sandbox; redact; commit as fixtures.
2. Write `sources/<name>.py` implementing `fetch(window)` with pagination, `WindowTooLarge`, `request_with_retry`, a
   `FieldMap` and `window_semantics` (`event_time` vs `overlap_snapshot`).
3. Tests: pagination, 429, contract shape, cap -> split, normalisation (time/severity/service).
4. Register in `sources/__init__.py`; `check-config` + `--dry-run`; timer.

## Scaling path
1. Vertical: more windows per run, larger caps, parallel sources on separate timers (already independent).
2. Horizontal: PostgreSQL state backend + sources partitioned across hosts (one source per host; the ledger is per source).
3. Streaming: Dynatrace OpenPipeline/log forwarding or Elastic -> Kinesis Data Streams/MSK -> Firehose to S3 in the same
   `opsi.event.v1` layout (Firehose dynamic partitioning) + a consumer for curated tables. Keep manifests (or Iceberg tables)
   so completeness stays provable.
4. Lakehouse: convert bronze to Apache Iceberg (Glue catalog) for Athena/Spark with snapshot isolation.

## Verify
`python -m opsi_ingest status --hours 24` clean; reconciliation within tolerance; quarantine < 1 %; outbox dead = 0.
