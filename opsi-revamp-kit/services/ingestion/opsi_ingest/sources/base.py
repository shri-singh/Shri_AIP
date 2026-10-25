"""Source adapter contract.

An adapter only *reads*. It yields ``SourceRecord`` objects for one window
and raises ``WindowTooLarge`` instead of truncating. Adapters never write
state, never log payloads and never log credentials.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from ..windows import Window

WindowSemantics = Literal["event_time", "overlap_snapshot"]


@dataclass(frozen=True)
class FieldMap:
    """Dotted paths tried in order; the first non-empty value wins.

    Keys containing dots (e.g. Dynatrace ``dt.entity.service``) are tried as a
    literal key first, then as a nested path.
    """

    time: tuple[str, ...]
    severity: tuple[str, ...] = ()
    status: tuple[str, ...] = ()
    service: tuple[str, ...] = ()
    host: tuple[str, ...] = ()
    trace: tuple[str, ...] = ()
    title: tuple[str, ...] = ()
    message: tuple[str, ...] = ()


@dataclass
class SourceRecord:
    origin_id: str | None  # vendor's stable id; None -> content hash is used
    payload: dict[str, Any]
    source_ref: str  # citation pointer back to the vendor record (no secrets)
    extras: dict[str, Any] = field(default_factory=dict)


class Source(Protocol):
    name: str
    dataset: str
    window_semantics: WindowSemantics
    field_map: FieldMap

    def fetch(self, window: Window) -> Iterator[SourceRecord]:
        """Yield records for ``[window.start, window.end)``; raise WindowTooLarge rather than truncate."""
        ...

    def close(self) -> None: ...


def get_path(payload: dict[str, Any], path: str) -> Any:
    """Literal key first, then a dotted path; numeric parts index into lists (``affectedEntities.0.name``)."""
    if path in payload:
        return payload[path]
    node: Any = payload
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        else:
            return None
    return node


def first_value(payload: dict[str, Any], paths: tuple[str, ...]) -> Any:
    for path in paths:
        value = get_path(payload, path)
        if value not in (None, "", [], {}):
            return value
    return None
