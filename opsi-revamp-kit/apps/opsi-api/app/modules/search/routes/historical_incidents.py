"""historical_incident_search: past Dynatrace problems from the curated PostgreSQL subset (FTS)."""
from __future__ import annotations

from datetime import timedelta
from typing import ClassVar

from pydantic import Field

from ..contracts import Citation, RouteContext, RouteResult, TimeWindowArgs, scoped_services
from ..stores import IncidentStore


class HistoricalIncidentArgs(TimeWindowArgs):
    query: str | None = Field(default=None, max_length=200, description="Words from the problem title")
    service_id: str | None = Field(default=None, max_length=200, description="Dynatrace entity id, e.g. SERVICE-...")
    limit: int = Field(default=10, ge=1, le=20)

    MAX_SPAN: ClassVar[timedelta] = timedelta(days=90)


class HistoricalIncidentRoute:
    name = "historical_incident_search"
    description = ("Find past incidents/problems (Dynatrace) similar to the current one, by words and/or affected "
                   "service, within up to 90 days. Use to answer 'has this happened before?'.")
    args_model = HistoricalIncidentArgs
    permission = "search:use"
    cost_units = 1.0
    timeout_seconds = 10.0
    max_items = 20

    def __init__(self, store: IncidentStore) -> None:
        self.store = store

    async def run(self, args: HistoricalIncidentArgs, ctx: RouteContext) -> RouteResult:
        services = scoped_services(ctx.principal, args.service_id)
        rows = await self.store.search_problems(ctx.principal, args.query, services, args.time_from, args.time_to,
                                                args.limit)
        items, citations = [], []
        for r in rows:
            citations.append(Citation(source_type="dynatrace_problem", source_ref=r["evidence_ref"],
                                      title=f"{r.get('display_id') or r['problem_id']} {r['title']}",
                                      event_time=r["start_time"]))
            items.append({"problem": r.get("display_id") or r["problem_id"], "title": r["title"],
                          "status": r.get("status"), "severity": r.get("severity_level"),
                          "start_time": r["start_time"], "end_time": r.get("end_time"),
                          "root_cause_entity": r.get("root_cause_entity_id"), "citation": len(citations) - 1})
        return RouteResult(route=self.name, items=items, citations=citations,
                           notes=[] if items else ["no matching past problems in this window"])
