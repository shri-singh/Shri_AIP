"""Application-aware context from the browser - a HINT, never identity or authorization.

React sends it with ``useAgentContext({description: "opsi.ui_context", value: {...}})``,
which arrives in ``RunAgentInput.context`` as ``{description, value: <json string>}``.
Only that one entry is read; it is size-limited and validated against an allowlist
of fields. ``tenant_id``/``user_id`` fields are rejected outright, and referenced
services are checked against the caller's scope.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..identity.principal import Principal

CONTEXT_KEY = "opsi.ui_context"
MAX_CONTEXT_BYTES = 8_192


class OpsiUiContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: Literal["dashboard", "incident", "services", "metadata", "settings", "chat", "graph", "reports"]
    incident_id: str | None = Field(default=None, max_length=200)
    service_id: str | None = Field(default=None, max_length=200)
    time_from: datetime | None = None
    time_to: datetime | None = None
    selected_panel_id: str | None = Field(default=None, max_length=64)
    selected_chart_id: str | None = Field(default=None, max_length=64)
    filters: dict[str, str] = Field(default_factory=dict, max_length=10)


def extract_ui_context(context_entries: list[Any] | None, principal: Principal) -> tuple[dict[str, Any], list[str]]:
    """Return (validated_context_dict, warnings). Invalid context is dropped, not fatal."""
    warnings: list[str] = []
    for entry in context_entries or []:
        description = getattr(entry, "description", None) if not isinstance(entry, dict) else entry.get("description")
        value = getattr(entry, "value", None) if not isinstance(entry, dict) else entry.get("value")
        if description != CONTEXT_KEY:
            continue
        if not isinstance(value, str) or len(value.encode()) > MAX_CONTEXT_BYTES:
            return {}, ["ui context ignored: missing or too large"]
        try:
            parsed = json.loads(value)
            ctx = OpsiUiContext.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError):
            return {}, ["ui context ignored: failed validation"]
        if any(len(k) > 40 or len(v) > 200 for k, v in ctx.filters.items()):
            return {}, ["ui context ignored: filter too long"]
        if ctx.service_id and not principal.can_access_service(ctx.service_id):
            warnings.append("ui context service outside caller scope was removed")
            ctx = ctx.model_copy(update={"service_id": None})
        return ctx.model_dump(mode="json", exclude_none=True), warnings
    return {}, warnings
