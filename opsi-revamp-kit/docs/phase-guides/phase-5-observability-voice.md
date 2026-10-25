# Phase 5 - observability and voice

## 5.1 Collector
```bash
sudo vi /etc/opsi/revamp.env
#  OTLP_EXPORT_ENDPOINT=https://<env-id>.live.dynatrace.com/api/v2/otlp
#  OTLP_EXPORT_AUTH_HEADER=Api-Token <token: openTelemetryTrace.ingest, metrics.ingest, logs.ingest>
#  DEPLOYMENT_ENVIRONMENT=staging
docker run --rm -v $PWD/services/otel-collector/config.prod.yaml:/c.yaml --env-file /etc/opsi/revamp.env \
  otel/opentelemetry-collector-contrib:0.137.0 validate --config=/c.yaml
scripts/compose_safe.sh opsi-revamp up && curl -s http://127.0.0.1:13133/
```

## 5.2 Applications
- API: `install_revamp(app, container, tracing=True)`; env `OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318`,
  `OTEL_TRACES_SAMPLER=parentbased_traceidratio`, `OTEL_TRACES_SAMPLER_ARG=0.2`, content flags false (defaults set in code).
- Collectors: optional - add `opentelemetry-instrumentation-requests` + `-botocore` and `setup_tracing("opsi-collectors")`.
- Runtime: forwards `traceparent` to FastAPI (allowlisted) so browser-initiated traces can join if the SPA sends it.

## 5.3 Verify "no content" before enabling in prod
In staging, run a chat containing a fake marker (`ZZ-CANARY-1234` and a fake email); search the backend for the marker
(should find nothing) and for spans `chat <model>` (should show token counts). Repeat after every instrumentation change.

## 5.4 Dashboards and alerts (suggested)
- Agent: runs/min, error rate by `error_code`, p95 latency of `chat <model>` spans, tokens/run, tool calls/run, budget exhaustion.
- Retrieval: route latency/error per route, citations per answer, `unknownCitations` events.
- Ingestion: windows committed/failed, records, quarantine ratio, outbox dead letters, curated freshness.

## 5.5 Voice prototype (lab)
Follow [../voice-roadmap.md](../voice-roadmap.md) Stage A: IAM voice statement, lifecycle rule, `OPSI_VOICE_ENABLED=true`
in lab, a push-to-talk button that posts to `/api/v2/voice/transcribe` and drops the returned text into the chat input
for the user to confirm.

## Exit criteria
Traces visible with GenAI attributes and no content; alerts wired; voice prototype demoed in lab with consent flow.
