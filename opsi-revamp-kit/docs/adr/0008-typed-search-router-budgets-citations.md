# ADR-0008: Typed retrieval routes as LLM tools, with budgets, scope and mandatory citations
- Status: Accepted
- Date: 2026-10-24

## Context
The assistant must combine exact logs (Elastic), catalog ownership (OpenMetadata), history (curated PG), service
graph (ontology), aggregates (SQL) and optionally semantic runbook search - always with citations, RBAC, time
windows and cost limits. Letting a model write SQL/DSL is unsafe and unauditable. Elasticsearch and OpenSearch
are not assumed to support cross-cluster search with each other.

## Decision
- Six read-only routes registered in a `SearchRouter`: `exact_logs`, `metadata_search`, `historical_incident_search`,
  `service_graph`, `sql_aggregation` (named templates only), `vector_knowledge` (optional).
- Each route has a pydantic args model (`extra="forbid"`, bounded strings, time windows with per-route maximums),
  a permission, a cost and timeout. The router validates, checks permission and **service scope**, charges the run
  budget (calls / cost units / seconds) **before** running, enforces the timeout and maps errors to short safe messages.
- Every route returns `Citation`s; keys `cN` are unique per thread; answers' `[cN]` markers are checked and
  unknown ones removed and reported (`CUSTOM opsi.answer_check`).
- Elastic is called via plain `_search` with `simple_query_string` (no wildcard/fuzzy/regexp), index chosen by tenant map.

## Consequences
- Adding a data source = adding a route + tests, not prompt engineering.
- Model quality depends on route descriptions; keep them short and specific.

## Alternatives considered
- Text-to-SQL / text-to-DSL - injection, cost and authorization risks.
- LLM-free deterministic router only - less flexible; can still be added as a pre-step (classify intent -> route).

## Verification
`tests/api/test_search_and_actions.py`, `tests/api/test_agui_contract.py::test_budget_*`, `::test_service_scope_*`.
