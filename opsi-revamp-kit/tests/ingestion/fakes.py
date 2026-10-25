"""Shared fakes for ingestion tests. No network, no AWS, no database."""
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from opsi_ingest.errors import WindowTooLarge
from opsi_ingest.sources.base import FieldMap, SourceRecord
from opsi_ingest.windows import Window

FIXTURES = Path(__file__).resolve().parents[2] / "services" / "ingestion" / "fixtures"
UTC = timezone.utc


def fixture_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def make_response(status: int, body: Any = None, headers: dict[str, str] | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(body if body is not None else {}).encode()
    response.headers.update(headers or {})
    response.headers.setdefault("Content-Type", "application/json")
    return response


class ScriptedSession(requests.Session):
    """Returns queued responses in order and records every request (method, url, params, json, data, headers)."""

    def __init__(self, responses: list[requests.Response | Exception]) -> None:
        super().__init__()
        self.queue = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(self, method, url, **kwargs):  # type: ignore[override]
        self.calls.append({"method": method, "url": url, **kwargs})
        if not self.queue:
            raise AssertionError(f"unexpected extra request {method} {url}")
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class ListSource:
    """In-memory event_time source. ``cap`` simulates a vendor result limit."""

    name = "synthetic"
    dataset = "logs"
    window_semantics = "event_time"
    field_map = FieldMap(time=("ts",), severity=("level",), service=("svc",), message=("msg",))

    def __init__(self, events: list[dict[str, Any]], cap: int | None = None, fail_on_call: int | None = None) -> None:
        self.events = events
        self.cap = cap
        self.calls: list[Window] = []
        self.fail_on_call = fail_on_call

    def fetch(self, window: Window) -> Iterator[SourceRecord]:
        self.calls.append(window)
        if self.fail_on_call is not None and len(self.calls) == self.fail_on_call:
            raise ConnectionError("simulated source outage")
        matching = [e for e in self.events if window.start <= e["_dt"] < window.end]
        if self.cap is not None and len(matching) > self.cap:
            # like Grail: we learn about the overflow only after reading cap+1
            for e in matching[: self.cap]:
                yield SourceRecord(e["id"], {k: v for k, v in e.items() if k != "_dt"}, f"synthetic://{e['id']}")
            raise WindowTooLarge("cap exceeded")
        for e in matching:
            yield SourceRecord(e["id"], {k: v for k, v in e.items() if k != "_dt"}, f"synthetic://{e['id']}")

    def close(self) -> None:
        pass


def event(eid: str, at: datetime, level: str = "ERROR", svc: str = "checkout", msg: str | None = None) -> dict:
    return {"id": eid, "_dt": at, "ts": at.isoformat().replace("+00:00", "Z"), "level": level, "svc": svc,
            "msg": msg or f"order {eid} failed with code 500"}


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs) -> None:
        self.now += timedelta(**kwargs)
