"""Durable collector state: window ledger, watermarks, outbox, run log.

Two backends with one implementation:
- SQLite (default): single EC2 host; WAL mode + busy timeout so several cron
  processes (one per source, each under ``flock``) can share the file.
- PostgreSQL: multi-host or when you want state backed up with the app DB.
  Tables live in schema ``opsi_ingest`` (database/migrations/0002_ingest.sql).

Invariants:
- ``watermarks.committed_until`` only advances across *contiguous* windows whose
  status is ``bronze_committed`` or ``skipped``. A failed window blocks progress
  (fail closed) until it succeeds or an operator explicitly skips it.
- The outbox row for a window run is written in the same transaction that marks
  the window committed, so the index stage can never miss a committed window.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .timeutil import UTC, parse_timestamp
from .windows import Window

STATUSES = ("running", "bronze_committed", "failed", "skipped")


@dataclass
class WindowRow:
    source: str
    dataset: str
    window: Window
    status: str
    run_id: str | None
    attempts: int
    scans: int
    record_count: int
    quarantined_count: int
    manifest_key: str | None
    last_error: str | None
    last_scan_at: datetime | None
    updated_at: datetime


@dataclass
class OutboxItem:
    id: int
    source: str
    dataset: str
    window: Window
    run_id: str
    manifest_key: str
    attempts: int
    status: str


_SQLITE_DDL = """
CREATE TABLE IF NOT EXISTS watermarks (
  source TEXT NOT NULL, dataset TEXT NOT NULL, committed_until TEXT NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY (source, dataset));
CREATE TABLE IF NOT EXISTS window_ledger (
  source TEXT NOT NULL, dataset TEXT NOT NULL, window_start TEXT NOT NULL, window_end TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('running','bronze_committed','failed','skipped')),
  run_id TEXT, attempts INTEGER NOT NULL DEFAULT 0, scans INTEGER NOT NULL DEFAULT 0,
  record_count INTEGER NOT NULL DEFAULT 0, quarantined_count INTEGER NOT NULL DEFAULT 0,
  manifest_key TEXT, last_error TEXT, last_scan_at TEXT, updated_at TEXT NOT NULL,
  PRIMARY KEY (source, dataset, window_start));
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, dataset TEXT NOT NULL,
  window_start TEXT NOT NULL, window_end TEXT NOT NULL, run_id TEXT NOT NULL, manifest_key TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','done','dead')),
  attempts INTEGER NOT NULL DEFAULT 0, next_attempt_at TEXT NOT NULL, last_error TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE (source, dataset, window_start, run_id));
CREATE INDEX IF NOT EXISTS ix_outbox_pending ON outbox (status, next_attempt_at);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, source TEXT NOT NULL, stage TEXT NOT NULL, started_at TEXT NOT NULL,
  finished_at TEXT, status TEXT NOT NULL, windows INTEGER NOT NULL DEFAULT 0, records INTEGER NOT NULL DEFAULT 0,
  detail TEXT);
CREATE TABLE IF NOT EXISTS operator_actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
  source TEXT NOT NULL, dataset TEXT NOT NULL, window_start TEXT, reason TEXT NOT NULL);
"""


class StateStore:
    """Backend-neutral SQL. ``?`` placeholders are rewritten to ``%s`` for psycopg."""

    def __init__(self, conn: Any, *, dialect: str, table_prefix: str = "") -> None:
        self._conn = conn
        self.dialect = dialect
        self.t = table_prefix  # "" for sqlite, "opsi_ingest." for postgres

    # -- construction -------------------------------------------------------------------
    @classmethod
    def sqlite(cls, path: str | Path) -> StateStore:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), timeout=30, isolation_level=None)  # autocommit; explicit BEGIN below
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_SQLITE_DDL)
        return cls(conn, dialect="sqlite")

    @classmethod
    def postgres(cls, url: str) -> StateStore:
        import psycopg  # imported lazily: optional dependency

        conn = psycopg.connect(url, autocommit=True, prepare_threshold=None)  # PgBouncer/RDS Proxy safe
        conn.execute("SET application_name = 'opsi_ingest_state'")
        return cls(conn, dialect="postgres", table_prefix="opsi_ingest.")

    def close(self) -> None:
        self._conn.close()

    # -- low level ---------------------------------------------------------------------
    def _sql(self, sql: str) -> str:
        sql = sql.replace("{t}", self.t)
        return sql.replace("?", "%s") if self.dialect == "postgres" else sql

    def _ts(self, value: datetime | None) -> Any:
        if value is None:
            return None
        return value if self.dialect == "postgres" else value.astimezone(UTC).isoformat()

    @staticmethod
    def _dt(value: Any) -> datetime | None:
        if value is None:
            return None
        return value.astimezone(UTC) if isinstance(value, datetime) else parse_timestamp(value)

    def _exec(self, sql: str, params: tuple = ()) -> Any:
        return self._conn.execute(self._sql(sql), params)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self.dialect == "sqlite":
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")
        else:
            with self._conn.transaction():
                yield

    # -- watermarks --------------------------------------------------------------------
    def committed_until(self, source: str, dataset: str) -> datetime | None:
        row = self._exec("SELECT committed_until FROM {t}watermarks WHERE source=? AND dataset=?",
                         (source, dataset)).fetchone()
        return self._dt(row[0]) if row else None

    def init_watermark(self, source: str, dataset: str, start: datetime, now: datetime) -> None:
        self._exec(
            "INSERT INTO {t}watermarks (source, dataset, committed_until, updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT (source, dataset) DO NOTHING",
            (source, dataset, self._ts(start), self._ts(now)),
        )

    def advance_watermark(self, source: str, dataset: str, now: datetime) -> datetime | None:
        """Move ``committed_until`` forward over contiguous committed/skipped windows."""
        with self.transaction():
            current = self.committed_until(source, dataset)
            if current is None:
                return None
            moved = current
            while True:
                row = self._exec(
                    "SELECT window_end, status FROM {t}window_ledger WHERE source=? AND dataset=? AND window_start=?",
                    (source, dataset, self._ts(moved)),
                ).fetchone()
                if not row or row[1] not in ("bronze_committed", "skipped"):
                    break
                moved = self._dt(row[0])
            if moved != current:
                self._exec("UPDATE {t}watermarks SET committed_until=?, updated_at=? WHERE source=? AND dataset=?",
                           (self._ts(moved), self._ts(now), source, dataset))
            return moved

    def reset_watermark(self, source: str, dataset: str, to: datetime, now: datetime, actor: str, reason: str) -> None:
        with self.transaction():
            self._exec(
                "INSERT INTO {t}watermarks (source, dataset, committed_until, updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT (source, dataset) DO UPDATE SET committed_until=excluded.committed_until, "
                "updated_at=excluded.updated_at",
                (source, dataset, self._ts(to), self._ts(now)),
            )
            self._audit(now, actor, "reset_watermark", source, dataset, to, reason)

    # -- window ledger -----------------------------------------------------------------
    def get_window(self, source: str, dataset: str, window: Window) -> WindowRow | None:
        row = self._exec(
            "SELECT source, dataset, window_start, window_end, status, run_id, attempts, scans, record_count, "
            "quarantined_count, manifest_key, last_error, last_scan_at, updated_at FROM {t}window_ledger "
            "WHERE source=? AND dataset=? AND window_start=?",
            (source, dataset, self._ts(window.start)),
        ).fetchone()
        return self._row(row) if row else None

    def _row(self, row: tuple) -> WindowRow:
        return WindowRow(
            source=row[0], dataset=row[1], window=Window(self._dt(row[2]), self._dt(row[3])), status=row[4],
            run_id=row[5], attempts=row[6], scans=row[7], record_count=row[8], quarantined_count=row[9],
            manifest_key=row[10], last_error=row[11], last_scan_at=self._dt(row[12]), updated_at=self._dt(row[13]),
        )

    def mark_running(self, source: str, dataset: str, window: Window, run_id: str, now: datetime) -> None:
        self._exec(
            "INSERT INTO {t}window_ledger AS wl (source, dataset, window_start, window_end, status, run_id, attempts, "
            "updated_at) VALUES (?,?,?,?, 'running', ?, 1, ?) "
            "ON CONFLICT (source, dataset, window_start) DO UPDATE SET "
            "status=CASE WHEN wl.status IN ('bronze_committed','skipped') THEN wl.status ELSE 'running' END, "
            "run_id=excluded.run_id, attempts=wl.attempts + 1, updated_at=excluded.updated_at",
            (source, dataset, self._ts(window.start), self._ts(window.end), run_id, self._ts(now)),
        )

    def mark_committed(self, source: str, dataset: str, window: Window, run_id: str, *, record_count: int,
                       quarantined_count: int, manifest_key: str, now: datetime) -> None:
        """Commit the window and enqueue its index job atomically."""
        with self.transaction():
            self._exec(
                "UPDATE {t}window_ledger SET status='bronze_committed', run_id=?, scans=scans + 1, record_count=?, "
                "quarantined_count=?, manifest_key=?, last_error=NULL, last_scan_at=?, updated_at=? "
                "WHERE source=? AND dataset=? AND window_start=?",
                (run_id, record_count, quarantined_count, manifest_key, self._ts(now), self._ts(now),
                 source, dataset, self._ts(window.start)),
            )
            self._exec(
                "INSERT INTO {t}outbox (source, dataset, window_start, window_end, run_id, manifest_key, status, "
                "attempts, next_attempt_at, created_at, updated_at) VALUES (?,?,?,?,?,?, 'pending', 0, ?, ?, ?) "
                "ON CONFLICT (source, dataset, window_start, run_id) DO NOTHING",
                (source, dataset, self._ts(window.start), self._ts(window.end), run_id, manifest_key,
                 self._ts(now), self._ts(now), self._ts(now)),
            )

    def mark_failed(self, source: str, dataset: str, window: Window, run_id: str, error: str, now: datetime) -> None:
        # A failed *re-scan* must not demote an already committed window.
        self._exec(
            "UPDATE {t}window_ledger SET status=CASE WHEN status IN ('bronze_committed','skipped') THEN status "
            "ELSE 'failed' END, last_error=?, run_id=?, updated_at=? WHERE source=? AND dataset=? AND window_start=?",
            (error[:2000], run_id, self._ts(now), source, dataset, self._ts(window.start)),
        )

    def mark_skipped(self, source: str, dataset: str, window: Window, now: datetime, actor: str, reason: str) -> None:
        if not reason.strip():
            raise ValueError("a reason is required to skip a window")
        with self.transaction():
            self._exec(
                "INSERT INTO {t}window_ledger (source, dataset, window_start, window_end, status, updated_at, "
                "last_error) VALUES (?,?,?,?, 'skipped', ?, ?) ON CONFLICT (source, dataset, window_start) "
                "DO UPDATE SET status='skipped', last_error=excluded.last_error, updated_at=excluded.updated_at",
                (source, dataset, self._ts(window.start), self._ts(window.end), self._ts(now), f"SKIPPED: {reason}"),
            )
            self._audit(now, actor, "skip_window", source, dataset, window.start, reason)

    def committed_windows_since(self, source: str, dataset: str, since: datetime, limit: int = 1000) -> list[WindowRow]:
        rows = self._exec(
            "SELECT source, dataset, window_start, window_end, status, run_id, attempts, scans, record_count, "
            "quarantined_count, manifest_key, last_error, last_scan_at, updated_at FROM {t}window_ledger "
            "WHERE source=? AND dataset=? AND status='bronze_committed' AND window_end >= ? "
            "ORDER BY window_start LIMIT ?",
            (source, dataset, self._ts(since), limit),
        ).fetchall()
        return [self._row(r) for r in rows]

    def recent_windows(self, source: str | None, since: datetime) -> list[WindowRow]:
        sql = ("SELECT source, dataset, window_start, window_end, status, run_id, attempts, scans, record_count, "
               "quarantined_count, manifest_key, last_error, last_scan_at, updated_at FROM {t}window_ledger "
               "WHERE window_end >= ?")
        params: tuple = (self._ts(since),)
        if source:
            sql += " AND source=?"
            params += (source,)
        sql += " ORDER BY source, dataset, window_start"
        return [self._row(r) for r in self._exec(sql, params).fetchall()]

    # -- outbox ------------------------------------------------------------------------
    def claim_pending(self, now: datetime, limit: int, source: str | None = None) -> list[OutboxItem]:
        sql = ("SELECT id, source, dataset, window_start, window_end, run_id, manifest_key, attempts, status "
               "FROM {t}outbox WHERE status='pending' AND next_attempt_at <= ?")
        params: tuple = (self._ts(now),)
        if source:
            sql += " AND source=?"
            params += (source,)
        # One index process per source (flock/systemd) is the supported topology, so no row locking here.
        sql += " ORDER BY window_start, id LIMIT ?"
        params += (limit,)
        rows = self._exec(sql, params).fetchall()
        return [OutboxItem(id=r[0], source=r[1], dataset=r[2], window=Window(self._dt(r[3]), self._dt(r[4])),
                           run_id=r[5], manifest_key=r[6], attempts=r[7], status=r[8]) for r in rows]

    def outbox_done(self, item_id: int, now: datetime) -> None:
        self._exec("UPDATE {t}outbox SET status='done', last_error=NULL, updated_at=? WHERE id=?",
                   (self._ts(now), item_id))

    def outbox_failed(self, item: OutboxItem, error: str, now: datetime, max_attempts: int) -> str:
        attempts = item.attempts + 1
        status = "dead" if attempts >= max_attempts else "pending"
        delay = timedelta(seconds=min(3600, 30 * (2 ** min(attempts, 10))))
        self._exec(
            "UPDATE {t}outbox SET status=?, attempts=?, last_error=?, next_attempt_at=?, updated_at=? WHERE id=?",
            (status, attempts, error[:2000], self._ts(now + delay), self._ts(now), item.id),
        )
        return status

    def requeue_dead(self, now: datetime, actor: str, reason: str, source: str | None = None) -> int:
        with self.transaction():
            sql = "UPDATE {t}outbox SET status='pending', attempts=0, next_attempt_at=?, updated_at=? WHERE status='dead'"
            params: tuple = (self._ts(now), self._ts(now))
            if source:
                sql += " AND source=?"
                params += (source,)
            count = self._exec(sql, params).rowcount
            self._audit(now, actor, "requeue_dead", source or "*", "*", None, reason)
            return count

    def outbox_counts(self) -> dict[str, int]:
        rows = self._exec("SELECT status, COUNT(*) FROM {t}outbox GROUP BY status").fetchall()
        return {r[0]: r[1] for r in rows}

    # -- runs / audit ------------------------------------------------------------------
    def start_run(self, run_id: str, source: str, stage: str, now: datetime) -> None:
        self._exec("INSERT INTO {t}runs (run_id, source, stage, started_at, status) VALUES (?,?,?,?, 'running')",
                   (run_id, source, stage, self._ts(now)))

    def finish_run(self, run_id: str, status: str, windows: int, records: int, detail: dict, now: datetime) -> None:
        self._exec(
            "UPDATE {t}runs SET finished_at=?, status=?, windows=?, records=?, detail=? WHERE run_id=?",
            (self._ts(now), status, windows, records, json.dumps(detail, default=str)[:8000], run_id),
        )

    def _audit(self, now: datetime, actor: str, action: str, source: str, dataset: str,
               window_start: datetime | None, reason: str) -> None:
        self._exec(
            "INSERT INTO {t}operator_actions (at, actor, action, source, dataset, window_start, reason) "
            "VALUES (?,?,?,?,?,?,?)",
            (self._ts(now), actor, action, source, dataset, self._ts(window_start), reason[:2000]),
        )


def open_state(settings) -> StateStore:
    if settings.state_backend == "postgres":
        return StateStore.postgres(settings.state_database_url)
    return StateStore.sqlite(settings.state_sqlite_path)
