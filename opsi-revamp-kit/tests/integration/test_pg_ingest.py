"""PostgreSQL integration: collector state backend + curated sink against the real schema.

Run against a throwaway database with migrations applied, e.g. PGlite:
    (cd database/validate && npm ci && node serve_pglite.mjs --port 55432)
    TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:55432/postgres?sslmode=disable' pytest -m integration
Never point TEST_DATABASE_URL at a shared or production database.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration
URL = os.environ.get("TEST_DATABASE_URL", "")
UTC = timezone.utc
T0 = datetime(2026, 10, 24, 10, 0, tzinfo=UTC)

if not URL:
    pytest.skip("TEST_DATABASE_URL not set", allow_module_level=True)

psycopg = pytest.importorskip("psycopg")

from opsi_ingest.sinks.postgres_curated import PostgresCuratedSink  # noqa: E402
from opsi_ingest.state import StateStore  # noqa: E402
from opsi_ingest.windows import Window  # noqa: E402


@pytest.fixture
def source_name():
    return f"it_{uuid.uuid4().hex[:8]}"


def test_postgres_state_store_ledger_outbox_and_watermark(source_name):
    store = StateStore.postgres(URL)
    try:
        w1, w2 = Window(T0, T0 + timedelta(minutes=5)), Window(T0 + timedelta(minutes=5), T0 + timedelta(minutes=10))
        store.init_watermark(source_name, "logs", T0, T0)
        store.mark_running(source_name, "logs", w2, "r2", T0)
        store.mark_committed(source_name, "logs", w2, "r2", record_count=3, quarantined_count=0,
                             manifest_key="k2", now=T0)
        assert store.advance_watermark(source_name, "logs", T0) == T0  # w1 missing -> blocked
        store.mark_running(source_name, "logs", w1, "r1", T0)
        store.mark_running(source_name, "logs", w1, "r1b", T0)  # retry increments attempts
        assert store.get_window(source_name, "logs", w1).attempts == 2
        store.mark_committed(source_name, "logs", w1, "r1b", record_count=1, quarantined_count=1,
                             manifest_key="k1", now=T0)
        assert store.advance_watermark(source_name, "logs", T0) == T0 + timedelta(minutes=10)
        store.mark_failed(source_name, "logs", w1, "r1c", "late rescan failed", T0)
        assert store.get_window(source_name, "logs", w1).status == "bronze_committed"  # never demoted
        items = store.claim_pending(T0 + timedelta(seconds=1), 10, source_name)
        assert [i.manifest_key for i in items] == ["k1", "k2"]
        assert store.outbox_failed(items[0], "pg down", T0, max_attempts=1) == "dead"
        store.outbox_done(items[1].id, T0)
        assert store.requeue_dead(T0, "it", "test", source_name) == 1
    finally:
        store.close()


def _manifest(tenant, source, dataset, run_id):
    return {"tenant_id": tenant, "source": source, "dataset": dataset, "run_id": run_id,
            "window_start": "2026-10-24T10:00:00Z", "window_end": "2026-10-24T10:05:00Z"}


def _log_row(uid, sev="ERROR", fp="fp1"):
    return {"severity": sev, "message_fingerprint": fp, "service_id": "payments", "event_time": T0 + timedelta(seconds=5),
            "event_uid": uid, "message": "gateway timeout", "source_ref": f"elastic://i/_doc/{uid}", "trace_id": None}


def _count(tenant, sql, params=()):
    # Superusers (like the test login) always bypass RLS, so read as the non-privileged reporting role.
    with psycopg.connect(URL, prepare_threshold=None) as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE opsi_readonly")
        cur.execute("SELECT set_config('opsi.tenant_id', %s, true)", (tenant,))
        cur.execute(sql, params)
        return cur.fetchone()[0]


def test_curated_sink_replace_semantics_and_run_order_guard(source_name):
    tenant = f"t-{uuid.uuid4().hex[:6]}"
    sink = PostgresCuratedSink(URL, max_samples=2)
    newer = sink.apply(_manifest(tenant, source_name, "logs", "20261024T104000Z-b"),
                       [_log_row("u1"), _log_row("u2"), _log_row("u3", sev="INFO")])
    assert newer["signatures"] == 1 and newer["samples"] == 2
    older = sink.apply(_manifest(tenant, source_name, "logs", "20261024T100700Z-a"), [_log_row("u9")])
    assert older["skipped_older_run"] == 1  # an older scan never overwrites a newer one
    again = sink.apply(_manifest(tenant, source_name, "logs", "20261024T104000Z-b"),
                       [_log_row("u1"), _log_row("u2"), _log_row("u3", sev="INFO")])
    assert again["signatures"] == 1  # same run re-applied: idempotent replace
    total = _count(tenant, "SELECT sum(event_count) FROM opsi_ingest.error_signature_windows WHERE source=%s",
                   (source_name,))
    assert total == 2
    assert _count("someone-else", "SELECT count(*) FROM opsi_ingest.error_signature_windows WHERE source=%s",
                  (source_name,)) == 0


def test_curated_sink_problems_latest_observation_wins(source_name):
    import json
    tenant = f"t-{uuid.uuid4().hex[:6]}"
    sink = PostgresCuratedSink(URL)

    def problem(status, observed):
        payload = {"problemId": "P1", "displayId": "P-1", "title": "Failure rate", "status": status,
                   "severityLevel": "ERROR", "impactLevel": "SERVICES", "endTime": -1,
                   "affectedEntities": [{"entityId": {"id": "SERVICE-1"}}], "managementZones": []}
        return {"origin_id": "P1", "payload_json": json.dumps(payload), "event_time": T0, "message": "Failure rate",
                "status": status, "record_version": status, "source_ref": "dynatrace-problem://P1",
                "ingest_time": observed}

    sink.apply(dict(_manifest(tenant, source_name, "problems", "r2"), window_start="2026-10-24T10:05:00Z"),
               [problem("CLOSED", T0 + timedelta(minutes=30))])
    sink.apply(_manifest(tenant, source_name, "problems", "r1"), [problem("OPEN", T0 + timedelta(minutes=5))])
    status = _count(tenant, "SELECT status FROM opsi_ingest.problems WHERE problem_id='P1'")
    assert status == "CLOSED"  # the later observation is kept even though it was applied first
