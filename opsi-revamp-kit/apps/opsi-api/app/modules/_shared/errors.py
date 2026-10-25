"""API error types. Messages are safe to show to the caller (no internals, no secrets)."""
from __future__ import annotations

from fastapi import HTTPException, status


class NotFound(HTTPException):
    """Also used for 'exists but not yours' so callers cannot probe other tenants' ids."""

    def __init__(self, what: str = "resource") -> None:
        super().__init__(status.HTTP_404_NOT_FOUND, f"{what} not found")


class Forbidden(HTTPException):
    def __init__(self, reason: str = "not permitted") -> None:
        super().__init__(status.HTTP_403_FORBIDDEN, reason)


class Unauthorized(HTTPException):
    def __init__(self, reason: str = "authentication required") -> None:
        super().__init__(status.HTTP_401_UNAUTHORIZED, reason, headers={"WWW-Authenticate": "Bearer"})


class BadRequest(HTTPException):
    def __init__(self, reason: str) -> None:
        super().__init__(status.HTTP_400_BAD_REQUEST, reason)


class Conflict(HTTPException):
    def __init__(self, reason: str) -> None:
        super().__init__(status.HTTP_409_CONFLICT, reason)


class BudgetExceeded(Exception):
    """Raised inside the agent loop when a run exceeds tool/cost/time budgets."""


class UpstreamUnavailable(Exception):
    """A retrieval backend (Elastic, OpenMetadata, ...) failed; message is safe for the model/user."""
