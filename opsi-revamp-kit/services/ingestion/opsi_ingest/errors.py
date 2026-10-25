"""Typed failures. Messages must never contain credentials or raw payloads."""


class IngestError(Exception):
    """Base class for collector errors."""


class ConfigError(IngestError):
    """A required setting is missing or invalid. Fix .env; retrying will not help."""


class TransientSourceError(IngestError):
    """Network/429/5xx after retries were exhausted. Safe to retry the window later."""


class PermanentSourceError(IngestError):
    """401/403/400 etc. Credentials, scopes or query are wrong; retrying will not help."""


class SourceContractError(IngestError):
    """The vendor response did not match the shape this adapter was written against."""


class WindowTooLarge(IngestError):
    """The source returned (or would return) more records than the per-window cap.

    The bronze stage reacts by splitting the window in half, down to
    ``INGEST_MIN_SPLIT_SECONDS``. It never silently truncates.
    """


class NotImplementedSource(IngestError):
    """Adapter is a deliberate stub until the vendor contract is verified."""
