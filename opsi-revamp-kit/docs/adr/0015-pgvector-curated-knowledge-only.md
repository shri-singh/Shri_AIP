# ADR-0015: pgvector is optional and only for curated knowledge
- Status: Accepted
- Date: 2026-10-24

## Context
Semantic search helps find runbooks and past RCAs phrased differently from the current symptom. Embedding raw
logs is expensive, low-value and multiplies sensitive data. HNSW indices consume memory on the primary.

## Decision
- Migration 0006 (optional) adds `opsi_knowledge.documents` with `vector(1024)` + HNSW (cosine), RLS, and
  `embedding_model` per row. Only runbooks, RCAs, incident summaries, KB and post-mortems are embedded.
- Route `vector_knowledge` is registered only when `OPSI_VECTOR_ENABLED=true`; results below a similarity floor are dropped.
- Embeddings via the same Portkey -> Bedrock gateway (`EMBEDDING_MODEL`); dimension fixed by the chosen model.
- Consider a read replica for vector queries if the primary is busy.

## Consequences
- Changing embedding model = new column/table + re-embed; plan versioned rollouts.

## Alternatives considered
- OpenSearch k-NN - viable when an Opsi-owned OpenSearch exists; keep pgvector first for fewer moving parts.

## Verification
Migration validator inserts and KNN-queries a 1024-dim vector under RLS.
