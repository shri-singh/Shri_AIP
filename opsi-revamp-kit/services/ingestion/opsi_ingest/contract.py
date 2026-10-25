"""The bronze event contract ``opsi.event.v1``.

One explicit Arrow schema for every Parquet part. Never let pyarrow infer the
schema from a batch: a column that happens to be all-null in one batch is
inferred as type ``null`` and later parts become unreadable together in
Athena/Glue/Spark.

Schema evolution rules (docs/data-contracts.md):
- Additive, nullable columns only within ``v1``. Bump to ``v2`` for renames/type changes.
- ``schema_version`` is written into every row, object metadata and the manifest.
"""
from __future__ import annotations

import pyarrow as pa

SCHEMA_VERSION = "opsi.event.v1"
MANIFEST_VERSION = 1

TS = pa.timestamp("us", tz="UTC")

EVENT_SCHEMA = pa.schema(
    [
        pa.field("schema_version", pa.string(), nullable=False),
        pa.field("tenant_id", pa.string(), nullable=False),
        pa.field("source", pa.string(), nullable=False),
        pa.field("dataset", pa.string(), nullable=False),
        pa.field("origin_id", pa.string(), nullable=False),
        pa.field("event_uid", pa.string(), nullable=False),
        pa.field("record_version", pa.string(), nullable=False),
        pa.field("event_time", TS, nullable=False),
        pa.field("ingest_time", TS, nullable=False),
        pa.field("window_start", TS, nullable=False),
        pa.field("window_end", TS, nullable=False),
        pa.field("run_id", pa.string(), nullable=False),
        pa.field("severity", pa.string(), nullable=False),
        pa.field("severity_raw", pa.string()),
        pa.field("status", pa.string()),
        pa.field("service_id", pa.string()),
        pa.field("host_id", pa.string()),
        pa.field("trace_id", pa.string()),
        pa.field("title", pa.string()),
        pa.field("message", pa.string()),
        pa.field("message_fingerprint", pa.string()),
        pa.field("classification", pa.string(), nullable=False),
        pa.field("source_ref", pa.string(), nullable=False),
        pa.field("redaction_hits", pa.int32(), nullable=False),
        pa.field("payload_json", pa.string(), nullable=False),
        pa.field("payload_truncated", pa.bool_(), nullable=False),
        pa.field("payload_sha256", pa.string(), nullable=False),
    ],
    metadata={b"opsi.schema_version": SCHEMA_VERSION.encode()},
)

COLUMN_NAMES = tuple(EVENT_SCHEMA.names)

SEVERITIES = ("CRITICAL", "ERROR", "WARN", "INFO", "DEBUG", "UNKNOWN")

# Quarantine reasons are a closed vocabulary so dashboards can group them.
QUARANTINE_REASONS = (
    "timestamp_missing",
    "timestamp_invalid",
    "timestamp_naive",
    "origin_id_missing",
    "payload_not_object",
    "event_outside_window",
    "normalization_error",
)


def table_from_rows(rows: list[dict]) -> pa.Table:
    """Build a table with the fixed schema; raises if a row has unexpected/missing required fields."""
    missing = [c for c in COLUMN_NAMES if rows and c not in rows[0]]
    if missing:
        raise ValueError(f"rows missing contract columns: {missing}")
    return pa.Table.from_pylist(rows, schema=EVENT_SCHEMA)
