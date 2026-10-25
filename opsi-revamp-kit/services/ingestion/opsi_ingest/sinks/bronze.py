"""Bronze writer: Parquet parts + quarantine file + manifest (the commit marker).

Layout (UTC partitions; one ``run=`` folder per scan of a window)::

    {raw}/{source}/dataset={dataset}/dt=YYYY-MM-DD/window={start}_{end}/run={run_id}/part-00000.parquet
    {raw}/{source}/dataset={dataset}/dt=YYYY-MM-DD/window={start}_{end}/run={run_id}/_manifest.json
    {quarantine}/{source}/dataset={dataset}/dt=YYYY-MM-DD/window={start}_{end}/run={run_id}/quarantine-00000.jsonl.gz

Readers must treat a run folder as valid **only if** its ``_manifest.json``
exists and lists the part with a matching SHA-256. Parts without a manifest are
leftovers of a failed attempt and are ignored (and cleaned up best-effort).
When several committed runs exist for one window (final re-scan), the newest
``run_id`` (sortable timestamp prefix) is authoritative.
"""
from __future__ import annotations

import gzip
import io
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

import pyarrow.parquet as pq

from ..contract import MANIFEST_VERSION, SCHEMA_VERSION, table_from_rows
from ..normalize import Quarantined
from ..timeutil import iso_z
from ..windows import Window
from .objectstore import ObjectStore, sha256_hex

log = logging.getLogger(__name__)


@dataclass
class PartInfo:
    key: str
    rows: int
    bytes: int
    sha256: str


@dataclass
class _Segment:
    window: Window
    parts_mark: int
    quarantine_mark: int
    uid_mark: int


@dataclass
class BronzeStats:
    records: int = 0
    quarantined: int = 0
    duplicates: int = 0
    out_of_window: int = 0
    bytes: int = 0
    splits: int = 0
    segments: list[str] = field(default_factory=list)
    quarantine_reasons: dict[str, int] = field(default_factory=dict)


def window_prefix(prefix: str, source: str, dataset: str, window: Window) -> str:
    return f"{prefix}/{source}/dataset={dataset}/dt={window.start:%Y-%m-%d}/window={window.key}"


class BronzeWriter:
    def __init__(self, store: ObjectStore, *, raw_prefix: str, quarantine_prefix: str, tenant_id: str,
                 source: str, dataset: str, window: Window, run_id: str, classification: str,
                 part_max_rows: int) -> None:
        self.store = store
        self.tenant_id = tenant_id
        self.source = source
        self.dataset = dataset
        self.window = window
        self.run_id = run_id
        self.classification = classification
        self.part_max_rows = part_max_rows
        self.base = window_prefix(raw_prefix, source, dataset, window) + f"/run={run_id}"
        self.qbase = window_prefix(quarantine_prefix, source, dataset, window) + f"/run={run_id}"
        self.buffer: list[dict[str, Any]] = []
        self.parts: list[PartInfo] = []
        self.quarantine: list[dict[str, Any]] = []
        self.seen: set[str] = set()
        self.uid_log: list[str] = []
        self.stats = BronzeStats()
        self._segment: _Segment | None = None
        self._committed = False

    # -- segments (sub-windows after a split) ---------------------------------------------
    def begin_segment(self, window: Window) -> None:
        self._flush()  # align segment start with a part boundary so rollback is exact
        self._segment = _Segment(window, len(self.parts), len(self.quarantine), len(self.uid_log))

    def rollback_segment(self) -> None:
        seg = self._segment
        if seg is None:
            return
        for part in self.parts[seg.parts_mark:]:
            self._safe_delete(part.key)
        self.parts = self.parts[: seg.parts_mark]
        self.quarantine = self.quarantine[: seg.quarantine_mark]
        for uid in self.uid_log[seg.uid_mark:]:
            self.seen.discard(uid)
        self.uid_log = self.uid_log[: seg.uid_mark]
        self.buffer = []
        self.stats.splits += 1
        self._segment = None

    def end_segment(self) -> None:
        if self._segment is not None:
            self.stats.segments.append(str(self._segment.window))
        self._segment = None

    # -- rows ------------------------------------------------------------------------------
    def add(self, item: dict[str, Any] | Quarantined) -> None:
        if isinstance(item, Quarantined):
            self.quarantine.append(asdict(item))
            return
        uid = item["event_uid"]
        if uid in self.seen:
            self.stats.duplicates += 1
            return
        self.seen.add(uid)
        self.uid_log.append(uid)
        self.buffer.append(item)
        if len(self.buffer) >= self.part_max_rows:
            self._flush()

    def _flush(self) -> None:
        if not self.buffer:
            return
        table = table_from_rows(self.buffer)
        sink = io.BytesIO()
        pq.write_table(table, sink, compression="snappy")
        data = sink.getvalue()
        key = f"{self.base}/part-{len(self.parts):05d}.parquet"
        digest = sha256_hex(data)
        self.store.put(key, data, content_type="application/vnd.apache.parquet", metadata={
            "schema-version": SCHEMA_VERSION, "record-count": str(len(self.buffer)), "sha256": digest,
            "run-id": self.run_id, "classification": self.classification, "source": self.source,
        })
        self.parts.append(PartInfo(key, len(self.buffer), len(data), digest))
        self.buffer = []

    # -- commit / abort ---------------------------------------------------------------------
    def commit(self, *, created_at: datetime, scan_kind: str, collector_version: str,
               source_stats: dict[str, Any] | None = None) -> str:
        if self._committed:
            raise RuntimeError("writer already committed")
        self._flush()
        quarantine_files: list[dict[str, Any]] = []
        if self.quarantine:
            lines = "\n".join(json.dumps(q, ensure_ascii=False, default=str) for q in self.quarantine)
            data = gzip.compress(lines.encode("utf-8"), mtime=0)
            qkey = f"{self.qbase}/quarantine-00000.jsonl.gz"
            self.store.put(qkey, data, content_type="application/gzip", metadata={
                "schema-version": SCHEMA_VERSION, "record-count": str(len(self.quarantine)),
                "run-id": self.run_id, "classification": self.classification,
            })
            quarantine_files.append({"key": qkey, "rows": len(self.quarantine), "sha256": sha256_hex(data)})
        reasons: dict[str, int] = {}
        for q in self.quarantine:
            reasons[q["reason"]] = reasons.get(q["reason"], 0) + 1
        self.stats.records = sum(p.rows for p in self.parts)
        self.stats.quarantined = len(self.quarantine)
        self.stats.out_of_window = reasons.get("event_outside_window", 0)
        self.stats.bytes = sum(p.bytes for p in self.parts)
        self.stats.quarantine_reasons = reasons
        manifest = {
            "manifest_version": MANIFEST_VERSION,
            "schema_version": SCHEMA_VERSION,
            "status": "committed",
            "tenant_id": self.tenant_id,
            "source": self.source,
            "dataset": self.dataset,
            "window_start": iso_z(self.window.start),
            "window_end": iso_z(self.window.end),
            "run_id": self.run_id,
            "scan_kind": scan_kind,
            "created_at": iso_z(created_at),
            "collector_version": collector_version,
            "classification": self.classification,
            "record_count": self.stats.records,
            "quarantined_count": self.stats.quarantined,
            "duplicate_count": self.stats.duplicates,
            "quarantine_reasons": reasons,
            "splits": self.stats.splits,
            "segments": self.stats.segments,
            "parts": [asdict(p) for p in self.parts],
            "quarantine": quarantine_files,
            "source_stats": source_stats or {},
        }
        key = f"{self.base}/_manifest.json"
        self.store.put(key, json.dumps(manifest, indent=1, sort_keys=True).encode("utf-8"),
                       content_type="application/json",
                       metadata={"schema-version": SCHEMA_VERSION, "run-id": self.run_id, "status": "committed"})
        self._committed = True
        return key

    def abort(self) -> None:
        """Best-effort cleanup of parts written by a failed attempt (no manifest => ignored anyway)."""
        if self._committed:
            return
        for part in self.parts:
            self._safe_delete(part.key)
        self.parts = []
        self.buffer = []

    def _safe_delete(self, key: str) -> None:
        try:
            self.store.delete(key)
        except Exception:  # noqa: BLE001 - orphans are harmless without a manifest
            log.warning("could not delete orphan part %s", key)


def load_manifest(store: ObjectStore, key: str) -> dict[str, Any]:
    manifest = json.loads(store.get(key))
    if manifest.get("status") != "committed" or manifest.get("manifest_version") != MANIFEST_VERSION:
        raise ValueError(f"manifest {key} is not a committed v{MANIFEST_VERSION} manifest")
    return manifest


def read_manifest_rows(store: ObjectStore, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Read all parts listed by a manifest, verifying each checksum first."""
    rows: list[dict[str, Any]] = []
    for part in manifest.get("parts", []):
        data = store.get(part["key"])
        if sha256_hex(data) != part["sha256"]:
            raise ValueError(f"checksum mismatch for {part['key']}: object changed or is corrupt")
        rows.extend(pq.read_table(io.BytesIO(data)).to_pylist())
    return rows
