# 13 - Capacity, sizing and cost

## The question
"What will this need, and what will it cost?"

## Method (use your own numbers)
1. **Ingestion volume** `V` = bytes/day of logs *after source filtering* (only ERROR/WARN etc.).
   Bronze S3 ~ `V x 0.15` (Parquet+snappy, redacted, capped payloads) per day; x retention days.
   Grail cost scales with **scanned** GB - narrow DQL filters and keep windows small.
2. **Curated PG** ~ `signatures_per_window x windows_per_day x ~300 bytes` + problems; usually < 1 GB/year per source.
3. **Agent runs** `R`/day x (`input_tokens` ~ 4-12k incl. tool results + `output_tokens` ~ 0.5-1.5k) x turns (1-4) ->
   token cost from the Bedrock price list for your model. Measure real averages from `agent_runs` after a week.
4. **Compute**: collectors are bursty (every 5 min); pyarrow memory ~ 3-5x part size; API mostly I/O-bound; runtime light.

## Starting instance choices
| Role | Lab | Prod start |
|---|---|---|
| Opsi host (API + runtime + collectors + otel) | m7i.xlarge (4 vCPU/16 GiB) or the existing host if headroom | existing host + 1 dedicated collector host (m7i.large) |
| OpenMetadata lab (all-in-Docker, source build) | m7i.2xlarge (8 vCPU/32 GiB) | n/a |
| OpenMetadata server | - | m7i.large/xlarge |
| OM PostgreSQL | - | db.m7g.large, gp3 100 GiB |
| OM OpenSearch | - | 2x r7g.large.search or m7g.large.search, 100 GiB each |
| Opsi operational OpenSearch (optional) | - | size by curated docs; start 2x m7g.large.search |
Check current instance families/prices in your region; Graviton (g) variants are cheaper where supported.

## Cost levers
- Source filters (biggest lever), window/caps, final re-scan on/off per source.
- S3 lifecycle tiers; Parquet compression; don't store full payloads if not needed (`INGEST_PAYLOAD_MAX_BYTES`).
- Agent budgets, history trimming, smaller model for routing/summaries (Portkey routing), caching only when approved.
- Turn off OpenMetadata lab when idle (`compose_safe.sh openmetadata-lab down`).

## Capacity alarms
CPU > 70 % sustained on the Opsi host during collector runs -> move collectors off-host; RDS CPU/IOPS/connection spikes
at :00/:05 -> stagger timers (`RandomizedDelaySec`), lower batch sizes; S3 PUT 503 SlowDown -> fewer, larger parts.
