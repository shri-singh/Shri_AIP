"""The two stages.

BronzeStage: source -> normalize/redact -> Parquet parts + manifest in S3 ->
             ledger commit + outbox row (one transaction) -> watermark advance.
IndexStage:  outbox -> manifest -> verified parts -> curated sinks (PG/OpenSearch).

A failure in IndexStage never touches watermarks or bronze data; the outbox
item is retried with backoff and dead-lettered after INDEX_MAX_ATTEMPTS.
"""
from __future__ import annotations

import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from . import __version__
from .config import Settings
from .errors import IngestError, WindowTooLarge
from .normalize import NormalizeContext, normalize
from .redaction import Redactor, scrub_for_log
from .sinks.bronze import BronzeWriter, load_manifest, read_manifest_rows
from .sinks.curated import CuratedSink
from .sinks.objectstore import ObjectStore
from .sources.base import Source
from .state import StateStore, WindowRow
from .timeutil import compact_z, utcnow
from .windows import Window, needs_final_rescan, plan_windows

log = logging.getLogger("opsi_ingest")


def new_run_id(now: datetime) -> str:
    """Sortable and unique: ``20261024T101502Z-3f9c2a1b``."""
    return f"{compact_z(now)}-{secrets.token_hex(4)}"


@dataclass
class WindowOutcome:
    window: Window
    scan_kind: str
    ok: bool
    records: int = 0
    quarantined: int = 0
    duplicates: int = 0
    splits: int = 0
    manifest_key: str | None = None
    error: str | None = None
    duration_s: float = 0.0


@dataclass
class RunSummary:
    run_id: str
    source: str
    outcomes: list[WindowOutcome] = field(default_factory=list)
    committed_until: datetime | None = None

    @property
    def ok(self) -> bool:
        return all(o.ok for o in self.outcomes)

    @property
    def records(self) -> int:
        return sum(o.records for o in self.outcomes)


class BronzeStage:
    def __init__(self, settings: Settings, source: Source, state: StateStore | None, store: ObjectStore,
                 redactor: Redactor | None = None, clock: Callable[[], datetime] = utcnow) -> None:
        self.settings = settings
        self.source = source
        self.state = state
        self.store = store
        self.redactor = redactor or Redactor(settings.redaction_level)
        self.clock = clock

    # -- planning ------------------------------------------------------------------------
    def plan(self, max_windows: int | None = None) -> tuple[list[Window], list[WindowRow]]:
        assert self.state is not None
        now = self.clock()
        limit = max_windows or self.settings.max_windows_per_run
        committed = self.state.committed_until(self.source.name, self.source.dataset)
        primary = plan_windows(committed_until=committed, now=now, step=self.settings.window,
                               lag=self.settings.lag, initial_lookback=self.settings.initial_lookback,
                               max_windows=limit)
        if committed is None and primary:
            self.state.init_watermark(self.source.name, self.source.dataset, primary[0].start, now)
        rescans: list[WindowRow] = []
        if self.settings.final_rescan_after_minutes > 0:
            since = now - self.settings.final_rescan_after - self.settings.window * (limit + 1)
            for row in self.state.committed_windows_since(self.source.name, self.source.dataset, since):
                if row.scans < 2 and row.last_scan_at and needs_final_rescan(
                        window=row.window, last_scan_at=row.last_scan_at, now=now,
                        final_rescan_after=self.settings.final_rescan_after):
                    rescans.append(row)
        return primary, rescans[:limit]

    # -- execution -----------------------------------------------------------------------
    def run(self, *, max_windows: int | None = None, windows: list[Window] | None = None,
            dry_run: bool = False) -> RunSummary:
        now = self.clock()
        run_id = new_run_id(now)
        summary = RunSummary(run_id=run_id, source=self.source.name)
        if dry_run:
            planned = windows or plan_windows(
                committed_until=self.state.committed_until(self.source.name, self.source.dataset) if self.state else None,
                now=now, step=self.settings.window, lag=self.settings.lag,
                initial_lookback=self.settings.initial_lookback, max_windows=1)
            for window in planned[:1]:
                summary.outcomes.append(self._process(window, run_id, "dry_run", dry_run=True))
            return summary

        assert self.state is not None
        if windows is None:
            primary, rescans = self.plan(max_windows)
        else:
            primary, rescans = windows, []
        self.state.start_run(run_id, self.source.name, "bronze", now)
        try:
            for window in primary:
                outcome = self._process(window, run_id, "primary")
                summary.outcomes.append(outcome)
                if not outcome.ok:
                    break  # fail closed: later windows cannot advance the watermark past this one anyway
            for row in rescans:
                summary.outcomes.append(self._process(row.window, run_id, "final_rescan"))
            summary.committed_until = self.state.advance_watermark(self.source.name, self.source.dataset,
                                                                   self.clock())
        finally:
            self.state.finish_run(run_id, "ok" if summary.ok else "failed", len(summary.outcomes),
                                  summary.records, {"errors": [o.error for o in summary.outcomes if o.error]},
                                  self.clock())
        return summary

    def _process(self, window: Window, run_id: str, scan_kind: str, dry_run: bool = False) -> WindowOutcome:
        started = time.monotonic()
        src, ds = self.source.name, self.source.dataset
        writer = BronzeWriter(
            self.store, raw_prefix=self.settings.archive_prefix, quarantine_prefix=self.settings.quarantine_prefix,
            tenant_id=self.settings.tenant_id, source=src, dataset=ds, window=window, run_id=run_id,
            classification=self.settings.classification, part_max_rows=self.settings.part_max_rows,
        )
        if not dry_run:
            assert self.state is not None
            self.state.mark_running(src, ds, window, run_id, self.clock())
        try:
            self._collect(window, window, writer, run_id)
            manifest_key = writer.commit(created_at=self.clock(), scan_kind=scan_kind,
                                         collector_version=__version__)
            stats = writer.stats
            if not dry_run:
                self.state.mark_committed(src, ds, window, run_id, record_count=stats.records,
                                          quarantined_count=stats.quarantined, manifest_key=manifest_key,
                                          now=self.clock())
            outcome = WindowOutcome(window, scan_kind, True, stats.records, stats.quarantined, stats.duplicates,
                                    stats.splits, manifest_key, None, time.monotonic() - started)
            log.info("window_committed", extra={"audit": {
                "source": src, "dataset": ds, "window": str(window), "scan": scan_kind, "run_id": run_id,
                "records": stats.records, "quarantined": stats.quarantined, "duplicates": stats.duplicates,
                "out_of_window": stats.out_of_window, "splits": stats.splits, "bytes": stats.bytes,
                "quarantine_reasons": stats.quarantine_reasons, "duration_s": round(outcome.duration_s, 2),
                "dry_run": dry_run}})
            return outcome
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, then surfaced via exit code
            writer.abort()
            message = scrub_for_log(f"{type(exc).__name__}: {exc}")
            if not dry_run:
                self.state.mark_failed(src, ds, window, run_id, message, self.clock())
            log.error("window_failed", extra={"audit": {"source": src, "dataset": ds, "window": str(window),
                                                        "scan": scan_kind, "run_id": run_id, "error": message}})
            if not isinstance(exc, IngestError):
                log.debug("unexpected error type", exc_info=True)
            return WindowOutcome(window, scan_kind, False, error=message, duration_s=time.monotonic() - started)

    def _collect(self, grid: Window, bounds: Window, writer: BronzeWriter, run_id: str) -> None:
        ctx = NormalizeContext(
            tenant_id=self.settings.tenant_id, source=self.source.name, dataset=self.source.dataset, window=grid,
            run_id=run_id, ingest_time=self.clock(), classification=self.settings.classification,
            message_max_chars=self.settings.message_max_chars, payload_max_bytes=self.settings.payload_max_bytes,
            window_semantics=self.source.window_semantics, field_map=self.source.field_map, bounds=bounds,
        )
        writer.begin_segment(bounds)
        try:
            for record in self.source.fetch(bounds):
                writer.add(normalize(record, ctx, self.redactor))
        except WindowTooLarge:
            writer.rollback_segment()
            if bounds.seconds / 2 < self.settings.min_split_seconds:
                raise WindowTooLarge(
                    f"{self.source.name} window {bounds} is still too large at the minimum split size "
                    f"({self.settings.min_split_seconds}s); raise the source cap or narrow the source filter"
                ) from None
            left, right = bounds.split()
            log.warning("window_split", extra={"audit": {"source": self.source.name, "window": str(bounds)}})
            self._collect(grid, left, writer, run_id)
            self._collect(grid, right, writer, run_id)
        else:
            writer.end_segment()


@dataclass
class IndexSummary:
    processed: int = 0
    failed: int = 0
    dead: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)


class IndexStage:
    def __init__(self, settings: Settings, state: StateStore, store: ObjectStore, sinks: list[CuratedSink],
                 clock: Callable[[], datetime] = utcnow) -> None:
        self.settings = settings
        self.state = state
        self.store = store
        self.sinks = sinks
        self.clock = clock

    def run(self, *, limit: int = 50, source: str | None = None) -> IndexSummary:
        summary = IndexSummary()
        for item in self.state.claim_pending(self.clock(), limit, source):
            try:
                manifest = load_manifest(self.store, item.manifest_key)
                rows = read_manifest_rows(self.store, manifest)
                result: dict[str, Any] = {}
                for sink in self.sinks:
                    result[sink.name] = sink.apply(manifest, rows)
                self.state.outbox_done(item.id, self.clock())
                summary.processed += 1
                summary.details.append({"window": str(item.window), "run_id": item.run_id, "result": result})
                log.info("window_indexed", extra={"audit": {"source": item.source, "window": str(item.window),
                                                            "run_id": item.run_id, "result": result}})
            except Exception as exc:  # noqa: BLE001
                message = scrub_for_log(f"{type(exc).__name__}: {exc}")
                status = self.state.outbox_failed(item, message, self.clock(), self.settings.index_max_attempts)
                summary.failed += 1
                summary.dead += 1 if status == "dead" else 0
                log.error("window_index_failed", extra={"audit": {"source": item.source, "window": str(item.window),
                                                                  "run_id": item.run_id, "status": status,
                                                                  "error": message}})
        return summary
