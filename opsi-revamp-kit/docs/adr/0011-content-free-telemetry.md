# ADR-0011: OpenTelemetry with GenAI conventions and no content
- Status: Accepted
- Date: 2026-10-24

## Context
We want traces across browser -> runtime -> FastAPI -> routes -> Portkey/Bedrock and collectors, with token usage
and latency. Prompts, completions, tool arguments and log lines may contain PHI/PII/secrets. OpenLLMetry
instrumentations capture content **by default**; the debug exporter keeps data in container logs.

## Decision
- Spans carry ids, counts, timings, model ids, token usage, finish reasons (`gen_ai.*` attributes), route names,
  run/thread ids and a pseudonymised user id - never content.
- Defaults: `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false`, `TRACELOOP_TRACE_CONTENT=false`.
- Collector (`services/otel-collector/config.prod.yaml`): attributes processor drops content/auth/query keys,
  redaction processor masks token/email patterns, OTLP/HTTP to the approved backend, no debug exporter in prod.
- Applications export only to the local collector (127.0.0.1:4318); the collector owns credentials to the backend.

## Consequences
- Debugging content issues requires reproducing with synthetic data, not reading traces.
- GenAI semantic conventions are evolving; the backend may expect `gen_ai.system` (older) - adjust attribute names
  in `_shared/telemetry.py` if dashboards don't light up.

## Verification
`otelcol-contrib validate` on both configs (run during kit build); code review: `telemetry.py` sets no content attributes.
