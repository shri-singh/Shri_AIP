"""sql_aggregation: named, parameterised aggregate queries over curated tables. No free-form SQL."""
from __future__ import annotations

from datetime import timedelta
from typing import ClassVar, Literal

from pydantic import Field

from ..contracts import Citation, RouteContext, RouteResult, TimeWindowArgs, scoped_services
from ..stores import IncidentStore

Template = Literal["error_counts_by_service", "top_error_signatures", "error_trend_hourly", "problems_by_status"]


class SqlAggregationArgs(TimeWindowArgs):
    template: Template = Field(description="Which predefined aggregate to run")
    service_id: str | None = Field(default=None, max_length=200)
    limit: int = Field(default=20, ge=1, le=200)

    MAX_SPAN: ClassVar[timedelta] = timedelta(days=30)


class SqlAggregationRoute:
    name = "sql_aggregation"
    description = ("Run a predefined aggregate over curated data (max 30 days): error_counts_by_service, "
                   "top_error_signatures, error_trend_hourly (good for a chart), problems_by_status.")
    args_model = SqlAggregationArgs
    permission = "search:use"
    cost_units = 2.0
    timeout_seconds = 15.0
    max_items = 200

    def __init__(self, store: IncidentStore) -> None:
        self.store = store

    async def run(self, args: SqlAggregationArgs, ctx: RouteContext) -> RouteResult:
        services = scoped_services(ctx.principal, args.service_id)
        rows = await self.store.aggregate(ctx.principal, args.template, services, args.time_from, args.time_to,
                                          args.limit)
        ref = (f"sql://opsi_ingest/{args.template}?from={args.time_from.isoformat()}&to={args.time_to.isoformat()}"
               f"&service={args.service_id or '*'}")
        citations = [Citation(source_type="sql_aggregate", source_ref=ref,
                              title=f"{args.template} ({args.time_from:%Y-%m-%d %H:%M}–{args.time_to:%Y-%m-%d %H:%M} UTC)")]
        items = [{**{k: v for k, v in r.items() if k != "tenant_id"}, "citation": 0} for r in rows]
        chart_hint = None
        if args.template == "error_trend_hourly" and items:
            chart_hint = {"kind": "timeseries", "x": "hour", "y": "events", "title": "Errors per hour"}
        return RouteResult(route=self.name, items=items, citations=citations, chart_hint=chart_hint,
                           notes=[] if items else ["no data for this window"])
