# ADR-0009: All inference via Portkey -> Amazon Bedrock, server-side only
- Status: Accepted
- Date: 2026-10-24

## Context
Opsi already routes model traffic through Portkey to Bedrock. Corporate policy requires central keys, routing,
guardrails and cost tracking; model ids differ per account/region and change over time (inference profiles).

## Decision
- One `LLMGateway` interface; `PortkeyGateway` uses `portkey_ai.AsyncPortkey` (OpenAI-compatible streaming) with
  `PORTKEY_PROVIDER` (Model Catalog slug) + `LLM_MODEL`, **or** a `PORTKEY_CONFIG` holding routing/fallbacks.
  `PORTKEY_BASE_URL` targets a self-hosted gateway when available.
- No model ids hard-coded; they come from configuration after `aws bedrock list-inference-profiles` confirms access.
- Metadata sent to Portkey: pseudonymised user (`hash_id`) and thread id only. Prompt/response caching off for
  sensitive tenants unless explicitly approved.
- No model keys or direct model calls from the browser or the Node runtime.

## Consequences
- Portkey is on the critical path: its outage -> `RUN_ERROR llm_unavailable` (handled, tested).
- Bedrock access policy belongs to the identity Portkey uses (`infrastructure/aws/iam/bedrock-invoke-policy.json`).

## Alternatives considered
- Direct `bedrock-runtime` from FastAPI - bypasses existing governance; possible fallback if Portkey is unavailable
  (add a `BedrockGateway` implementing the same interface).

## Verification
`apps/opsi-api/app/modules/llm/gateway.py`; contract tests use `ScriptedLLM`; Phase 4 guide includes a live smoke
(`tools/kb/ask.py --llm` uses the same env variables).
