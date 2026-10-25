"""Opsi bounded collectors: source -> S3 bronze Parquet -> (separately) curated PostgreSQL/OpenSearch.

Entry point: ``python -m opsi_ingest --help`` (run from ``services/ingestion``).

Design rules (see docs/consultations/04-ingestion-correctness-and-backfills.md):
- Windows are aligned to a fixed grid so a re-run of the same window is identifiable.
- The bronze stage commits a window only after every Parquet part *and* the manifest are in S3.
- The index stage (PostgreSQL/OpenSearch) runs from an outbox; its failures never move watermarks.
- Missing or unparseable timestamps are quarantined, never replaced with "now".
"""

__version__ = "0.3.0"
