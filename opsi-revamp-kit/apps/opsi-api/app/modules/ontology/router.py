"""Ontology REST API (incident-graph UI): neighbourhood reads + provenance-tracked edge writes."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, status

from .._shared.container import OpsiServices, services
from .._shared.errors import BadRequest, NotFound
from ..identity.deps import require
from ..identity.principal import Principal
from .repository import Edge, EdgeIn, Neighborhood

router = APIRouter(prefix="/api/v2/ontology", tags=["ontology"])


def _repo(svc: OpsiServices):
    if svc.ontology is None:
        raise NotFound("ontology")
    return svc.ontology


@router.get("/entities/{key:path}/neighborhood", response_model=Neighborhood)
async def neighborhood(key: str, depth: int = Query(default=2, ge=1, le=3), at: datetime | None = None,
                       limit: int = Query(default=200, ge=1, le=500), p: Principal = Depends(require("ontology:read")),
                       svc: OpsiServices = Depends(services)):
    repo = _repo(svc)
    root = await repo.find_entity(p, key)
    if root is None:
        raise NotFound("entity")
    hood = await repo.neighborhood(p, root.id, at or datetime.now(timezone.utc), depth, limit)
    if hood is None:
        raise NotFound("entity")
    return hood


@router.post("/edges", response_model=Edge, status_code=status.HTTP_201_CREATED)
async def add_edge(body: EdgeIn, request: Request, p: Principal = Depends(require("ontology:write")),
                   svc: OpsiServices = Depends(services)):
    if body.source_system == "agent":
        raise BadRequest("agent edges are created by the agent pipeline, not this endpoint")
    try:
        edge = await _repo(svc).add_edge(p, body)
    except LookupError:
        raise NotFound("entity") from None
    except ValueError as exc:
        raise BadRequest(str(exc)) from None
    await svc.audit.record(tenant_id=p.tenant_id, actor_id=p.user_id, action="ontology.edge.add", target=str(edge.id),
                           outcome="allowed", request_id=request.headers.get("x-request-id"),
                           detail={"relation": edge.relation})
    return edge


@router.post("/edges/{edge_id}/close", status_code=status.HTTP_204_NO_CONTENT)
async def close_edge(edge_id: uuid.UUID, p: Principal = Depends(require("ontology:write")),
                     svc: OpsiServices = Depends(services)):
    if not await _repo(svc).close_edge(p, edge_id, datetime.now(timezone.utc)):
        raise NotFound("open edge")
