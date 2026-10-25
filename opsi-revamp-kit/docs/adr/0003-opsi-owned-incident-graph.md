# ADR-0003: Opsi-owned operational ontology / incident graph in PostgreSQL
- Status: Accepted
- Date: 2026-10-24

## Context
Investigations need relations such as incident *affects* service, service *runs_on* host, service *calls* service,
evidence *supports* hypothesis, change *triggered* incident. OpenMetadata lineage describes *data* flow between
assets; it does not model operational causality, and its "IncidentManager" is about data-quality test failures.
Facts change over time (a service moves hosts; a dependency is removed) and some edges are inferred by an agent
and may be wrong.

## Decision
- Model the graph in `opsi_knowledge` (migration 0004): `entities` (kind, natural_key, catalog FQN/UUID) and
  `edges` with `valid_from`/`valid_to`, `confidence`, `source_system`, `source_ref`, `provenance` JSON,
  `evidence_ref`, `classification`, `created_by`.
- Relation vocabulary is data (`relation_types` with allowed src/dst kinds and an `is_causal` flag).
- Edges are never updated in place: closing (`valid_to`) + inserting keeps history; one open edge per triple.
- Agent-sourced edges must carry evidence and `confidence < 1` (DB CHECK constraint).
- Traversal is a bounded recursive CTE (`opsi_knowledge.neighborhood`, depth <= 4, limit <= 1000), executed under RLS.

## Consequences
- No new database technology to operate; RLS and backups come for free.
- Deep graph analytics (e.g. 6+ hop path finding over millions of edges) would need a graph engine later
  (Apache AGE or Amazon Neptune) - revisit when traversal latency exceeds budgets.

## Alternatives considered
- Neo4j/Neptune now - extra platform, data duplication, separate authz model.
- Use OpenMetadata lineage edges - wrong semantics, and not ours to write at incident speed.

## Verification
Migration validator checks (`database/validate/validate_migrations.mjs`): traversal works, respects RLS, and rejects
agent edges without evidence. `tests/integration/test_pg_chat.py::test_ontology_and_incident_store_on_seed_data`.
