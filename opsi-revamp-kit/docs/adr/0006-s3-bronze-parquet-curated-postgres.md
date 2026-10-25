# ADR-0006: Raw events to S3 bronze Parquet; only a curated subset to PostgreSQL
- Status: Accepted
- Date: 2026-10-24

## Context
Log volume is large; the existing PostgreSQL estate is multi-TB and serves production. The master prompt forbids
bulk-loading raw logs into it, and asks for an immutable-ish archive with provenance, checksums, classification and
quarantine. Investigations need fast access to *signals* (problems, error signatures, examples), not every line.

## Decision
- **Bronze** = S3 Parquet (`opsi.event.v1`, fixed Arrow schema), one folder per window run:
  `raw/{source}/dataset={kind}/dt=YYYY-MM-DD/window={start}_{end}/run={run_id}/part-NNNNN.parquet` + `_manifest.json`.
  Every row carries tenant, source, origin id, deterministic `event_uid`, event/ingest time, window, run, severity,
  service, redacted message + payload (size-capped), SHA-256, classification, `source_ref`.
- Bad rows go to `quarantine/...jsonl.gz` with closed-vocabulary reasons; never silently dropped or "fixed".
- **Curated PostgreSQL** (`opsi_ingest`): problems (latest observation), per-window error signatures (replace
  semantics guarded by run order), up to N evidence samples per signature. Optional OpenSearch `opsi-incidents`.
- SSE-KMS by default; bucket policy denies non-TLS and unencrypted puts.

## Consequences
- Analytics over raw data = Athena/Spark on S3 (manifest-aware views), not PostgreSQL.
- Curated tables are rebuildable from bronze by re-running the index stage.
- S3 Parquet is an **archive, not a DB backup** - PostgreSQL backups stay RDS snapshots/PITR (ADR in runbooks).

## Alternatives considered
- Everything into PostgreSQL (starter) - capacity and blast-radius risk.
- Everything into OpenSearch - costly retention, not an immutable archive.
- JSON lines in S3 - larger, slower to query, no schema enforcement.

## Verification
`tests/ingestion/test_pipeline.py` (schema identity, manifests, quarantine, checksum tamper detection),
`database/migrations/0002_ingest.sql` contains no raw payload columns.
