"""Contracts shared by every retrieval route.

A route is a typed, read-only, budgeted tool. The LLM may *choose* a route and
fill its arguments; the server validates the arguments (pydantic), checks
permissions and service scope, clamps time windows, charges the run budget and
attaches citations. The model never sees credentials, index names or SQL.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .._shared.errors import BudgetExceeded
from ..identity.principal import Principal

UTC = timezone.utc


class Citation(BaseModel):
    source_type: str  # elastic_log | grail_log | dynatrace_problem | error_signature | om_entity | ontology | runbook | sql_aggregate
    source_ref: str
    title: str | None = None
    event_time: datetime | None = None
    snippet: str | None = Field(default=None, max_length=1000)
    url: str | None = None


class RouteResult(BaseModel):
    route: str
    items: list[dict[str, Any]] = Field(default_factory=list)  # each item may carry "citation": Citation index
    citations: list[Citation] = Field(default_factory=list)
    truncated: bool = False
    total_hint: int | None = None
    notes: list[str] = Field(default_factory=list)  # safe, model-facing notes ("time window clamped to 24h")
    chart_hint: dict[str, Any] | None = None


class RouteArgs(BaseModel):
    """Base for route arguments: unknown fields are rejected (the model cannot smuggle tenant ids)."""

    model_config = ConfigDict(extra="forbid")


class TimeWindowArgs(RouteArgs):
    time_from: datetime = Field(description="UTC start (ISO-8601, inclusive)")
    time_to: datetime = Field(description="UTC end (ISO-8601, exclusive)")

    MAX_SPAN: ClassVar[timedelta] = timedelta(hours=24)

    @model_validator(mode="after")
    def _check_window(self) -> TimeWindowArgs:
        for name in ("time_from", "time_to"):
            value = getattr(self, name)
            if value.tzinfo is None:
                setattr(self, name, value.replace(tzinfo=UTC))
        if self.time_from >= self.time_to:
            raise ValueError("time_from must be before time_to")
        if self.time_to > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("time_to is in the future")
        if self.time_to - self.time_from > self.MAX_SPAN:
            raise ValueError(f"time window exceeds the maximum of {self.MAX_SPAN}")
        return self


@dataclass
class RunBudget:
    max_calls: int
    max_cost: float
    max_seconds: float
    calls: int = 0
    cost: float = 0.0
    started: float = field(default_factory=time.monotonic)

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.max_seconds - (time.monotonic() - self.started))

    def charge(self, route: str, cost: float) -> None:
        if self.calls + 1 > self.max_calls:
            raise BudgetExceeded(f"tool-call budget exhausted ({self.max_calls} calls) before {route}")
        if self.cost + cost > self.max_cost:
            raise BudgetExceeded(f"cost budget exhausted ({self.max_cost} units) before {route}")
        if self.remaining_seconds <= 0:
            raise BudgetExceeded("time budget exhausted")
        self.calls += 1
        self.cost += cost


@dataclass
class RouteContext:
    principal: Principal
    budget: RunBudget
    request_id: str | None = None
    ui_context: dict[str, Any] = field(default_factory=dict)


class SearchRoute(Protocol):
    name: str
    description: str
    args_model: type[RouteArgs]
    permission: str
    cost_units: float
    timeout_seconds: float
    max_items: int

    async def run(self, args: Any, ctx: RouteContext) -> RouteResult: ...


def scoped_services(principal: Principal, requested: str | None) -> list[str] | None:
    """Return the service filter to apply. None = no filter (unrestricted principal, no request).

    Raises PermissionError when a restricted principal asks for a service outside its scope.
    """
    if requested is not None:
        if not principal.can_access_service(requested):
            raise PermissionError("service outside your access scope")
        return [requested]
    if principal.service_scope is None:
        return None
    if not principal.service_scope:
        raise PermissionError("no services in your access scope")
    return sorted(principal.service_scope)
