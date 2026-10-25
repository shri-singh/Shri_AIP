"""Deterministic, grid-aligned time windows.

Why a grid (instead of "last watermark minus overlap")? Because the same window
must map to the same identity on every retry. With a grid, ``[10:05, 10:10)``
is always the same window, so the ledger, the S3 prefix and the outbox can all
key on it, and a retry is recognisable as a retry.

Late-arriving data is handled by an optional *final re-scan* of each window
once ``final_rescan_after`` has elapsed (see ``plan_rescans``), not by
overlapping windows.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .timeutil import compact_z, floor_to_grid, iso_z


@dataclass(frozen=True, order=True)
class Window:
    start: datetime  # inclusive
    end: datetime  # exclusive

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("window bounds must be timezone-aware")
        if self.start >= self.end:
            raise ValueError("window start must be before end")

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    @property
    def key(self) -> str:
        """Stable identity used in S3 keys and the ledger: ``20261024T100500Z_20261024T101000Z``."""
        return f"{compact_z(self.start)}_{compact_z(self.end)}"

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end

    def split(self) -> tuple[Window, Window]:
        middle = self.start + (self.end - self.start) / 2
        middle = middle.replace(microsecond=0) if (middle - self.start).total_seconds() >= 2 else middle
        return Window(self.start, middle), Window(middle, self.end)

    def __str__(self) -> str:
        return f"[{iso_z(self.start)}, {iso_z(self.end)})"


def plan_windows(
    *,
    committed_until: datetime | None,
    now: datetime,
    step: timedelta,
    lag: timedelta,
    initial_lookback: timedelta,
    max_windows: int,
) -> list[Window]:
    """Return the next closed grid windows to collect, oldest first.

    - A window is "closed" when ``window.end <= now - lag`` (sources need time
      to make late-indexed data searchable).
    - The first run starts ``initial_lookback`` before the newest closed grid point.
    - At most ``max_windows`` are returned so one run cannot run unbounded after an outage;
      the next scheduled run continues the catch-up.
    """
    if max_windows < 1:
        raise ValueError("max_windows must be >= 1")
    horizon = floor_to_grid(now - lag, step)
    if committed_until is None:
        cursor = floor_to_grid(horizon - initial_lookback, step)
    else:
        cursor = floor_to_grid(committed_until, step)
        if cursor != committed_until:
            raise ValueError(
                "committed_until is not on the window grid; INGEST_WINDOW_MINUTES was probably "
                "changed after windows were committed. See runbook 'Changing the window size'."
            )
    windows: list[Window] = []
    while cursor + step <= horizon and len(windows) < max_windows:
        windows.append(Window(cursor, cursor + step))
        cursor += step
    return windows


def windows_between(start: datetime, end: datetime, step: timedelta) -> list[Window]:
    """Grid windows covering ``[start, end)`` for explicit backfills."""
    cursor = floor_to_grid(start, step)
    result = []
    while cursor < end:
        result.append(Window(cursor, cursor + step))
        cursor += step
    return result


def needs_final_rescan(
    *, window: Window, last_scan_at: datetime, now: datetime, final_rescan_after: timedelta
) -> bool:
    """True when the window was last scanned before late data could settle and that time has now passed."""
    if final_rescan_after <= timedelta(0):
        return False
    settle_point = window.end + final_rescan_after
    return last_scan_at < settle_point <= now
