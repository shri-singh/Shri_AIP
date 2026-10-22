"""Tiny worker-local watermark store. Single host only; use durable DB for multi-worker."""
import sqlite3
from datetime import datetime, timezone
from .config import STATE_PATH

def _db():
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(STATE_PATH)
    db.execute('CREATE TABLE IF NOT EXISTS watermarks (source TEXT PRIMARY KEY, cursor_utc TEXT NOT NULL)')
    return db

def read(source: str):
    with _db() as db:
        row = db.execute('SELECT cursor_utc FROM watermarks WHERE source=?',(source,)).fetchone()
    return datetime.fromisoformat(row[0]) if row else None

def write(source: str, end: datetime):
    assert end.tzinfo is not None
    with _db() as db:
        db.execute('INSERT INTO watermarks(source,cursor_utc) VALUES (?, ?) '
                   'ON CONFLICT(source) DO UPDATE SET cursor_utc=excluded.cursor_utc',
                   (source,end.astimezone(timezone.utc).isoformat()))
