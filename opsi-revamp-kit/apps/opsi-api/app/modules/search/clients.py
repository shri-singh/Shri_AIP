"""Thin read-only HTTP clients for retrieval backends.

Elasticsearch is called over plain HTTP ``_search`` (httpx) instead of the
official client: a read-only ``_search`` body is stable across 7.x/8.x/9.x, so
the API does not need its client major version pinned to the cluster major
(the collectors still use the official client for PIT pagination).
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from .._shared.errors import UpstreamUnavailable


class ElasticReadClient:
    def __init__(self, base_url: str, api_key: str = "", ca_certs: str = "", transport: Any | None = None) -> None:
        if not base_url:
            raise ValueError("SEARCH_ELASTIC_URL is required for exact_logs")
        headers = {"Authorization": f"ApiKey {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), headers=headers, timeout=20,
                                         verify=ca_certs or True, transport=transport)

    async def search(self, indices: list[str], body: dict[str, Any]) -> dict[str, Any]:
        path = "/" + ",".join(quote(i, safe="*-_.") for i in indices) + "/_search"
        try:
            response = await self._client.post(path, json=body,
                                               params={"ignore_unavailable": "true", "allow_no_indices": "true"})
        except httpx.HTTPError as exc:
            raise UpstreamUnavailable(f"log search unavailable ({type(exc).__name__})") from None
        if response.status_code in (401, 403):
            raise UpstreamUnavailable("log search denied for the service account (check its read privileges)")
        if response.status_code >= 400:
            raise UpstreamUnavailable(f"log search failed (HTTP {response.status_code})")
        return response.json()

    async def aclose(self) -> None:
        await self._client.aclose()
