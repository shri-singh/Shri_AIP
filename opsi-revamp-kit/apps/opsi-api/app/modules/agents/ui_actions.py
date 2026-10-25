"""Allowlisted UI actions ("frontend tools") the agent may ask the browser to perform.

The same names must be registered in React with ``useFrontendTool`` /
``useHumanInTheLoop`` (apps/opsi-web/src/features/chat-v2/uiActions.tsx). The
server validates every proposed call *before* streaming it to the browser:
unknown names and invalid arguments never reach the client; they go back to the
model as tool errors so it can correct itself.

Nothing here can execute code. ``render_chart`` carries a declarative
``ChartSpec`` (data + labels) that the frontend maps to ECharts options itself;
no JavaScript, HTML or formatter functions are accepted from the model.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ..identity.principal import Principal

_SAFE_TEXT = re.compile(r"^[^<>{}`\\]*$")  # no markup, template braces or escapes in labels
_ID = r"^[A-Za-z0-9_.:\-/]{1,200}$"


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _safe(value: str | None) -> str | None:
    if value is not None and not _SAFE_TEXT.match(value):
        raise ValueError("text must not contain markup or template characters")
    return value


class ChartSeries(_Args):
    name: str = Field(max_length=80)
    type: Literal["line", "bar", "area", "scatter"] = "line"
    points: list[tuple[str | float, float | None]] = Field(max_length=2000,
                                                           description="[x, y] pairs; x is ISO time or category")

    @field_validator("name")
    @classmethod
    def _label(cls, value: str) -> str:
        return _safe(value)


class ChartSpec(_Args):
    kind: Literal["timeseries", "category"]
    title: str = Field(max_length=120)
    x_label: str | None = Field(default=None, max_length=60)
    y_label: str | None = Field(default=None, max_length=60)
    unit: str | None = Field(default=None, max_length=20)
    series: list[ChartSeries] = Field(min_length=1, max_length=10)
    citations: list[str] = Field(default_factory=list, max_length=20, description="citation keys backing the data, e.g. c3")

    @field_validator("title", "x_label", "y_label", "unit")
    @classmethod
    def _labels(cls, value: str | None) -> str | None:
        return _safe(value)

    @field_validator("citations")
    @classmethod
    def _keys(cls, value: list[str]) -> list[str]:
        if any(not re.fullmatch(r"c\d{1,4}", v) for v in value):
            raise ValueError("citations must be keys like c3")
        return value


class OpenIncidentArgs(_Args):
    incident_id: str = Field(pattern=_ID, description="Incident/problem id to open in the Opsi UI")


class SetDashboardFilterArgs(_Args):
    panel_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_\-]{1,64}$")
    service_id: str | None = Field(default=None, pattern=_ID)
    severity: Literal["CRITICAL", "ERROR", "WARN", "INFO"] | None = None
    environment: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_\-]{1,40}$")
    time_from: datetime | None = None
    time_to: datetime | None = None

    @model_validator(mode="after")
    def _window(self) -> SetDashboardFilterArgs:
        if (self.time_from is None) != (self.time_to is None):
            raise ValueError("time_from and time_to must be set together")
        if self.time_from and self.time_to:
            if self.time_from >= self.time_to or self.time_to - self.time_from > timedelta(days=30):
                raise ValueError("time window must be positive and at most 30 days")
        if not any([self.service_id, self.severity, self.environment, self.time_from]):
            raise ValueError("at least one filter must be set")
        return self


class RenderChartArgs(_Args):
    chart: ChartSpec


class HighlightGraphArgs(_Args):
    entity_keys: list[str] = Field(min_length=1, max_length=50)


class DraftIncidentUpdateArgs(_Args):
    incident_id: str = Field(pattern=_ID)
    summary: str = Field(min_length=10, max_length=4000, description="Proposed update text for human review")
    citations: list[str] = Field(default_factory=list, max_length=20)


@dataclass(frozen=True)
class UiAction:
    name: str
    description: str
    args_model: type[_Args]
    permission: str
    requires_approval: bool = False

    def tool_spec(self) -> dict[str, Any]:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": schema}}


UI_ACTIONS: dict[str, UiAction] = {a.name: a for a in [
    UiAction("open_incident", "Open an incident page in the user's Opsi UI.", OpenIncidentArgs, "chat:use"),
    UiAction("set_dashboard_filter", "Change filters (service, severity, environment, time range) on the "
             "dashboard the user is viewing.", SetDashboardFilterArgs, "chat:use"),
    UiAction("render_chart", "Show a chart in the chat from data you retrieved with tools. Data only.",
             RenderChartArgs, "chat:use"),
    UiAction("highlight_graph_nodes", "Highlight entities in the incident dependency graph view.",
             HighlightGraphArgs, "chat:use"),
    UiAction("draft_incident_update", "Propose an incident update. A human must approve it before anything "
             "is saved.", DraftIncidentUpdateArgs, "action:request", requires_approval=True),
]}


class ActionRejected(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def validate_ui_action(name: str, raw_args: str | dict[str, Any], principal: Principal) -> dict[str, Any]:
    action = UI_ACTIONS.get(name)
    if action is None:
        raise ActionRejected("unknown_action", f"unknown UI action {name!r}")
    if not principal.can(action.permission):
        raise ActionRejected("denied", f"you are not permitted to use {name}")
    try:
        data = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        args = action.args_model.model_validate(data)
    except (json.JSONDecodeError, TypeError):
        raise ActionRejected("invalid_arguments", "arguments must be a JSON object") from None
    except ValidationError as exc:
        reasons = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])
        raise ActionRejected("invalid_arguments", reasons[:500]) from None
    service = getattr(args, "service_id", None)
    if service and not principal.can_access_service(service):
        raise ActionRejected("denied", "service outside your access scope")
    return args.model_dump(mode="json", exclude_none=True)


def approval_expiry(minutes: int = 15) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)
