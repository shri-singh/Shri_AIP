# 05 - Retrieval routing, reranking, citations and evaluation

## The question
"How does the assistant decide where to look, how do we keep answers grounded, and how do we measure quality?"

## Short answer
The model chooses among **typed, read-only tools** (the six routes); the server enforces validation, scope, budgets
and citations. Grounding is enforced structurally: only server-issued citation keys survive, evidence is stored per
message, and the UI shows sources. Quality is measured with a golden-question set and user feedback, not vibes.

## Routing strategies
| Strategy | How | When |
|---|---|---|
| **Tool-calling (implemented)** | route specs as tools; model picks; server validates | default; flexible |
| Deterministic pre-router | classify intent (regex/small model) -> force a first route (e.g. incident page -> `historical_incident_search` + `exact_logs`) | latency/cost sensitive flows |
| Plan-then-execute | model writes a plan of route calls, server executes in parallel | multi-source questions; later |
Parallelism: the orchestrator runs calls sequentially (simple budgets). If latency matters, execute independent server
calls of one turn concurrently with `asyncio.gather` while still charging the budget first.

## Making routes work well with models
- Short, specific descriptions with *when to use*; field descriptions with formats ("UTC ISO-8601").
- Keep schemas flat (no `$defs`); enums for templates.
- Return compact items with `cite` keys; put limits/truncation in `notes`.
- Error results are informative (`invalid_arguments: time window exceeds ...`) so the model can self-correct.

## Reranking (optional)
When a route returns many candidates (runbooks, historical incidents), rerank before handing them to the model:
- Bedrock offers rerank models (e.g. Amazon Rerank, Cohere Rerank) via the `bedrock-agent-runtime` Rerank API - verify
  availability in your region/account before designing around it.
- Or a cheap lexical rerank (BM25 over title+excerpt) - deterministic, no extra service.
Implement as a post-processor in the route (`items = rerank(query, items)[:k]`) and keep citations aligned.

## Citations end-to-end
1. Route returns `Citation(source_type, source_ref, title, event_time, snippet, url)`.
2. `CitationRegistry` assigns `cN` (per thread, deduped by source) and tags items with `cite`.
3. Model is instructed to cite; `check_answer` removes unknown keys; `CUSTOM opsi.answer_check` reports them.
4. Evidence persisted with the answering message id; UI shows an evidence panel; `/threads/{id}/evidence` API.
Possible next steps: claim-level verification (second pass asks the model to list claims without citations -> UI flags),
or require at least one citation per paragraph for incident summaries.

## Evaluation
- **Golden set**: 30-100 real (redacted) questions per domain with expected sources (e.g. "why did checkout fail at 10:05"
  -> must cite the problem + an error signature). Store as JSONL; run nightly through the agent with a fixed model;
  score: route recall (expected routes called), citation precision (cited sources in expected set), answer rubric.
- **Online**: thumbs up/down + reason codes (`feedback` table), `unknownCitations` rate, budget exhaustion rate,
  time-to-first-token.
- **Regression gate**: block model/prompt changes that drop golden-set scores.

## Pitfalls
- Over-broad log queries -> noise; prefer service + narrow window from the UI context.
- Mixed identifiers (service names vs Dynatrace ids) -> empty results; pick a canonical id (consultation 06).
- Letting the model write DSL/SQL - don't (ADR-0008).

## Verify
`pytest tests/api/test_search_and_actions.py`; golden-set report; feedback dashboard.
