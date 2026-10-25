"""Broadcom DX Operational Intelligence (OI) - deliberate stub.

The master prompt forbids inventing vendor response structures. OI APIs and
authentication differ per installation (SaaS vs on-prem, tenant, version), so
this adapter fails loudly until the contract is verified.

To implement (docs/handbook/FAQ.md "How do I add a new source?"):
1. Obtain the OI API reference for *your* installation and a read-only service account.
2. Capture 3+ real responses (redacted) into ``fixtures/broadcom_oi/`` and write
   contract tests against them first (``tests/ingestion/test_contract_fixtures.py``).
3. Implement ``fetch`` with time-bounded pagination and ``WindowTooLarge`` on caps.
4. Register it in ``sources/__init__.py`` and add it to ``INGEST_ENABLED_SOURCES``.
"""
from __future__ import annotations

from collections.abc import Iterator

from ..config import Settings
from ..errors import NotImplementedSource
from ..windows import Window
from .base import FieldMap, SourceRecord


class BroadcomOISource:
    name = "broadcom_oi"
    dataset = "alarms"
    window_semantics = "event_time"
    field_map = FieldMap(time=("TODO_verify_timestamp_field",))

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def fetch(self, window: Window) -> Iterator[SourceRecord]:
        raise NotImplementedSource(
            "broadcom_oi adapter is a stub: verify the OI API contract for your installation, "
            "add redacted fixtures and contract tests, then implement fetch()."
        )
        yield  # pragma: no cover - makes this a generator for interface parity

    def close(self) -> None:
        return None
