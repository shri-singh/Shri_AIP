"""Optional OpenSearch indexer for lexical incident search (index stage).

Writes to an **Opsi-owned** index (default ``opsi-incidents``) on the
*operational* cluster - never into OpenMetadata's catalog indices. Document
ids are deterministic so replays overwrite instead of duplicating.

Index template: infrastructure/opensearch/opsi-incidents-template.json.
"""
from __future__ import annotations

import json
from typing import Any

import requests

from ..errors import PermanentSourceError, TransientSourceError
from ..timeutil import iso_z
from .curated import aggregate_signatures, problem_rows


class OpenSearchSink:
    name = "opensearch"

    def __init__(self, url: str, index: str, username: str = "", password: str = "", ca_certs: str = "",
                 session: requests.Session | None = None, max_samples: int = 3) -> None:
        if not index.startswith("opsi-"):
            raise ValueError("OPENSEARCH_INDEX must start with 'opsi-' (Opsi-owned index namespace)")
        if url.startswith("http://") and not url.startswith(("http://127.0.0.1", "http://localhost")):
            raise ValueError("OPENSEARCH_URL must use https outside localhost")
        self.url = url.rstrip("/")
        self.index = index
        self.session = session or requests.Session()
        if username:
            self.session.auth = (username, password)
        self.verify: Any = ca_certs or True
        self.max_samples = max_samples

    def _docs(self, manifest: dict[str, Any], rows: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
        tenant, source = manifest["tenant_id"], manifest["source"]
        docs: list[tuple[str, dict[str, Any]]] = []
        if manifest["dataset"] == "problems":
            for p in problem_rows(rows):
                docs.append((f"{tenant}:problem:{p['problem_id']}", {
                    "tenant_id": tenant, "kind": "problem", "source": source, "problem_id": p["problem_id"],
                    "title": p["title"], "status": p["status"], "severity": p["severity_level"],
                    "event_time": iso_z(p["start_time"]), "entity_ids": p["affected_entity_ids"],
                    "evidence_ref": p["evidence_ref"],
                }))
        else:
            signatures, _ = aggregate_signatures(rows, self.max_samples)
            for s in signatures:
                docs.append((f"{tenant}:sig:{source}:{manifest['window_start']}:{s.service_id}:{s.fingerprint}", {
                    "tenant_id": tenant, "kind": "error_signature", "source": source, "service_id": s.service_id,
                    "fingerprint": s.fingerprint, "severity": s.severity, "count": s.count,
                    "event_time": iso_z(s.first_seen), "last_seen": iso_z(s.last_seen),
                    "message": s.sample_message, "evidence_ref": s.sample_ref,
                }))
        return docs

    def apply(self, manifest: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, int]:
        docs = self._docs(manifest, rows)
        if not docs:
            return {"indexed": 0}
        lines = []
        for doc_id, doc in docs:
            lines.append(json.dumps({"index": {"_index": self.index, "_id": doc_id}}))
            lines.append(json.dumps(doc, ensure_ascii=False))
        try:
            response = self.session.post(f"{self.url}/_bulk", data="\n".join(lines) + "\n",
                                         headers={"Content-Type": "application/x-ndjson"},
                                         verify=self.verify, timeout=60)
        except requests.RequestException as exc:
            raise TransientSourceError(f"opensearch bulk failed: {type(exc).__name__}") from None
        if response.status_code in (401, 403):
            raise PermanentSourceError(f"opensearch bulk HTTP {response.status_code}: check role (index, create_index)")
        if response.status_code >= 400:
            raise TransientSourceError(f"opensearch bulk HTTP {response.status_code}")
        body = response.json()
        if body.get("errors"):
            failed = [i for i in body.get("items", []) if (i.get("index") or {}).get("status", 200) >= 300]
            raise TransientSourceError(f"opensearch bulk: {len(failed)} item(s) failed")
        return {"indexed": len(docs)}
