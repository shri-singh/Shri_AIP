import json
from datetime import datetime, timezone

from opsi_ingest.normalize import NormalizeContext, Quarantined, message_fingerprint, normalize, normalize_severity
from opsi_ingest.redaction import Redactor
from opsi_ingest.sources.base import SourceRecord
from opsi_ingest.sources.dynatrace_grail import DynatraceGrailSource
from opsi_ingest.sources.dynatrace_problems import DynatraceProblemsSource
from opsi_ingest.windows import Window

from .fakes import fixture_json

UTC = timezone.utc
W = Window(datetime(2024, 10, 24, 10, 0, tzinfo=UTC), datetime(2024, 10, 24, 10, 5, tzinfo=UTC))
NOW = datetime(2024, 10, 24, 10, 8, tzinfo=UTC)


def ctx(source_cls, **over):
    base = dict(tenant_id="tenant-a", source=source_cls.name, dataset=source_cls.dataset, window=W, run_id="run-1",
                ingest_time=NOW, classification="internal-confidential", message_max_chars=4000,
                payload_max_bytes=65536, window_semantics=source_cls.window_semantics,
                field_map=source_cls.field_map)
    base.update(over)
    return NormalizeContext(**base)


def test_grail_record_normalizes_with_nanoseconds_and_redaction():
    record = fixture_json("grail_poll_succeeded.json")["result"]["records"][0]
    row = normalize(SourceRecord(None, record, "grail://x"), ctx(DynatraceGrailSource), Redactor("strict"))
    assert not isinstance(row, Quarantined)
    assert row["event_time"] == datetime(2024, 10, 24, 10, 1, 0, 123456, tzinfo=UTC)
    assert row["severity"] == "ERROR" and row["service_id"] == "SERVICE-00000000000000A1"
    assert "jane.doe@example.com" not in row["message"] and "jane.doe" not in row["payload_json"]
    assert row["origin_id"].startswith("sha256:") and len(row["event_uid"]) == 64
    assert row["redaction_hits"] >= 1


def test_missing_timestamp_is_quarantined_not_defaulted_to_now():
    result = normalize(SourceRecord("x", {"content": "no time here"}, "grail://x"), ctx(DynatraceGrailSource),
                       Redactor())
    assert isinstance(result, Quarantined) and result.reason == "timestamp_missing"


def test_naive_and_invalid_timestamps_get_distinct_reasons():
    naive = normalize(SourceRecord("a", {"timestamp": "2024-10-24T10:01:00"}, "r"), ctx(DynatraceGrailSource),
                      Redactor())
    bad = normalize(SourceRecord("b", {"timestamp": "not-a-date"}, "r"), ctx(DynatraceGrailSource), Redactor())
    assert naive.reason == "timestamp_naive" and bad.reason == "timestamp_invalid"


def test_event_outside_window_is_quarantined_for_event_time_sources():
    rec = SourceRecord("a", {"timestamp": "2024-10-24T10:05:00Z", "content": "x"}, "r")  # == end (exclusive)
    assert normalize(rec, ctx(DynatraceGrailSource), Redactor()).reason == "event_outside_window"


def test_problem_snapshots_outside_window_are_kept():
    problem = fixture_json("dynatrace_problems_page1.json")["problems"][0]
    problem = dict(problem, startTime=1700000000000)  # started long before the window, still open
    row = normalize(SourceRecord(problem["problemId"], problem, "dynatrace-problem://x"),
                    ctx(DynatraceProblemsSource), Redactor())
    assert not isinstance(row, Quarantined)
    assert row["service_id"] == "SERVICE-00000000000000A1" and row["severity"] == "WARN"
    assert row["status"] == "OPEN" and row["title"] == "P-24101"


def test_secret_in_problem_title_is_redacted():
    problem = fixture_json("dynatrace_problems_page1.json")["problems"][1]
    row = normalize(SourceRecord(problem["problemId"], problem, "r"), ctx(DynatraceProblemsSource), Redactor())
    assert "hunter2" not in row["message"] and "hunter2" not in row["payload_json"]


def test_oversized_payload_is_truncated_and_flagged():
    rec = SourceRecord("a", {"timestamp": "2024-10-24T10:01:00Z", "content": "x" * 5000}, "r")
    row = normalize(rec, ctx(DynatraceGrailSource, payload_max_bytes=1024), Redactor())
    assert row["payload_truncated"] is True and json.loads(row["payload_json"])["_opsi_truncated"] is True


def test_fingerprint_groups_messages_that_differ_only_by_ids():
    a = message_fingerprint("order 123 failed for 7c9e6679-7425-40de-944b-e07fc1f90ae7 from 10.0.0.1:8080")
    b = message_fingerprint("order 98765 failed for 11111111-2222-3333-4444-555555555555 from 10.9.9.9:443")
    c = message_fingerprint("payment declined")
    assert a == b != c


def test_severity_mapping():
    assert [normalize_severity(v) for v in ("fatal", "Error", "warning", "AVAILABILITY", "x", None)] == \
           ["CRITICAL", "ERROR", "WARN", "CRITICAL", "UNKNOWN", "UNKNOWN"]


def test_same_record_same_uid_across_runs():
    rec = SourceRecord("idx/doc-1", {"timestamp": "2024-10-24T10:01:00Z"}, "r")
    a = normalize(rec, ctx(DynatraceGrailSource, run_id="run-1"), Redactor())
    b = normalize(rec, ctx(DynatraceGrailSource, run_id="run-2"), Redactor())
    assert a["event_uid"] == b["event_uid"] and a["record_version"] == b["record_version"]
