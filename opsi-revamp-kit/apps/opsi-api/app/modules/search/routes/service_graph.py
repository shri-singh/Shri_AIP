"""service_graph: bounded, time-scoped neighbourhood in the Opsi operational ontology."""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import Field

from ...ontology.repository import OntologyRepository
from ..contracts import Citation, RouteArgs, RouteContext, RouteResult


class ServiceGraphArgs(RouteArgs):
    entity: str = Field(max_length=300, description="Entity natural key (e.g. SERVICE-...), name, or catalog FQN")
    at: datetime | None = Field(default=None, description="Point in time (UTC) for which edges must be valid")
    depth: int = Field(default=2, ge=1, le=3)


class ServiceGraphRoute:
    name = "service_graph"
    description = ("Explore dependencies around a service, host, table or incident: calls, depends_on, runs_on, "
                   "reads_from/writes_to, owned_by, affects, documented_by (runbooks). Edges carry source and "
                   "confidence. Use for blast radius and upstream suspects.")
    args_model = ServiceGraphArgs
    permission = "ontology:read"
    cost_units = 1.0
    timeout_seconds = 8.0
    max_items = 80

    def __init__(self, repo: OntologyRepository) -> None:
        self.repo = repo

    async def run(self, args: ServiceGraphArgs, ctx: RouteContext) -> RouteResult:
        root = await self.repo.find_entity(ctx.principal, args.entity)
        if root is None:
            return RouteResult(route=self.name, notes=[f"no entity matches {args.entity!r}"])
        at = args.at or datetime.now(timezone.utc)
        hood = await self.repo.neighborhood(ctx.principal, root.id, at, args.depth, self.max_items)
        if hood is None:
            return RouteResult(route=self.name, notes=["entity not accessible"])
        by_id = {e.id: e for e in hood.entities}
        by_id[root.id] = root
        names = {i: f"{e.kind}:{e.name}" for i, e in by_id.items()}
        items, citations = [], []
        for edge in hood.edges:
            # edges touching services outside the caller's scope are dropped entirely
            if not _visible(ctx, by_id.get(edge.src_id)) or not _visible(ctx, by_id.get(edge.dst_id)):
                continue
            src, dst = names.get(edge.src_id, str(edge.src_id)), names.get(edge.dst_id, str(edge.dst_id))
            citations.append(Citation(source_type="ontology", source_ref=f"ontology://edge/{edge.id}",
                                      title=f"{src} -{edge.relation}-> {dst}", event_time=edge.valid_from,
                                      snippet=f"source={edge.source_system} confidence={edge.confidence}"))
            items.append({"from": src, "relation": edge.relation, "to": dst, "depth": edge.depth,
                          "confidence": float(edge.confidence), "source": edge.source_system,
                          "evidence_ref": edge.evidence_ref, "citation": len(citations) - 1})
        return RouteResult(route=self.name, items=items, citations=citations, truncated=hood.truncated,
                           chart_hint={"kind": "graph", "root": names[root.id]})


def _visible(ctx: RouteContext, entity) -> bool:
    if entity is None or entity.kind != "service":
        return True
    return ctx.principal.can_access_service(entity.natural_key) or ctx.principal.can_access_service(entity.name)
