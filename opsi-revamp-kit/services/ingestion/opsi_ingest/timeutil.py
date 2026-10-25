"""Strict UTC timestamp handling.

Vendors disagree on formats:
- Elasticsearch: ISO-8601 strings, often with ``Z`` and up to nanosecond precision.
- Dynatrace Problems v2: epoch **milliseconds** (``endTime`` is ``-1`` while a problem is open).
- Dynatrace Grail: ISO-8601 strings with nanoseconds (``2026-10-24T10:00:00.123456789Z``).

Python's ``datetime.fromisoformat`` rejects more than 6 fractional digits on older
versions, so fractions are truncated to microseconds before parsing. Naive
timestamps (no offset) are rejected unless the caller explicitly allows them,
because guessing a zone silently corrupts event ordering.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
_FRACTION = re.compile(r"(\.\d+)")
_EPOCH_MS_THRESHOLD = 100_000_000_000  # values above this are milliseconds, not seconds


class TimestampError(ValueError):
    """Raised for missing, naive or unparseable timestamps."""


def utcnow() -> datetime:
    return datetime.now(UTC)


def parse_timestamp(value: object, *, assume_utc_for_naive: bool = False) -> datetime:
    """Return an aware UTC datetime or raise ``TimestampError``.

    Accepts aware datetimes, epoch seconds/milliseconds (int/float or numeric
    strings) and ISO-8601 strings. Never returns "now" for bad input.
    """
    if value is None or value == "":
        raise TimestampError("timestamp missing")
    if isinstance(value, bool):  # bool is an int subclass; never a timestamp
        raise TimestampError("boolean is not a timestamp")
    if isinstance(value, datetime):
        return _require_aware(value, assume_utc_for_naive)
    if isinstance(value, (int, float)):
        return _from_epoch(float(value))
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"-?\d+(\.\d+)?", text):
            return _from_epoch(float(text))
        return _from_iso(text, assume_utc_for_naive)
    raise TimestampError(f"unsupported timestamp type {type(value).__name__}")


def _from_epoch(number: float) -> datetime:
    if number <= 0:
        raise TimestampError("non-positive epoch value")
    seconds = number / 1000.0 if number > _EPOCH_MS_THRESHOLD else number
    try:
        return datetime.fromtimestamp(seconds, UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise TimestampError("epoch value out of range") from exc


def _from_iso(text: str, assume_utc_for_naive: bool) -> datetime:
    normalized = text.replace("Z", "+00:00").replace("z", "+00:00")
    if " " in normalized and "T" not in normalized:
        normalized = normalized.replace(" ", "T", 1)
    match = _FRACTION.search(normalized)
    if match and len(match.group(1)) > 7:  # "." + more than 6 digits
        normalized = normalized.replace(match.group(1), match.group(1)[:7], 1)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise TimestampError("unparseable ISO-8601 timestamp") from exc
    return _require_aware(parsed, assume_utc_for_naive)


def _require_aware(value: datetime, assume_utc_for_naive: bool) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        if not assume_utc_for_naive:
            raise TimestampError("naive timestamp (no UTC offset)")
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_epoch_ms(value: datetime) -> int:
    return int(_require_aware(value, False).timestamp() * 1000)


def iso_z(value: datetime) -> str:
    """``2026-10-24T10:05:00Z`` (microseconds kept only when non-zero)."""
    value = _require_aware(value, False)
    text = value.isoformat().replace("+00:00", "Z")
    return text


def compact_z(value: datetime) -> str:
    """Filesystem/S3-key friendly: ``20261024T100500Z``."""
    return _require_aware(value, False).strftime("%Y%m%dT%H%M%SZ")


def floor_to_grid(value: datetime, step: timedelta) -> datetime:
    """Floor an aware datetime onto a grid anchored at the Unix epoch."""
    value = _require_aware(value, False)
    step_s = int(step.total_seconds())
    if step_s <= 0:
        raise ValueError("grid step must be positive")
    epoch = int(value.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % step_s), UTC)
