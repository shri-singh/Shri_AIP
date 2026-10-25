from datetime import datetime, timedelta, timezone

import pytest
from opsi_ingest.timeutil import TimestampError, parse_timestamp
from opsi_ingest.windows import Window, needs_final_rescan, plan_windows, windows_between

UTC = timezone.utc
T0 = datetime(2026, 10, 24, 10, 0, tzinfo=UTC)


class TestParseTimestamp:
    def test_nanosecond_iso_from_grail(self):
        assert parse_timestamp("2026-10-24T10:01:00.123456789Z") == datetime(2026, 10, 24, 10, 1, 0, 123456, tzinfo=UTC)

    def test_epoch_milliseconds_from_dynatrace(self):
        assert parse_timestamp(1729764000000) == datetime(2024, 10, 24, 10, 0, tzinfo=UTC)

    def test_epoch_seconds_and_numeric_strings(self):
        assert parse_timestamp("1729764000") == datetime(2024, 10, 24, 10, 0, tzinfo=UTC)

    def test_offsets_are_converted_to_utc(self):
        assert parse_timestamp("2026-10-24T12:00:00+02:00") == T0

    @pytest.mark.parametrize("bad", [None, "", "yesterday", True, -5, "2026-13-40T00:00:00Z"])
    def test_bad_values_raise_and_never_return_now(self, bad):
        with pytest.raises(TimestampError):
            parse_timestamp(bad)

    def test_naive_is_rejected_unless_explicitly_allowed(self):
        with pytest.raises(TimestampError, match="naive"):
            parse_timestamp("2026-10-24T10:00:00")
        assert parse_timestamp("2026-10-24T10:00:00", assume_utc_for_naive=True) == T0


class TestPlanWindows:
    def test_first_run_aligns_to_grid_with_lookback_and_lag(self):
        now = datetime(2026, 10, 24, 10, 17, 30, tzinfo=UTC)
        windows = plan_windows(committed_until=None, now=now, step=timedelta(minutes=5), lag=timedelta(minutes=2),
                               initial_lookback=timedelta(minutes=15), max_windows=10)
        # horizon = floor(10:15:30, 5m) = 10:15 -> windows 10:00..10:15
        assert [w.start.minute for w in windows] == [0, 5, 10]
        assert windows[-1].end == datetime(2026, 10, 24, 10, 15, tzinfo=UTC)

    def test_open_window_is_never_planned(self):
        now = datetime(2026, 10, 24, 10, 6, 59, tzinfo=UTC)
        windows = plan_windows(committed_until=T0, now=now, step=timedelta(minutes=5), lag=timedelta(minutes=2),
                               initial_lookback=timedelta(minutes=15), max_windows=10)
        assert windows == []  # 10:00-10:05 closes at 10:07 once lag is applied

    def test_catch_up_is_bounded(self):
        now = T0 + timedelta(hours=3)
        windows = plan_windows(committed_until=T0, now=now, step=timedelta(minutes=5), lag=timedelta(0),
                               initial_lookback=timedelta(minutes=5), max_windows=6)
        assert len(windows) == 6 and windows[0].start == T0

    def test_off_grid_watermark_is_refused(self):
        with pytest.raises(ValueError, match="grid"):
            plan_windows(committed_until=T0 + timedelta(minutes=1), now=T0 + timedelta(hours=1),
                         step=timedelta(minutes=5), lag=timedelta(0), initial_lookback=timedelta(minutes=5),
                         max_windows=3)

    def test_same_window_always_has_same_key(self):
        a = windows_between(T0, T0 + timedelta(minutes=10), timedelta(minutes=5))
        b = windows_between(T0 + timedelta(minutes=1), T0 + timedelta(minutes=10), timedelta(minutes=5))
        assert [w.key for w in a] == [w.key for w in b] == ["20261024T100000Z_20261024T100500Z",
                                                              "20261024T100500Z_20261024T101000Z"]


class TestWindow:
    def test_split_covers_window_exactly(self):
        w = Window(T0, T0 + timedelta(minutes=5))
        left, right = w.split()
        assert left.start == w.start and right.end == w.end and left.end == right.start

    def test_half_open_bounds(self):
        w = Window(T0, T0 + timedelta(minutes=5))
        assert w.contains(T0) and not w.contains(T0 + timedelta(minutes=5))

    def test_naive_bounds_rejected(self):
        with pytest.raises(ValueError):
            Window(datetime(2026, 1, 1), datetime(2026, 1, 2))


class TestFinalRescan:
    w = Window(T0, T0 + timedelta(minutes=5))

    def test_rescan_due_after_settle_time(self):
        assert needs_final_rescan(window=self.w, last_scan_at=T0 + timedelta(minutes=7),
                                  now=T0 + timedelta(minutes=40), final_rescan_after=timedelta(minutes=30))

    def test_not_due_yet(self):
        assert not needs_final_rescan(window=self.w, last_scan_at=T0 + timedelta(minutes=7),
                                      now=T0 + timedelta(minutes=20), final_rescan_after=timedelta(minutes=30))

    def test_not_needed_when_first_scan_was_already_late(self):
        assert not needs_final_rescan(window=self.w, last_scan_at=T0 + timedelta(hours=2),
                                      now=T0 + timedelta(hours=3), final_rescan_after=timedelta(minutes=30))

    def test_disabled(self):
        assert not needs_final_rescan(window=self.w, last_scan_at=T0, now=T0 + timedelta(days=1),
                                      final_rescan_after=timedelta(0))
