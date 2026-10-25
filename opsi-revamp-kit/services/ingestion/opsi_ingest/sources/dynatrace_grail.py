"""Dynatrace Grail logs via the platform Storage Query API.

Flow (verified against the platform-storage-query-v1 reference, 2026-10):

1. ``POST {DYNATRACE_PLATFORM_URL}/platform/storage/query/v1/query:execute``
   body: ``query``, ``defaultTimeframeStart``, ``defaultTimeframeEnd``,
   ``timezone``, ``locale``, ``maxResultRecords``, ``requestTimeoutMilliseconds``
   (+ optional ``defaultScanLimitGbytes``).
   - HTTP 200: finished within the request timeout; body holds ``state`` and ``result``.
   - HTTP 202: accepted; body holds ``requestToken``; poll.
2. ``GET .../query:poll?request-token=...&request-timeout-milliseconds=...``
   ``state`` is one of NOT_STARTED, RUNNING, SUCCEEDED, RESULT_GONE, CANCELLED, FAILED.
   Results are kept only ~1 minute after completion: poll promptly.
3. On our own timeout: ``POST .../query:cancel?request-token=...`` (best effort).

Completeness: we ask for ``cap + 1`` records. Receiving more than ``cap`` means
the window is too large -> ``WindowTooLarge`` -> the bronze stage splits the
window. Sampled results or WARN/ERROR notifications about limits are also
treated as incomplete. Nothing is ever silently truncated.

The timeframe is passed in the request body (not in the DQL). The configured
DQL must therefore not contain its own ``timeframe:``/``from:``/``to:`` or ``| limit``.
"""
from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterator
from typing import Any

import requests

from ..config import Settings
from ..errors import ConfigError, PermanentSourceError, SourceContractError, TransientSourceError, WindowTooLarge
from ..http import RetryPolicy, request_with_retry
from ..timeutil import iso_z
from ..windows import Window
from .base import FieldMap, SourceRecord
from .dynatrace_auth import DynatraceTokenProvider

log = logging.getLogger(__name__)

API = "/platform/storage/query/v1/"
TERMINAL_FAILURES = {"FAILED", "CANCELLED", "RESULT_GONE"}
_LIMIT_WORDS = re.compile(r"limit|truncat|exceed|sampl", re.I)


def validate_dql(dql: str) -> str:
    text = dql.strip()
    if not text.lower().startswith("fetch "):
        raise ConfigError("DYNATRACE_GRAIL_DQL must start with 'fetch ' (e.g. 'fetch logs | filter ...')")
    first_command = text.split("|", 1)[0]
    if re.search(r"\b(timeframe|from|to)\s*:", first_command, re.I):
        raise ConfigError("DYNATRACE_GRAIL_DQL must not set timeframe/from/to; the collector supplies the window")
    if re.search(r"\|\s*limit\b", text, re.I):
        raise ConfigError("DYNATRACE_GRAIL_DQL must not contain '| limit'; use DYNATRACE_GRAIL_MAX_RECORDS")
    return text


class DynatraceGrailSource:
    name = "dynatrace_grail"
    dataset = "logs"
    window_semantics = "event_time"

    field_map = FieldMap(
        time=("timestamp",),
        severity=("loglevel", "status"),
        status=("status",),
        service=("dt.entity.service", "service.name", "dt.entity.process_group"),
        host=("host.name", "dt.entity.host"),
        trace=("trace_id", "dt.trace_id"),
        title=("log.source",),
        message=("content",),
    )

    def __init__(self, settings: Settings, session: requests.Session | None = None,
                 token_provider: DynatraceTokenProvider | None = None, sleep=time.sleep,
                 clock=time.monotonic) -> None:
        settings.require("dynatrace_platform_url")
        self.settings = settings
        self.base = settings.dynatrace_platform_url + API
        self.dql = validate_dql(settings.dynatrace_grail_dql)
        self.cap = settings.dynatrace_grail_max_records
        self.session = session or requests.Session()
        self.tokens = token_provider or DynatraceTokenProvider(settings, self.session)
        self.policy = RetryPolicy(max_retries=settings.http_max_retries, timeout=settings.http_timeout_seconds)
        self._sleep = sleep
        self._clock = clock

    # -- HTTP helpers -----------------------------------------------------------------
    def _call(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        for attempt in (1, 2):
            headers = {"Authorization": self.tokens.authorization_header(), "Accept": "application/json"}
            if method == "POST":
                headers["Content-Type"] = "application/json"
            try:
                return request_with_retry(self.session, method, self.base + path, policy=self.policy,
                                          sleep=self._sleep, what=f"grail {path}", headers=headers, **kwargs)
            except PermanentSourceError as exc:
                if "HTTP 401" in str(exc) and attempt == 1:
                    self.tokens.invalidate()  # token expired between refresh and use
                    continue
                raise
        raise AssertionError("unreachable")

    def _execute(self, window: Window) -> dict[str, Any]:
        body: dict[str, Any] = {
            "query": f"{self.dql} | sort timestamp asc | limit {self.cap + 1}",
            "defaultTimeframeStart": iso_z(window.start),
            "defaultTimeframeEnd": iso_z(window.end),
            "timezone": "UTC",
            "locale": "en_US",
            "maxResultRecords": self.cap + 1,
            "requestTimeoutMilliseconds": 10_000,
        }
        if self.settings.dynatrace_grail_scan_limit_gbytes:
            body["defaultScanLimitGbytes"] = self.settings.dynatrace_grail_scan_limit_gbytes
        return self._call("POST", "query:execute", json=body).json()

    def _poll(self, token: str) -> dict[str, Any]:
        return self._call("GET", "query:poll",
                          params={"request-token": token, "request-timeout-milliseconds": 10_000}).json()

    def _cancel(self, token: str) -> None:
        try:
            self._call("POST", "query:cancel", params={"request-token": token})
        except Exception:  # noqa: BLE001 - best effort; query expires server-side
            log.warning("grail query:cancel failed (ignored)")

    # -- main ---------------------------------------------------------------------------
    def run_query(self, window: Window) -> dict[str, Any]:
        state = self._execute(window)
        token = state.get("requestToken")
        deadline = self._clock() + self.settings.dynatrace_grail_poll_budget_seconds
        while state.get("state") != "SUCCEEDED":
            status = state.get("state")
            if status in TERMINAL_FAILURES:
                raise TransientSourceError(f"grail query ended with state={status} for window {window}")
            if status not in ("NOT_STARTED", "RUNNING", None):
                raise SourceContractError(f"grail query returned unknown state {status!r}")
            if not token:
                raise SourceContractError("grail query not finished but no requestToken returned")
            if self._clock() > deadline:
                self._cancel(token)
                raise TransientSourceError(
                    f"grail query exceeded DYNATRACE_GRAIL_POLL_BUDGET_SECONDS for window {window}; "
                    "narrow the DQL filter or reduce INGEST_WINDOW_MINUTES"
                )
            state = self._poll(token)
            token = state.get("requestToken", token)
        result = state.get("result")
        if not isinstance(result, dict):
            raise SourceContractError("grail SUCCEEDED without a 'result' object")
        return result

    def fetch(self, window: Window) -> Iterator[SourceRecord]:
        result = self.run_query(window)
        records = result.get("records") or []
        if not isinstance(records, list):
            raise SourceContractError("grail result.records is not a list")
        if len(records) > self.cap:
            raise WindowTooLarge(f"grail window {window} returned > DYNATRACE_GRAIL_MAX_RECORDS={self.cap}")
        grail_meta = ((result.get("metadata") or {}).get("grail") or {})
        if grail_meta.get("sampled"):
            raise WindowTooLarge(f"grail window {window} result is sampled; refusing incomplete data")
        for note in grail_meta.get("notifications") or []:
            severity = str(note.get("severity", "")).upper()
            text = f"{note.get('notificationType', '')} {note.get('message', '')}"
            if severity in ("WARN", "WARNING", "ERROR") and _LIMIT_WORDS.search(text):
                raise WindowTooLarge(f"grail window {window} reported a limit/truncation notification")
        for item in records:
            if not isinstance(item, dict):
                continue
            yield SourceRecord(
                origin_id=None,  # Grail log records carry no guaranteed unique id; content hash is used
                payload=item,
                source_ref=f"grail://logs?timestamp={item.get('timestamp', '')}",
            )

    def close(self) -> None:
        self.session.close()
