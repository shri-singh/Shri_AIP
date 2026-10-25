"""Curated subset for PostgreSQL / OpenSearch (index stage only).

What reaches PostgreSQL (never raw log payloads):
- ``problems``: one row per Dynatrace problem (latest observation wins).
- ``error_signature_windows``: per window x service x fingerprint counts for
  ERROR/CRITICAL log events, with a short redacted sample and its source_ref.
- ``evidence_samples``: up to N example events per signature per window
  (message excerpt + source_ref) so answers can cite exact log lines.

Idempotency: window-scoped tables use *replace* semantics guarded by run order
(``window_index_state``): applying an older run after a newer one is a no-op.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

CURATED_LOG_SEVERITIES = ("CRITICAL", "ERROR")


class CuratedSink(Protocol):
    name: str

    def apply(self, manifest: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, int]: ...


@dataclass
class Signature:
    service_id: str
    fingerprint: str
    severity: str
    count: int
    first_seen: datetime
    last_seen: datetime
    sample_message: str
    sample_ref: str


def aggregate_signatures(rows: list[dict[str, Any]], max_samples: int) -> tuple[list[Signature], list[dict[str, Any]]]:
    """Group ERROR/CRITICAL events by (service, fingerprint). Returns signatures and evidence samples."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("severity") not in CURATED_LOG_SEVERITIES or not row.get("message_fingerprint"):
            continue
        groups[(row.get("service_id") or "", row["message_fingerprint"])].append(row)
    signatures: list[Signature] = []
    samples: list[dict[str, Any]] = []
    for (service_id, fingerprint), events in sorted(groups.items()):
        events.sort(key=lambda r: (r["event_time"], r["event_uid"]))
        worst = "CRITICAL" if any(e["severity"] == "CRITICAL" for e in events) else "ERROR"
        first = events[0]
        signatures.append(Signature(
            service_id=service_id, fingerprint=fingerprint, severity=worst, count=len(events),
            first_seen=first["event_time"], last_seen=events[-1]["event_time"],
            sample_message=(first.get("message") or first.get("title") or "")[:500], sample_ref=first["source_ref"],
        ))
        for event in events[:max_samples]:
            samples.append({
                "event_uid": event["event_uid"], "service_id": service_id, "fingerprint": fingerprint,
                "severity": event["severity"], "event_time": event["event_time"],
                "message_excerpt": (event.get("message") or "")[:1000], "source_ref": event["source_ref"],
                "trace_id": event.get("trace_id"),
            })
    return signatures, samples


def problem_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project Dynatrace problem events to the curated ``problems`` shape (ids only, no free text beyond title)."""
    out = []
    for row in rows:
        payload = json.loads(row["payload_json"]) if row.get("payload_json") else {}
        affected = [e.get("entityId", {}).get("id") for e in payload.get("affectedEntities", []) if isinstance(e, dict)]
        zones = [z.get("name") for z in payload.get("managementZones", []) if isinstance(z, dict)]
        end_ms = payload.get("endTime")
        out.append({
            "problem_id": row["origin_id"],
            "display_id": payload.get("displayId"),
            "title": (payload.get("title") or row.get("message") or "")[:500],
            "status": payload.get("status") or row.get("status"),
            "severity_level": payload.get("severityLevel"),
            "impact_level": payload.get("impactLevel"),
            "start_time": row["event_time"],
            "end_time_ms": end_ms if isinstance(end_ms, int) and end_ms > 0 else None,
            "root_cause_entity_id": (payload.get("rootCauseEntity") or {}).get("entityId", {}).get("id"),
            "affected_entity_ids": [a for a in affected if a],
            "management_zones": [z for z in zones if z],
            "record_version": row["record_version"],
            "evidence_ref": row["source_ref"],
            "observed_at": row["ingest_time"],
        })
    return out


class MemoryCuratedSink:
    """Test double that records what would be written."""

    name = "memory"

    def __init__(self, fail_times: int = 0) -> None:
        self.applied: list[tuple[str, str, int]] = []
        self.fail_times = fail_times

    def apply(self, manifest: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, int]:
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError("simulated PostgreSQL outage")
        self.applied.append((manifest["window_start"], manifest["run_id"], len(rows)))
        return {"rows": len(rows)}
