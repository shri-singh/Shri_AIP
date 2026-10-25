"""Ontology (opsi_knowledge.*) read/write with provenance rules.

Write rules enforced here *and* by DB constraints (0004_knowledge.sql):
- relation must exist in relation_types and match src/dst kinds;
- agent-sourced edges need an evidence_ref and confidence < 1;
- edges are never updated in place: ``close_edge`` sets valid_to, a new fact is a new row.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..identity.principal import Principal

UTC = timezone.utc


class Entity(BaseModel):
    id: uuid.UUID
    kind: str
    natural_key: str
    name: str
    external_catalog_fqn: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class Edge(BaseModel):
    id: uuid.UUID
    src_id: uuid.UUID
    dst_id: uuid.UUID
    relation: str
    valid_from: datetime
    valid_to: datetime | None = None
    confidence: float = 1.0
    source_system: str
    source_ref: str | None = None
    evidence_ref: str | None = None
    depth: int | None = None


class EdgeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    src_id: uuid.UUID
    dst_id: uuid.UUID
    relation: str = Field(max_length=40)
    valid_from: datetime | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    source_system: str = Field(default="manual", pattern="^(manual|agent|opsi)$")
    source_ref: str | None = Field(default=None, max_length=500)
    evidence_ref: str | None = Field(default=None, max_length=500)
    provenance: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _agent_rules(self) -> EdgeIn:
        if self.src_id == self.dst_id:
            raise ValueError("an edge cannot point to itself")
        if self.source_system == "agent" and (not self.evidence_ref or self.confidence >= 1.0):
            raise ValueError("agent-inferred edges need evidence_ref and confidence < 1")
        return self


class Neighborhood(BaseModel):
    root: Entity
    entities: list[Entity]
    edges: list[Edge]
    truncated: bool = False


class OntologyRepository(Protocol):
    async def find_entity(self, p: Principal, key: str) -> Entity | None: ...
    async def neighborhood(self, p: Principal, entity_id: uuid.UUID, at: datetime, depth: int,
                           limit: int) -> Neighborhood | None: ...
    async def add_edge(self, p: Principal, edge: EdgeIn) -> Edge: ...
    async def close_edge(self, p: Principal, edge_id: uuid.UUID, at: datetime) -> bool: ...


class PgOntologyRepository:
    def __init__(self, db) -> None:
        self.db = db

    async def find_entity(self, p, key):
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute(
                "SELECT id, kind, natural_key, name, external_catalog_fqn, attributes FROM opsi_knowledge.entities "
                "WHERE (natural_key = %(k)s OR lower(name) = lower(%(k)s) OR external_catalog_fqn = %(k)s "
                "OR id::text = %(k)s) AND valid_to IS NULL ORDER BY (natural_key = %(k)s) DESC LIMIT 1", {"k": key})
            row = await cur.fetchone()
            return Entity(**row) if row else None

    async def neighborhood(self, p, entity_id, at, depth, limit):
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute("SELECT id, kind, natural_key, name, external_catalog_fqn, attributes "
                                     "FROM opsi_knowledge.entities WHERE id = %s", (entity_id,))
            root = await cur.fetchone()
            if not root:
                return None
            cur = await conn.execute(
                "SELECT n.depth, e.id, e.src_id, e.dst_id, e.relation, e.valid_from, e.valid_to, e.confidence, "
                "e.source_system, e.source_ref, e.evidence_ref FROM opsi_knowledge.neighborhood(%s, %s, %s, %s) n "
                "JOIN opsi_knowledge.edges e ON e.id = n.edge_id ORDER BY n.depth, e.relation",
                (entity_id, at, depth, limit + 1))
            edges = [Edge(**r) for r in await cur.fetchall()]
            truncated = len(edges) > limit
            edges = edges[:limit]
            ids = {e.src_id for e in edges} | {e.dst_id for e in edges}
            cur = await conn.execute("SELECT id, kind, natural_key, name, external_catalog_fqn, attributes "
                                     "FROM opsi_knowledge.entities WHERE id = ANY(%s)", (list(ids),))
            entities = [Entity(**r) for r in await cur.fetchall()]
            return Neighborhood(root=Entity(**root), entities=entities, edges=edges, truncated=truncated)

    async def add_edge(self, p, edge):
        from psycopg.types.json import Jsonb

        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute(
                "SELECT (SELECT kind FROM opsi_knowledge.entities WHERE id = %s) AS src_kind, "
                "(SELECT kind FROM opsi_knowledge.entities WHERE id = %s) AS dst_kind, "
                "(SELECT row_to_json(r) FROM opsi_knowledge.relation_types r WHERE relation = %s) AS rel",
                (edge.src_id, edge.dst_id, edge.relation))
            info = await cur.fetchone()
            _check_relation(info["src_kind"], info["dst_kind"], info["rel"])
            cur = await conn.execute(
                "INSERT INTO opsi_knowledge.edges (tenant_id, src_id, dst_id, relation, valid_from, confidence, "
                "source_system, source_ref, provenance, evidence_ref, created_by) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id, src_id, dst_id, relation, valid_from, "
                "valid_to, confidence, source_system, source_ref, evidence_ref",
                (p.tenant_id, edge.src_id, edge.dst_id, edge.relation, edge.valid_from or datetime.now(UTC),
                 edge.confidence, edge.source_system, edge.source_ref, Jsonb(edge.provenance), edge.evidence_ref,
                 p.user_id))
            return Edge(**await cur.fetchone())

    async def close_edge(self, p, edge_id, at):
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute("UPDATE opsi_knowledge.edges SET valid_to = %s WHERE id = %s AND valid_to IS NULL "
                                     "AND valid_from < %s", (at, edge_id, at))
            return cur.rowcount == 1


def _check_relation(src_kind: str | None, dst_kind: str | None, rel: dict | None) -> None:
    if not src_kind or not dst_kind:
        raise LookupError("entity not found")
    if not rel:
        raise ValueError("unknown relation type")
    if src_kind not in rel["src_kinds"] or dst_kind not in rel["dst_kinds"]:
        raise ValueError(f"relation {rel['relation']} does not allow {src_kind} -> {dst_kind}")


@dataclass
class MemoryOntologyRepository:
    """Fake honouring tenant scoping and time validity; relation kinds are not enforced."""

    entities: dict[uuid.UUID, tuple[str, Entity]] = field(default_factory=dict)
    edges: dict[uuid.UUID, tuple[str, Edge]] = field(default_factory=dict)

    def add_entity(self, tenant: str, entity: Entity) -> Entity:
        self.entities[entity.id] = (tenant, entity)
        return entity

    async def find_entity(self, p, key):
        for tenant, e in self.entities.values():
            if tenant == p.tenant_id and key in (e.natural_key, e.name, e.external_catalog_fqn, str(e.id)):
                return e
        return None

    async def neighborhood(self, p, entity_id, at, depth, limit):
        root = self.entities.get(entity_id)
        if not root or root[0] != p.tenant_id:
            return None
        frontier, seen_nodes, found = {entity_id}, {entity_id}, []
        for level in range(1, min(depth, 4) + 1):
            nxt = set()
            for tenant, edge in self.edges.values():
                if tenant != p.tenant_id or edge.valid_from > at or (edge.valid_to and edge.valid_to <= at):
                    continue
                if (edge.src_id in frontier or edge.dst_id in frontier) and edge.id not in {e.id for e in found}:
                    found.append(edge.model_copy(update={"depth": level}))
                    nxt |= {edge.src_id, edge.dst_id} - seen_nodes
            seen_nodes |= nxt
            frontier = nxt
        ids = {e.src_id for e in found} | {e.dst_id for e in found}
        entities = [e for t, e in self.entities.values() if t == p.tenant_id and e.id in ids]
        return Neighborhood(root=root[1], entities=entities, edges=found[:limit], truncated=len(found) > limit)

    async def add_edge(self, p, edge):
        new = Edge(id=uuid.uuid4(), src_id=edge.src_id, dst_id=edge.dst_id, relation=edge.relation,
                   valid_from=edge.valid_from or datetime.now(UTC), confidence=edge.confidence,
                   source_system=edge.source_system, source_ref=edge.source_ref, evidence_ref=edge.evidence_ref)
        self.edges[new.id] = (p.tenant_id, new)
        return new

    async def close_edge(self, p, edge_id, at):
        item = self.edges.get(edge_id)
        if not item or item[0] != p.tenant_id or item[1].valid_to is not None:
            return False
        self.edges[edge_id] = (item[0], item[1].model_copy(update={"valid_to": at}))
        return True
