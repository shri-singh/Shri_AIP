"""PostgreSQL curated sink (schema in database/migrations/0002_ingest.sql).

Runs as the ``opsi_ingest_writer`` role, which can write only ``opsi_ingest.*``.
Every apply is one transaction with ``statement_timeout``/``lock_timeout`` so a
busy multi-TB primary is never blocked for long. Tune batch sizes with the DBA.

``prepare_threshold=None`` disables server-side prepared statements: required
behind PgBouncer / RDS Proxy in transaction-pooling mode (otherwise
``prepared statement "_pg3_0" already exists`` errors), negligible cost here.
"""
from __future__ import annotations

from typing import Any

from ..timeutil import parse_timestamp
from .curated import aggregate_signatures, problem_rows


class PostgresCuratedSink:
    name = "postgres"

    def __init__(self, url: str, max_samples: int = 3, statement_timeout_ms: int = 60_000) -> None:
        if not url:
            raise ValueError("DATABASE_URL is required for the PostgreSQL curated sink")
        self.url = url
        self.max_samples = max_samples
        self.statement_timeout_ms = statement_timeout_ms

    def apply(self, manifest: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, int]:
        import psycopg
        from psycopg.types.json import Jsonb

        tenant = manifest["tenant_id"]
        source, dataset, run_id = manifest["source"], manifest["dataset"], manifest["run_id"]
        window_start = parse_timestamp(manifest["window_start"])
        window_end = parse_timestamp(manifest["window_end"])
        counts = {"problems": 0, "signatures": 0, "samples": 0, "skipped_older_run": 0}
        with psycopg.connect(self.url, prepare_threshold=None) as conn, conn.cursor() as cur:
            cur.execute(f"SET LOCAL statement_timeout = {int(self.statement_timeout_ms)}")
            cur.execute("SET LOCAL lock_timeout = 5000")
            cur.execute("SELECT set_config('opsi.tenant_id', %s, true)", (tenant,))
            # run-order guard: never let an older scan overwrite a newer one
            cur.execute(
                """INSERT INTO opsi_ingest.window_index_state AS s (tenant_id, source, dataset, window_start, run_id, applied_at)
                   VALUES (%s,%s,%s,%s,%s, now())
                   ON CONFLICT (tenant_id, source, dataset, window_start) DO UPDATE
                     SET run_id = excluded.run_id, applied_at = excluded.applied_at
                     WHERE s.run_id <= excluded.run_id
                   RETURNING run_id""",
                (tenant, source, dataset, window_start, run_id),
            )
            if cur.fetchone() is None:
                counts["skipped_older_run"] = 1
                return counts

            if dataset == "problems":
                for p in problem_rows(rows):
                    cur.execute(
                        """INSERT INTO opsi_ingest.problems AS p (tenant_id, problem_id, display_id, title, status,
                             severity_level, impact_level, start_time, end_time, root_cause_entity_id,
                             affected_entity_ids, management_zones, record_version, evidence_ref, last_observed_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s, to_timestamp(%s / 1000.0),%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (tenant_id, problem_id) DO UPDATE SET
                             display_id=excluded.display_id, title=excluded.title, status=excluded.status,
                             severity_level=excluded.severity_level, impact_level=excluded.impact_level,
                             end_time=excluded.end_time, root_cause_entity_id=excluded.root_cause_entity_id,
                             affected_entity_ids=excluded.affected_entity_ids,
                             management_zones=excluded.management_zones, record_version=excluded.record_version,
                             evidence_ref=excluded.evidence_ref, last_observed_at=excluded.last_observed_at
                           WHERE p.last_observed_at <= excluded.last_observed_at""",
                        (tenant, p["problem_id"], p["display_id"], p["title"], p["status"], p["severity_level"],
                         p["impact_level"], p["start_time"], p["end_time_ms"], p["root_cause_entity_id"],
                         Jsonb(p["affected_entity_ids"]), Jsonb(p["management_zones"]), p["record_version"],
                         p["evidence_ref"], p["observed_at"]),
                    )
                    counts["problems"] += 1
            else:
                signatures, samples = aggregate_signatures(rows, self.max_samples)
                cur.execute(
                    "DELETE FROM opsi_ingest.error_signature_windows WHERE tenant_id=%s AND source=%s AND window_start=%s",
                    (tenant, source, window_start),
                )
                cur.execute(
                    "DELETE FROM opsi_ingest.evidence_samples WHERE tenant_id=%s AND source=%s AND window_start=%s",
                    (tenant, source, window_start),
                )
                cur.executemany(
                    """INSERT INTO opsi_ingest.error_signature_windows (tenant_id, source, window_start, window_end,
                         service_id, fingerprint, severity, event_count, first_seen, last_seen, sample_message,
                         sample_ref, run_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    [(tenant, source, window_start, window_end, s.service_id, s.fingerprint, s.severity, s.count,
                      s.first_seen, s.last_seen, s.sample_message, s.sample_ref, run_id) for s in signatures],
                )
                cur.executemany(
                    """INSERT INTO opsi_ingest.evidence_samples (tenant_id, source, window_start, event_uid,
                         service_id, fingerprint, severity, event_time, message_excerpt, source_ref, trace_id, run_id)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (tenant_id, event_uid) DO NOTHING""",
                    [(tenant, source, window_start, s["event_uid"], s["service_id"], s["fingerprint"], s["severity"],
                      s["event_time"], s["message_excerpt"], s["source_ref"], s["trace_id"], run_id) for s in samples],
                )
                counts["signatures"], counts["samples"] = len(signatures), len(samples)
        return counts
