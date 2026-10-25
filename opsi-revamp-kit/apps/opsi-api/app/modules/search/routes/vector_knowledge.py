"""vector_knowledge (optional): semantic search over curated runbooks/RCA write-ups (pgvector).

Registered only when OPSI_VECTOR_ENABLED=true and migration 0006 is applied.
Embeddings come from the same Portkey -> Bedrock gateway (EMBEDDING_MODEL).
"""
from __future__ import annotations

from typing import Literal, Protocol

from pydantic import Field

from ...identity.principal import Principal
from ..contracts import Citation, RouteArgs, RouteContext, RouteResult


class Embedder(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class KnowledgeStore(Protocol):
    async def knn(self, p: Principal, embedding: list[float], doc_type: str | None, limit: int) -> list[dict]: ...


class PgKnowledgeStore:
    def __init__(self, db) -> None:
        self.db = db

    async def knn(self, p, embedding, doc_type, limit):
        vector = "[" + ",".join(f"{x:.6f}" for x in embedding) + "]"
        async with self.db.tenant_tx(p) as conn:
            await conn.execute("SET LOCAL hnsw.ef_search = 64")
            cur = await conn.execute(
                "SELECT title, doc_type, source_ref, content_excerpt, 1 - (embedding <=> %s::vector) AS similarity "
                "FROM opsi_knowledge.documents WHERE valid_to IS NULL AND (%s::text IS NULL OR doc_type = %s) "
                "ORDER BY embedding <=> %s::vector LIMIT %s", (vector, doc_type, doc_type, vector, limit))
            return list(await cur.fetchall())


class VectorKnowledgeArgs(RouteArgs):
    query: str = Field(min_length=3, max_length=500, description="Natural-language description of the symptom")
    doc_type: Literal["runbook", "rca", "incident_summary", "kb", "postmortem"] | None = None
    limit: int = Field(default=5, ge=1, le=8)


class VectorKnowledgeRoute:
    name = "vector_knowledge"
    description = "Find relevant runbooks, RCAs and post-mortems by meaning (semantic search)."
    args_model = VectorKnowledgeArgs
    permission = "search:use"
    cost_units = 2.0
    timeout_seconds = 15.0
    max_items = 8

    def __init__(self, embedder: Embedder, store: KnowledgeStore, min_similarity: float = 0.35) -> None:
        self.embedder = embedder
        self.store = store
        self.min_similarity = min_similarity

    async def run(self, args: VectorKnowledgeArgs, ctx: RouteContext) -> RouteResult:
        rows = await self.store.knn(ctx.principal, await self.embedder.embed(args.query), args.doc_type, args.limit)
        items, citations = [], []
        for r in rows:
            if r["similarity"] < self.min_similarity:
                continue
            citations.append(Citation(source_type="runbook", source_ref=r["source_ref"], title=r["title"],
                                      snippet=r["content_excerpt"][:300]))
            items.append({"title": r["title"], "type": r["doc_type"], "excerpt": r["content_excerpt"][:800],
                          "similarity": round(float(r["similarity"]), 3), "citation": len(citations) - 1})
        return RouteResult(route=self.name, items=items, citations=citations,
                           notes=[] if items else ["no sufficiently similar documents"])
