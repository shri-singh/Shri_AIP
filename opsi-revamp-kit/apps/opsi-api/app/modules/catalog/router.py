"""Read-only catalog proxy for the React metadata pages: the browser never holds an OpenMetadata token."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from .._shared.container import OpsiServices, services
from .._shared.errors import NotFound
from ..identity.deps import require
from ..identity.principal import Principal

router = APIRouter(prefix="/api/v2/catalog", tags=["catalog"])
READ = require("catalog:read")


def _client(svc: OpsiServices):
    if svc.openmetadata is None:
        raise NotFound("catalog integration")
    return svc.openmetadata


@router.get("/search")
async def search(q: str = Query(min_length=1, max_length=200),
                 entity_type: Literal["table", "dashboard", "pipeline", "topic", "glossaryTerm"] = "table",
                 size: int = Query(default=10, ge=1, le=25), p: Principal = Depends(READ),
                 svc: OpsiServices = Depends(services)) -> list[dict[str, Any]]:
    return await _client(svc).search(q, entity_type, size)


@router.get("/tables/{fqn:path}")
async def table(fqn: str, p: Principal = Depends(READ), svc: OpsiServices = Depends(services)) -> dict[str, Any]:
    found = await _client(svc).get_table(fqn)
    if not found:
        raise NotFound("table")
    return found


@router.get("/lineage/table/{fqn:path}")
async def lineage(fqn: str, upstream: int = Query(default=1, ge=0, le=3), downstream: int = Query(default=1, ge=0, le=3),
                  p: Principal = Depends(READ), svc: OpsiServices = Depends(services)) -> dict[str, Any]:
    return await _client(svc).lineage("table", fqn, upstream, downstream)
