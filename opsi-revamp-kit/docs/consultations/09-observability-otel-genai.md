# 09 - Observability for the platform itself

## The question
"How do we trace a question end-to-end and watch LLM latency/cost without leaking content?"

## Short answer
App SDKs -> local OTel Collector (loopback) -> approved backend. Spans carry ids, timings, model ids and token counts
using GenAI semantic conventions; content capture is off at three layers (code, env defaults, collector processors).

## What is instrumented in the kit
| Span | Where | Key attributes |
|---|---|---|
| FastAPI server spans | `instrument_fastapi(app)` (health excluded) | http route/status |
| `chat <model>` | orchestrator per LLM turn | `gen_ai.operation.name=chat`, `gen_ai.provider.name=aws.bedrock`, `gen_ai.request.model`, `gen_ai.usage.*`, `gen_ai.response.finish_reasons`, `opsi.run_id`, `opsi.thread_id` |
| `opsi.route <name>` | SearchRouter | `opsi.route`, `opsi.request_id` |
Correlation: `x-request-id` flows browser -> runtime -> FastAPI; `traceparent` is forwarded by the runtime (allowlisted).

## Adding more
- Collectors: `opentelemetry-instrumentation-requests`, `-botocore`; wrap each window in a span `opsi.window` with
  `opsi.source`, `opsi.records`, `opsi.quarantined`.
- Metrics: use OTel metrics API for counters (runs, errors by code, windows committed) or derive from spans in the backend.
- Logs: JSON logs already structured; ship journald via the collector's `journald` receiver or CloudWatch agent.

## GenAI conventions caveat
The conventions are still evolving (`gen_ai.system` -> `gen_ai.provider.name`, message events). If your backend's AI
dashboards stay empty, check which attribute names it expects and adapt `telemetry.py` (one place).

## Dynatrace specifics
- OTLP endpoint `https://<env>.live.dynatrace.com/api/v2/otlp` with `Authorization: Api-Token ...`
  (scopes `openTelemetryTrace.ingest`, `metrics.ingest`, `logs.ingest`); metrics must be **delta** temporality
  (collector `cumulativetodelta` processor included).
- Alternatively an ActiveGate as an OTLP endpoint inside the network.

## Sampling
Start `parentbased_traceidratio` 0.2; keep 100 % for errors via tail sampling in the collector (`tail_sampling` processor)
if the backend's cost allows.

## Verify "no content"
Canary test (phase 5.3): send a unique marker in a chat; search backend for it; expect zero hits.
