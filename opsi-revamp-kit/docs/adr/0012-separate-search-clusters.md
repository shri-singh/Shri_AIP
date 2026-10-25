# ADR-0012: Catalog indices and operational indices in separate search clusters
- Status: Accepted
- Date: 2026-10-24

## Context
OpenMetadata needs a search backend for its catalog (OpenSearch 3.x or Elasticsearch 9.x for 2.0; reindex
always recreates indices). Opsi may add an operational index of curated incidents/signatures. The existing
Elastic log cluster is large and production-critical. Elasticsearch and OpenSearch diverged; cross-cluster
search between them is not assumed.

## Decision
- OpenMetadata gets its **own** security-enabled cluster (managed OpenSearch domain preferred). Never the log cluster.
- Opsi's curated `opsi-incidents*` index lives on an Opsi-owned operational cluster (or a separate domain);
  template in `infrastructure/opensearch/` (`dynamic: strict`).
- The API queries each backend through its own adapter (`ElasticReadClient`, `OpenMetadataClient`, OpenSearch sink)
  and merges results in Python. No cross-cluster search dependency.
- Lab exception: the OpenMetadata dev compose's internal OpenSearch (security disabled, never published).

## Consequences
- More clusters to pay for; isolation of failure domains and upgrade cadences (OM reindexes don't hit logs).

## Alternatives considered
- One shared cluster with index prefixes - noisy-neighbour risk, conflicting version requirements, shared credentials.

## Verification
Config review: `OM_SEARCH_HOST` != log cluster host; `OPENSEARCH_INDEX` must start with `opsi-` (enforced in code).
