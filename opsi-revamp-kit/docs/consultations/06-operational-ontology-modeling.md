# 06 - Modelling the operational ontology

## The question
"What exactly goes into the graph, how do ids line up across Dynatrace, Elastic, OpenMetadata and Opsi, and how do we
keep it true over time?"

## Short answer
Entities are keyed by `(tenant, kind, natural_key)`; pick **one canonical natural key per kind** (Dynatrace entity ids
for services/hosts/process groups; OpenMetadata FQN for tables; problem id for incidents). Edges are facts with a time
range, a source and a confidence. Load from authoritative systems first, let humans curate, let agents only *propose*.

## Canonical identifiers
| Kind | natural_key | Also store (attributes) | Join to |
|---|---|---|---|
| service | `SERVICE-<hex>` (Dynatrace) | name, k8s workload, Elastic `service.name` alias list | curated `service_id`, Elastic queries |
| host | Dynatrace `HOST-...` | hostname, instance id | |
| process_group | `PROCESS_GROUP-...` | | |
| table | OpenMetadata FQN | `external_catalog_id` | `catalog_xrefs` |
| team | OpenMetadata team name | | `owned_by` edges |
| incident | Dynatrace `problemId` | display id | `opsi_ingest.problems` |
| runbook | URL / KB id | | `documents.source_ref` |
| change | deployment id | version, pipeline | `triggered`/`changed_by` |
Keep an **alias list** (`attributes.aliases`) for names used in logs; `find_entity` matches natural key, name, FQN or id.
Decide which identifier `service_id` in curated tables uses (collectors map Elastic `service.name` vs Dynatrace ids) -
if they differ, add a mapping step in the index stage or store aliases and resolve at query time.

## Edge semantics
- Structural (from Smartscape): `calls`, `runs_on`, `depends_on` - confidence 1, source `dynatrace`, refreshed daily;
  close edges not seen in N refreshes.
- Data access (from OM or code knowledge): `reads_from`, `writes_to` - source `openmetadata`/`manual`.
- Ownership: `owned_by` from OM teams (OM is the source of truth; Opsi mirrors for traversal).
- Incident: `affects` from problems' affected entities (valid from problem start, closed at problem end).
- Causal (`triggered`, `caused_by`, `explains`): manual (postmortems) or agent-proposed with evidence and confidence < 1.

## Time
Query "as of" the incident start (`neighborhood(entity, at => incident_start)`) to see the topology that existed then.
Never update edges in place; close (`valid_to`) and insert. That gives reproducible investigations.

## Bootstrapping from Dynatrace (sketch)
```python
# GET {env}/api/v2/entities?entitySelector=type(SERVICE)&fields=+fromRelationships,+toRelationships,+properties&pageSize=500
# token scope: entities.read  (paginate with nextPageKey like Problems v2)
for svc in entities:
    upsert_entity(kind="service", natural_key=svc["entityId"], name=svc["displayName"], source_system="dynatrace")
    for rel, targets in svc.get("fromRelationships", {}).items():   # e.g. "calls", "runsOnHost"
        for t in targets:
            ensure_edge(src=svc["entityId"], dst=t["id"], relation=MAP[rel], source_system="dynatrace")
```
Verify relationship names in your tenant (`fromRelationships` keys) before mapping; write the loader as a separate
collector-style job with its own tests and fixtures.

## When to outgrow PostgreSQL
Triggers: traversals > 4 hops needed interactively, > 10^7 edges with sub-second needs, graph algorithms (centrality,
community detection) at query time. Options: Apache AGE (PostgreSQL extension, Apache-2.0 - check RDS support), Amazon
Neptune, or offline graph analytics on S3 exports.

## Verify
`GET /api/v2/ontology/entities/<key>/neighborhood?depth=2` returns expected edges for a known service; edges have
sources; closed edges remain queryable with `at=` in the past.
