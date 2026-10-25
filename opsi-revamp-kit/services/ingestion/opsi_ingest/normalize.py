"""Turn vendor records into ``opsi.event.v1`` rows or quarantine entries.

Never invents data: a record without a usable timestamp is quarantined with a
reason code. Payloads are redacted *before* they are hashed, stored or sized.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .contract import SCHEMA_VERSION
from .redaction import Redactor
from .sources.base import FieldMap, SourceRecord, WindowSemantics, first_value
from .timeutil import TimestampError, parse_timestamp
from .windows import Window

_SEVERITY_MAP = {
    "CRITICAL": "CRITICAL", "FATAL": "CRITICAL", "EMERGENCY": "CRITICAL", "ALERT": "CRITICAL", "SEVERE": "CRITICAL",
    "AVAILABILITY": "CRITICAL",  # Dynatrace severityLevel
    "ERROR": "ERROR", "ERR": "ERROR", "FAILURE": "ERROR",
    "PERFORMANCE": "WARN", "RESOURCE_CONTENTION": "WARN", "CUSTOM_ALERT": "WARN", "MONITORING_UNAVAILABLE": "WARN",
    "WARN": "WARN", "WARNING": "WARN",
    "INFO": "INFO", "INFORMATION": "INFO", "NOTICE": "INFO",
    "DEBUG": "DEBUG", "TRACE": "DEBUG",
}

_FINGERPRINT_RULES = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<ip>"),
    (re.compile(r"\b0x[0-9a-f]+\b|\b[0-9a-f]{12,}\b", re.I), "<hex>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ][\d:.]+(?:Z|[+-]\d{2}:?\d{2})?"), "<ts>"),
    (re.compile(r"\"[^\"]{0,200}\"|'[^']{0,200}'"), "<str>"),
    (re.compile(r"\b\d+\b"), "<n>"),
    (re.compile(r"\s+"), " "),
]


def normalize_severity(raw: Any) -> str:
    if raw is None:
        return "UNKNOWN"
    return _SEVERITY_MAP.get(str(raw).strip().upper(), "UNKNOWN")


def message_fingerprint(message: str) -> str:
    """Stable error-signature id: masks ids, numbers, IPs, quoted values, timestamps."""
    text = message[:1000]
    for pattern, replacement in _FINGERPRINT_RULES:
        text = pattern.sub(replacement, text)
    return hashlib.sha1(text.strip().lower().encode("utf-8"), usedforsecurity=False).hexdigest()[:16]


def stable_event_uid(tenant_id: str, source: str, dataset: str, origin_id: str) -> str:
    return hashlib.sha256(f"{tenant_id}\x1f{source}\x1f{dataset}\x1f{origin_id}".encode()).hexdigest()


@dataclass
class Quarantined:
    reason: str
    detail: str
    source_ref: str
    origin_id: str | None
    payload_json: str  # redacted


@dataclass
class NormalizeContext:
    tenant_id: str
    source: str
    dataset: str
    window: Window  # the grid window written into every row
    run_id: str
    ingest_time: datetime
    classification: str
    message_max_chars: int
    payload_max_bytes: int
    window_semantics: WindowSemantics
    field_map: FieldMap
    bounds: Window | None = None  # sub-window being fetched after a split; defaults to ``window``


def normalize(record: SourceRecord, ctx: NormalizeContext, redactor: Redactor) -> dict[str, Any] | Quarantined:
    if not isinstance(record.payload, dict):
        return Quarantined("payload_not_object", type(record.payload).__name__, record.source_ref, record.origin_id, "{}")

    payload_json, redaction_hits = redactor.redact_json(record.payload)
    payload_bytes = payload_json.encode("utf-8")
    truncated = len(payload_bytes) > ctx.payload_max_bytes
    if truncated:
        payload_json = json.dumps(
            {"_opsi_truncated": True, "original_bytes": len(payload_bytes),
             "head": payload_bytes[: ctx.payload_max_bytes // 2].decode("utf-8", "ignore")},
            ensure_ascii=False,
        )
    payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

    raw_time = first_value(record.payload, ctx.field_map.time)
    try:
        event_time = parse_timestamp(raw_time)
    except TimestampError as exc:
        reason = (
            "timestamp_missing" if raw_time in (None, "")
            else "timestamp_naive" if "naive" in str(exc)
            else "timestamp_invalid"
        )
        return Quarantined(reason, str(exc), record.source_ref, record.origin_id, payload_json)

    if ctx.window_semantics == "event_time" and not (ctx.bounds or ctx.window).contains(event_time):
        return Quarantined("event_outside_window", f"event_time={event_time.isoformat()}", record.source_ref,
                           record.origin_id, payload_json)

    origin_id = record.origin_id or f"sha256:{payload_sha256}"

    def text(paths: tuple[str, ...], limit: int) -> str | None:
        nonlocal redaction_hits
        value = first_value(record.payload, paths)
        if value is None:
            return None
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (dict, list)) else str(value)
        redacted = redactor.redact_text(value)
        redaction_hits += redacted.hits
        return redacted.text[:limit]

    severity_raw = text(ctx.field_map.severity, 64)
    message = text(ctx.field_map.message, ctx.message_max_chars) or ""
    title = text(ctx.field_map.title, 500)

    return {
        "schema_version": SCHEMA_VERSION,
        "tenant_id": ctx.tenant_id,
        "source": ctx.source,
        "dataset": ctx.dataset,
        "origin_id": origin_id,
        "event_uid": stable_event_uid(ctx.tenant_id, ctx.source, ctx.dataset, origin_id),
        "record_version": payload_sha256[:32],
        "event_time": event_time,
        "ingest_time": ctx.ingest_time,
        "window_start": ctx.window.start,
        "window_end": ctx.window.end,
        "run_id": ctx.run_id,
        "severity": normalize_severity(severity_raw),
        "severity_raw": severity_raw,
        "status": text(ctx.field_map.status, 64),
        "service_id": text(ctx.field_map.service, 256),
        "host_id": text(ctx.field_map.host, 256),
        "trace_id": text(ctx.field_map.trace, 128),
        "title": title,
        "message": message,
        "message_fingerprint": message_fingerprint(message or title or "") if (message or title) else None,
        "classification": ctx.classification,
        "source_ref": record.source_ref,
        "redaction_hits": int(redaction_hits),
        "payload_json": payload_json,
        "payload_truncated": truncated,
        "payload_sha256": payload_sha256,
    }
