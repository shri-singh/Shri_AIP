"""SearchRouter: the only way the agent (or the REST API) reaches retrieval backends.

Order of checks for every call:
1. route exists (allowlist)                     -> ToolError("unknown_route")
2. arguments parse + validate (pydantic)        -> ToolError("invalid_arguments", <short reason>)
3. permission + service scope                   -> ToolError("denied")
4. budget charge (calls / cost / time)          -> BudgetExceeded (ends the tool loop)
5. run with timeout                             -> ToolError("timeout" | "upstream_unavailable")
6. truncate items, register citations, return

ToolError messages are short and safe to show to the model (they help it retry
with corrected arguments) - no stack traces, hosts or credentials.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from .._shared.errors import BudgetExceeded, UpstreamUnavailable
from .._shared.telemetry import span
from ..rag.citations import CitationRegistry
from .contracts import RouteContext, RouteResult, SearchRoute

log = logging.getLogger(__name__)


class ToolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ToolOutcome:
    route: str
    result: RouteResult
    model_items: list[dict[str, Any]]  # items with "cite" keys, for the model
    citation_keys: list[str]
    latency_ms: int


class SearchRouter:
    def __init__(self) -> None:
        self._routes: dict[str, SearchRoute] = {}

    def register(self, route: SearchRoute) -> None:
        if route.name in self._routes:
            raise ValueError(f"route {route.name} already registered")
        self._routes[route.name] = route

    @property
    def names(self) -> list[str]:
        return sorted(self._routes)

    def has(self, name: str) -> bool:
        return name in self._routes

    def tool_specs(self) -> list[dict[str, Any]]:
        """OpenAI-compatible tool definitions (Portkey translates them for Bedrock)."""
        specs = []
        for route in self._routes.values():
            schema = route.args_model.model_json_schema()
            schema.pop("title", None)
            specs.append({"type": "function", "function": {
                "name": route.name, "description": route.description, "parameters": schema}})
        return specs

    async def execute(self, name: str, raw_args: str | dict[str, Any], ctx: RouteContext,
                      citations: CitationRegistry) -> ToolOutcome:
        route = self._routes.get(name)
        if route is None:
            raise ToolError("unknown_route", f"unknown tool {name!r}; available: {', '.join(self.names)}")
        try:
            data = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            args = route.args_model.model_validate(data)
        except (json.JSONDecodeError, TypeError):
            raise ToolError("invalid_arguments", "arguments must be a JSON object") from None
        except ValidationError as exc:
            reasons = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])
            raise ToolError("invalid_arguments", reasons[:500]) from None
        if not ctx.principal.can(route.permission):
            raise ToolError("denied", f"you are not permitted to use {name}")
        ctx.budget.charge(name, route.cost_units)  # BudgetExceeded propagates to the orchestrator
        started = time.monotonic()
        timeout = max(0.5, min(route.timeout_seconds, ctx.budget.remaining_seconds))
        with span(f"opsi.route {name}", **{"opsi.route": name, "opsi.request_id": ctx.request_id}):
            try:
                result = await asyncio.wait_for(route.run(args, ctx), timeout=timeout)
            except PermissionError as exc:
                raise ToolError("denied", str(exc)[:200]) from None
            except TimeoutError:
                raise ToolError("timeout", f"{name} timed out after {timeout:.0f}s; narrow the time window") from None
            except UpstreamUnavailable as exc:
                raise ToolError("upstream_unavailable", str(exc)[:200]) from None
            except BudgetExceeded:
                raise
            except Exception:  # noqa: BLE001 - never leak internals to the model
                log.exception("route %s failed", name)
                raise ToolError("upstream_unavailable", f"{name} failed; try again later or use another tool") from None
        if len(result.items) > route.max_items:
            result.items = result.items[: route.max_items]
            result.truncated = True
        keys = [citations.add(c) for c in result.citations]
        model_items = []
        for item in result.items:
            item = dict(item)
            idx = item.pop("citation", None)
            if isinstance(idx, int) and 0 <= idx < len(keys):
                item["cite"] = keys[idx]
            model_items.append(item)
        return ToolOutcome(name, result, model_items, keys, int((time.monotonic() - started) * 1000))
