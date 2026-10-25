"""End-to-end stage tests: SQLite state + local object store + in-memory source/sinks.

Covers the master prompt's ingestion definition of done: overlapping/repeated
windows, late events, duplicate ids, S3/PG partial failure, restart without
data loss, result-cap handling and fail-closed watermarks.
"""
import io
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pyarrow.parquet as pq
import pytest
from opsi_ingest.contract import EVENT_SCHEMA
from opsi_ingest.pipeline import BronzeStage, IndexStage
from opsi_ingest.sinks.bronze import load_manifest, read_manifest_rows
from opsi_ingest.sinks.curated import MemoryCuratedSink, aggregate_signatures
from opsi_ingest.sinks.objectstore import LocalObjectStore
from opsi_ingest.state import StateStore
from opsi_ingest.windows import Window

from .fakes import Clock, ListSource, event

UTC = timezone.utc
T0 = datetime(2026, 10, 24, 10, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


@pytest.fixture
def env(settings):
    clock = Clock(at(17))  # horizon = floor(10:15) -> first run plans 10:00, 10:05, 10:10
    state = StateStore.sqlite(settings.state_sqlite_path)
    store = LocalObjectStore(settings.local_archive_dir)
    yield settings, clock, state, store
    state.close()


def all_committed_rows(store, state, source="synthetic", dataset="logs"):
    rows = []
    for w in state.recent_windows(source, T0 - timedelta(days=1)):
        if w.status == "bronze_committed":
            rows.extend(read_manifest_rows(store, load_manifest(store, w.manifest_key)))
    return rows


class FlakyStore(LocalObjectStore):
    def __init__(self, root, fail_on_put: int):
        super().__init__(root)
        self.puts = 0
        self.fail_on_put = fail_on_put

    def put(self, key, data, **kw):
        self.puts += 1
        if self.puts == self.fail_on_put:
            raise ConnectionError("simulated S3 outage")
        return super().put(key, data, **kw)


def test_happy_path_commits_contiguous_windows_and_advances_watermark(env):
    settings, clock, state, store = env
    source = ListSource([event("a", at(1)), event("b", at(6)), event("c", at(6.5), level="INFO"), event("d", at(12))])
    summary = BronzeStage(settings, source, state, store, clock=clock).run()
    assert summary.ok and summary.records == 4
    assert [str(o.window) for o in summary.outcomes] == [
        "[2026-10-24T10:00:00Z, 2026-10-24T10:05:00Z)", "[2026-10-24T10:05:00Z, 2026-10-24T10:10:00Z)",
        "[2026-10-24T10:10:00Z, 2026-10-24T10:15:00Z)"]
    assert state.committed_until("synthetic", "logs") == at(15)
    manifest = load_manifest(store, summary.outcomes[1].manifest_key)
    assert manifest["record_count"] == 2 and manifest["schema_version"] == "opsi.event.v1"
    assert manifest["parts"][0]["key"].startswith(
        "raw/synthetic/dataset=logs/dt=2026-10-24/window=20261024T100500Z_20261024T101000Z/run=")
    assert sorted(r["origin_id"] for r in all_committed_rows(store, state)) == ["a", "b", "c", "d"]
    assert state.outbox_counts() == {"pending": 3}


def test_parquet_schema_is_identical_across_parts_even_with_all_null_columns(env):
    settings, clock, state, store = env
    # part_max_rows=2 -> 3 events in one window produce 2 parts; second part has no trace/host at all
    source = ListSource([event("a", at(1)), event("b", at(2)), event("c", at(3))])
    summary = BronzeStage(settings, source, state, store, clock=clock).run(max_windows=1)
    manifest = load_manifest(store, summary.outcomes[0].manifest_key)
    assert len(manifest["parts"]) == 2
    for part in manifest["parts"]:
        table = pq.read_table(io.BytesIO(store.get(part["key"])))
        assert table.schema.remove_metadata() == EVENT_SCHEMA.remove_metadata()


def test_duplicate_ids_within_a_window_are_written_once(env):
    settings, clock, state, store = env
    source = ListSource([event("a", at(1)), event("a", at(1)), event("b", at(2))])
    summary = BronzeStage(settings, source, state, store, clock=clock).run(max_windows=1)
    assert summary.outcomes[0].records == 2 and summary.outcomes[0].duplicates == 1


def test_s3_failure_mid_window_does_not_advance_watermark_and_restart_loses_nothing(env, tmp_path):
    settings, clock, state, _ = env
    events = [event(str(i), at(1 + i * 0.1)) for i in range(5)] + [event("w2", at(7))]
    flaky = FlakyStore(settings.local_archive_dir, fail_on_put=2)  # 2nd part upload of first window fails
    summary = BronzeStage(settings, ListSource(events), state, flaky, clock=clock).run()
    assert not summary.ok and len(summary.outcomes) == 1  # stopped at the failing window (fail closed)
    assert state.committed_until("synthetic", "logs") == at(0)
    assert state.get_window("synthetic", "logs", Window(at(0), at(5))).status == "failed"
    assert not [k for k in flaky.list("raw/") if k.endswith("_manifest.json")]

    clock.advance(minutes=5)  # next cron tick; store healthy again
    store = LocalObjectStore(settings.local_archive_dir)
    summary = BronzeStage(settings, ListSource(events), state, store, clock=clock).run()
    assert summary.ok
    assert sorted(r["origin_id"] for r in all_committed_rows(store, state)) == sorted(e["id"] for e in events)
    assert state.committed_until("synthetic", "logs") == at(20)


def test_crash_after_mark_running_is_retried_on_restart(env):
    settings, clock, state, store = env
    w = Window(at(0), at(5))
    state.init_watermark("synthetic", "logs", at(0), clock())
    state.mark_running("synthetic", "logs", w, "crashed-run", clock())  # process died here
    summary = BronzeStage(settings, ListSource([event("a", at(1))]), state, store, clock=clock).run(max_windows=1)
    assert summary.ok and summary.outcomes[0].window == w
    assert state.get_window("synthetic", "logs", w).attempts == 2


def test_failed_window_blocks_progress_until_operator_skips_it(env):
    settings, clock, state, store = env
    source = ListSource([event("a", at(1)), event("b", at(7))], fail_on_call=1)
    assert not BronzeStage(settings, source, state, store, clock=clock).run().ok
    state.mark_skipped("synthetic", "logs", Window(at(0), at(5)), clock(), "jdoe", "source purged; CHG-1")
    state.advance_watermark("synthetic", "logs", clock())
    assert state.committed_until("synthetic", "logs") == at(5)
    summary = BronzeStage(settings, ListSource([event("b", at(7))]), state, store, clock=clock).run()
    assert summary.ok and state.committed_until("synthetic", "logs") == at(15)


def test_result_cap_splits_window_and_collects_every_event_exactly_once(env):
    settings, clock, state, store = env
    events = [event(f"e{i}", at(i * 0.4)) for i in range(12)]  # 12 events inside 10:00-10:05
    source = ListSource(events, cap=4)
    summary = BronzeStage(settings, source, state, store, clock=clock).run(max_windows=1)
    outcome = summary.outcomes[0]
    assert outcome.ok and outcome.records == 12 and outcome.splits >= 2
    origin_ids = [r["origin_id"] for r in all_committed_rows(store, state)]
    assert sorted(origin_ids) == sorted(e["id"] for e in events) and len(origin_ids) == len(set(origin_ids))
    manifest = load_manifest(store, outcome.manifest_key)
    listed = {p["key"] for p in manifest["parts"]}
    on_disk = {k for k in store.list("raw/") if k.endswith(".parquet")}
    assert listed == on_disk  # rolled-back partial parts were deleted


def test_cap_below_minimum_split_fails_closed(env):
    settings, clock, state, store = env
    events = [event(f"e{i}", at(1)) for i in range(10)]  # all in the same instant: splitting cannot help
    summary = BronzeStage(replace(settings, min_split_seconds=60), ListSource(events, cap=3), state, store,
                          clock=clock).run(max_windows=1)
    assert not summary.ok and "minimum split" in summary.outcomes[0].error


def test_late_event_is_picked_up_by_final_rescan(env):
    settings, clock, state, store = env
    events = [event("a", at(1))]
    source = ListSource(events)
    BronzeStage(settings, source, state, store, clock=clock).run()
    events.append(event("late", at(2)))  # arrives in the source after the window was scanned
    clock.advance(minutes=35)
    summary = BronzeStage(settings, source, state, store, clock=clock).run()
    rescans = [o for o in summary.outcomes if o.scan_kind == "final_rescan"]
    assert any(o.window == Window(at(0), at(5)) and o.records == 2 for o in rescans)
    row = state.get_window("synthetic", "logs", Window(at(0), at(5)))
    assert row.scans == 2
    # a third pass is never scheduled
    clock.advance(minutes=60)
    again = BronzeStage(settings, source, state, store, clock=clock).plan()[1]
    assert Window(at(0), at(5)) not in [r.window for r in again]


def test_rerunning_the_same_window_produces_a_new_run_with_same_event_uids(env):
    settings, clock, state, store = env
    source = ListSource([event("a", at(1))])
    first = BronzeStage(settings, source, state, store, clock=clock).run(windows=[Window(at(0), at(5))])
    second = BronzeStage(settings, source, state, store, clock=clock).run(windows=[Window(at(0), at(5))])
    m1, m2 = (load_manifest(store, s.outcomes[0].manifest_key) for s in (first, second))
    assert m1["run_id"] != m2["run_id"]
    uid1 = read_manifest_rows(store, m1)[0]["event_uid"]
    uid2 = read_manifest_rows(store, m2)[0]["event_uid"]
    assert uid1 == uid2  # downstream upserts dedupe deterministically


def test_quarantine_file_written_and_counted(env):
    settings, clock, state, store = env
    bad = {"id": "bad", "_dt": at(1), "level": "ERROR", "msg": "no ts"}
    summary = BronzeStage(settings, ListSource([event("a", at(1)), bad]), state, store, clock=clock).run(max_windows=1)
    manifest = load_manifest(store, summary.outcomes[0].manifest_key)
    assert manifest["quarantined_count"] == 1 and manifest["quarantine_reasons"] == {"timestamp_missing": 1}
    assert manifest["quarantine"][0]["key"].startswith("quarantine/synthetic/")


def test_dry_run_writes_nothing(env):
    settings, clock, state, store = env
    from opsi_ingest.sinks.objectstore import DiscardObjectStore
    discard = DiscardObjectStore()
    summary = BronzeStage(settings, ListSource([event("a", at(1))]), state, discard, clock=clock).run(dry_run=True)
    assert summary.ok and discard.objects and not store.list("")
    assert state.committed_until("synthetic", "logs") is None


# ------------------------------------------------------------------ index stage
def test_index_failure_is_retried_and_never_touches_watermark(env):
    settings, clock, state, store = env
    BronzeStage(settings, ListSource([event("a", at(1))]), state, store, clock=clock).run(max_windows=1)
    watermark = state.committed_until("synthetic", "logs")
    sink = MemoryCuratedSink(fail_times=1)
    stage = IndexStage(settings, state, store, [sink], clock=clock)
    first = stage.run()
    assert first.failed == 1 and state.outbox_counts() == {"pending": 1}
    assert state.committed_until("synthetic", "logs") == watermark
    assert stage.run().processed == 0  # backoff: not yet due
    clock.advance(minutes=2)
    assert stage.run().processed == 1 and sink.applied and state.outbox_counts() == {"done": 1}


def test_index_dead_letter_and_requeue(env):
    settings, clock, state, store = env
    BronzeStage(settings, ListSource([event("a", at(1))]), state, store, clock=clock).run(max_windows=1)
    stage = IndexStage(replace(settings, index_max_attempts=2), state, store, [MemoryCuratedSink(fail_times=99)],
                       clock=clock)
    stage.run()
    clock.advance(hours=2)
    assert stage.run().dead == 1 and state.outbox_counts() == {"dead": 1}
    assert state.requeue_dead(clock(), "jdoe", "PG restored") == 1


def test_index_detects_tampered_part(env):
    settings, clock, state, store = env
    summary = BronzeStage(settings, ListSource([event("a", at(1))]), state, store, clock=clock).run(max_windows=1)
    manifest = load_manifest(store, summary.outcomes[0].manifest_key)
    key = manifest["parts"][0]["key"]
    store.put(key, b"corrupted", content_type="x", metadata={})
    result = IndexStage(settings, state, store, [MemoryCuratedSink()], clock=clock).run()
    assert result.failed == 1


def test_signature_aggregation_only_counts_errors():
    rows = [
        {"severity": "ERROR", "message_fingerprint": "f1", "service_id": "s", "event_time": at(1), "event_uid": "1",
         "message": "boom", "source_ref": "r1", "trace_id": None},
        {"severity": "CRITICAL", "message_fingerprint": "f1", "service_id": "s", "event_time": at(2),
         "event_uid": "2", "message": "boom", "source_ref": "r2", "trace_id": None},
        {"severity": "INFO", "message_fingerprint": "f2", "service_id": "s", "event_time": at(2), "event_uid": "3",
         "message": "ok", "source_ref": "r3", "trace_id": None},
    ]
    signatures, samples = aggregate_signatures(rows, max_samples=1)
    assert len(signatures) == 1 and signatures[0].count == 2 and signatures[0].severity == "CRITICAL"
    assert len(samples) == 1 and samples[0]["source_ref"] == "r1"


def test_status_cli_reports_failed_windows(env, monkeypatch, capsys):
    settings, clock, state, store = env
    BronzeStage(settings, ListSource([event("a", at(1))], fail_on_call=1), state, store, clock=clock).run()
    from opsi_ingest import cli
    monkeypatch.setenv("WORKER_STATE_DB", settings.state_sqlite_path)
    monkeypatch.setenv("OPSI_ENV_FILE", "does-not-exist.env")
    code = cli.main(["status", "--hours", "100000", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and out["sources"][0]["failed_windows"]
