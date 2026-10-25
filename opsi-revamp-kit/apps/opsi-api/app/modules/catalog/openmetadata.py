"""Read-only OpenMetadata REST client (catalog = source of truth for tables/owners/domains/lineage).

Uses OpenMetadata's public REST API with a *bot* JWT (create a dedicated bot
with a read-only role in OpenMetadata -> Settings -> Bots). Never connect to
OpenMetadata's internal database.

Endpoints used (stable through 1.x and 2.0; verify on your instance at
``{OPENMETADATA_URL}/swagger.html`` after every upgrade):
- GET /api/v1/system/version
- GET /api/v1/search/query?q=&index=<entity>_search_index&from=0&size=
- GET /api/v1/tables/name/{fqn}?fields=owners,tags,domains,columns
- GET /api/v1/lineage/{entity}/name/{fqn}?upstreamDepth=&downstreamDepth=
OpenMetadata >= 1.5 returns ``owners`` (a list) instead of ``owner``; 2.0 changed
search-related parameters (``search_after`` must be repeated) - see
docs/cheatsheets/openmetadata-api.md.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from .._shared.errors import UpstreamUnavailable

SEARCH_INDEX = {
    "table": "table_search_index",
    "dashboard": "dashboard_search_index",
    "pipeline": "pipeline_search_index",
    "topic": "topic_search_index",
    "glossaryTerm": "glossary_term_search_index",
}


class OpenMetadataClient:
    def __init__(self, base_url: str, token: str, ca_certs: str = "", transport: Any | None = None) -> None:
        if not base_url or not token:
            raise ValueError("OPENMETADATA_URL and OPENMETADATA_BOT_TOKEN are required")
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=15, verify=ca_certs or True,
                                         headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                                         transport=transport)

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"catalog unavailable ({type(exc).__name__})") from None
        if response.status_code == 404:
            return {}
        if response.status_code in (401, 403):
            raise UpstreamUnavailable("catalog denied the bot token (expired token or missing read role)")
        if response.status_code >= 400:
            raise UpstreamUnavailable(f"catalog request failed (HTTP {response.status_code})")
        return response.json()

    async def version(self) -> str:
        return (await self._get("/api/v1/system/version")).get("version", "unknown")

    async def search(self, q: str, entity_type: str = "table", size: int = 10) -> list[dict[str, Any]]:
        body = await self._get("/api/v1/search/query", {"q": q, "index": SEARCH_INDEX[entity_type],
                                                         "from": 0, "size": size})
        hits = ((body.get("hits") or {}).get("hits")) or []
        return [summarize_entity(h.get("_source") or {}, entity_type) for h in hits]

    async def get_table(self, fqn: str) -> dict[str, Any] | None:
        body = await self._get(f"/api/v1/tables/name/{quote(fqn, safe='')}",
                               {"fields": "owners,tags,domains,columns"})
        return summarize_entity(body, "table", max_columns=60) if body else None

    async def lineage(self, entity_type: str, fqn: str, upstream: int = 1, downstream: int = 1) -> dict[str, Any]:
        body = await self._get(f"/api/v1/lineage/{entity_type}/name/{quote(fqn, safe='')}",
                               {"upstreamDepth": min(upstream, 3), "downstreamDepth": min(downstream, 3)})
        nodes = [{"id": n.get("id"), "fqn": n.get("fullyQualifiedName"), "type": n.get("type")}
                 for n in body.get("nodes", [])]
        edges = [{"from": e.get("fromEntity"), "to": e.get("toEntity")}
                 for e in body.get("upstreamEdges", []) + body.get("downstreamEdges", [])]
        return {"entity": (body.get("entity") or {}).get("fullyQualifiedName", fqn), "nodes": nodes, "edges": edges}

    def ui_url(self, entity_type: str, fqn: str) -> str:
        return f"{self.base_url}/{entity_type}/{quote(fqn, safe='.')}"

    async def aclose(self) -> None:
        await self._client.aclose()


def _names(items: Any, key: str = "name") -> list[str]:
    if isinstance(items, dict):
        items = [items]
    return [str(i.get("displayName") or i.get(key)) for i in items or [] if isinstance(i, dict) and i.get(key)]


def summarize_entity(src: dict[str, Any], entity_type: str, max_columns: int = 0) -> dict[str, Any]:
    owners = src.get("owners") if "owners" in src else src.get("owner")  # owner: OpenMetadata < 1.5
    domains = src.get("domains") if "domains" in src else src.get("domain")
    out = {
        "entity_type": entity_type,
        "id": src.get("id"),
        "name": src.get("name"),
        "fqn": src.get("fullyQualifiedName"),
        "description": (src.get("description") or "")[:500],
        "owners": _names(owners),
        "domains": _names(domains),
        "tags": [t.get("tagFQN") for t in src.get("tags", []) if isinstance(t, dict) and t.get("tagFQN")],
        "service": (src.get("service") or {}).get("name") if isinstance(src.get("service"), dict) else None,
    }
    if max_columns:
        out["columns"] = [{"name": c.get("name"), "type": c.get("dataType"),
                           "tags": [t.get("tagFQN") for t in c.get("tags", []) if isinstance(t, dict)]}
                          for c in (src.get("columns") or [])[:max_columns]]
    return out
