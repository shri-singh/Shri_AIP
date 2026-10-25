# ADR-0007: Grid-aligned windows, ledger, manifest commit marker and outbox-driven indexing
- Status: Accepted
- Date: 2026-10-24

## Context
Requirements: deterministic boundaries, idempotent reprocessing, duplicate control, late arrivals, no data loss on
restart, S3/PostgreSQL partial failures must not corrupt watermarks, result caps must not truncate silently.
Exactly-once delivery across HTTP sources, S3 and PostgreSQL is not achievable; effectively-once with
deterministic ids and replace/upsert semantics is.

## Decision
1. Windows are aligned to a fixed grid (`INGEST_WINDOW_MINUTES` dividing 1440). A window closes at `end + lag`.
2. A **window ledger** records every window's status (`running|bronze_committed|failed|skipped`), attempts, scans,
   counts and manifest key. The **watermark** (`committed_until`) only advances over *contiguous* committed or
   operator-skipped windows - a failed window blocks progress (fail closed) and alerts.
3. A window run is committed when every part and finally `_manifest.json` are in S3; the ledger update and the
   **outbox** insert happen in one local transaction.
4. The **index stage** consumes the outbox independently (retry with exponential backoff, dead-letter after
   `INDEX_MAX_ATTEMPTS`, operator requeue). PostgreSQL/OpenSearch failures never touch watermarks or bronze.
5. **Late data**: each window gets exactly one *final re-scan* after `INGEST_FINAL_RESCAN_AFTER_MINUTES`; the newest
   run is authoritative downstream (`window_index_state` guard).
6. **Caps**: sources raise `WindowTooLarge`; the stage rolls back that segment and splits the window recursively
   down to `INGEST_MIN_SPLIT_SECONDS`, then fails loudly.
7. Operator actions (`skip-window`, `requeue-dead`, `reset-watermark`) require an actor and reason and are audited.

## Consequences
- Late data beyond the re-scan horizon is missed by design; tune the horizon per source (or backfill).
- Problems API returns overlapping snapshots (open problems appear in many windows) - handled by upsert on
  `problem_id` keeping the latest observation.
- SQLite state suits one host; use the PostgreSQL state backend for multiple collector hosts.

## Alternatives considered
- Overlapping sliding windows (starter) - non-deterministic keys, duplicates, no late-data guarantee.
- Streaming (Kinesis/MSK + consumers) - the right future step for volume; heavier to operate now.

## Verification
`tests/ingestion/test_pipeline.py` (13 scenario tests) and `tests/integration/test_pg_ingest.py`.
