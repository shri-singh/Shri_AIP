# 08 - Portkey -> Amazon Bedrock: configuration, operations, costs

## The question
"How do I configure the model path, pick models, control cost and handle failures?"

## Short answer
FastAPI calls Portkey's OpenAI-compatible Chat Completions (streaming, tools) with either a **Model Catalog provider
slug** + model id or a **Portkey config** that encodes routing/fallbacks/guardrails. Portkey calls Bedrock with an
identity allowed to invoke only approved models/inference profiles. Model ids come from configuration.

## Configuration recipes
```bash
# A) Provider slug (Model Catalog) - simplest
PORTKEY_API_KEY=...            PORTKEY_PROVIDER=@bedrock-prod      LLM_MODEL=<model or inference-profile id>
# B) Config id - routing, fallbacks, retries, guardrails managed in Portkey
PORTKEY_API_KEY=...            PORTKEY_CONFIG=pc-opsi-prod-xxxx      LLM_MODEL=   (config decides)
# C) Self-hosted gateway (data stays in your VPC)
PORTKEY_BASE_URL=https://portkey-gw.internal.corp.example/v1  (+ A or B)
```
Discover what your account can call:
```bash
aws bedrock list-inference-profiles --region $AWS_REGION --query 'inferenceProfileSummaries[].{id:inferenceProfileId,name:inferenceProfileName,status:status}'
aws bedrock list-foundation-models --region $AWS_REGION --by-output-modality TEXT --query 'modelSummaries[].modelId'
```
Many newer models must be invoked through an **inference profile** (cross-region ids like `us.<vendor>.<model>...`);
the IAM policy then needs the profile ARN plus the foundation-model ARN in each routed region.

## Portkey config ideas (JSON, maintained in Portkey)
```json
{
  "strategy": {"mode": "fallback"},
  "targets": [
    {"provider": "@bedrock-prod", "override_params": {"model": "<primary profile id>"}},
    {"provider": "@bedrock-prod", "override_params": {"model": "<smaller/fallback profile id>"}}
  ],
  "retry": {"attempts": 2, "on_status_codes": [429, 500, 502, 503, 504]},
  "cache": {"mode": "simple", "max_age": 0}
}
```
Verify field names against your Portkey version's config docs; keep caching **off** for chats containing client data
unless approved.

## Token and cost control
- Prompt size: history capped at 40 messages; tool results compact; fenced data; consider trimming old tool payloads.
- Output cap: `LLM_MAX_OUTPUT_TOKENS` (2048 default).
- Per-run budgets: tool calls, cost units, seconds, LLM turns (`AGENT_*`).
- Observe: `gen_ai.usage.input_tokens/output_tokens` on spans; `agent_runs.input_tokens/output_tokens` in DB.
- Monthly estimate: runs/day x avg tokens x price per 1k tokens (from your Bedrock pricing page) - track in a dashboard.

## Failure modes
| Symptom | Likely cause | Fix |
|---|---|---|
| 401 from Portkey | wrong/expired key | rotate key |
| 400 "model not found"/validation | model id vs profile id, region | use `list-inference-profiles`; set `LLM_MODEL` accordingly |
| 403 AccessDenied (Bedrock) | IAM policy lacks profile/model ARN or model access not granted | update policy; request model access |
| 429 throttling | Bedrock quotas | Portkey retries/fallback; request quota increase; lower concurrency |
| stream ends without tool calls JSON | provider translation edge case | log `finish_reason`; try non-streaming test; update SDK |
| 400 about `stream_options` | gateway rejects usage option | `LLM_STREAM_USAGE=false` |

## Direct Bedrock fallback (if Portkey is unavailable)
Implement `BedrockGateway` with `boto3.client("bedrock-runtime").converse_stream(modelId=..., messages=..., toolConfig=...)`
mapping events to `TextDelta/ToolCallDelta/Finish`. Only with approval - it bypasses Portkey governance.

## Verify
Phase 4.2 smoke script; one real agent run in staging; Portkey logs show the request with metadata `_user` (hash) and
`thread`; Bedrock CloudWatch metrics show invocations.
