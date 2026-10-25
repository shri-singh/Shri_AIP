# OpenTelemetry

## Env vars (applications)
```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
OTEL_SERVICE_NAME=opsi-api
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=0.2
OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false
TRACELOOP_TRACE_CONTENT=false        # OpenLLMetry captures content by default!
OTEL_SDK_DISABLED=false
```

## Collector
```bash
docker run --rm -v $PWD/services/otel-collector/config.prod.yaml:/c.yaml --env-file /etc/opsi/revamp.env \
  otel/opentelemetry-collector-contrib:0.137.0 validate --config=/c.yaml
curl -s http://127.0.0.1:13133/                       # health_check extension
docker logs --tail 100 opsi-revamp-otel-collector-1    # export errors (401 = token, 400 = payload/temporality)
# send a test span (needs otel-cli or python):
python3 - <<'PY'
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
p = TracerProvider(); p.add_span_processor(SimpleSpanProcessor(OTLPSpanExporter(endpoint="http://127.0.0.1:4318/v1/traces")))
trace.set_tracer_provider(p)
with trace.get_tracer("smoke").start_as_current_span("opsi.smoke") as s: s.set_attribute("opsi.canary", "ZZ-CANARY-1")
p.shutdown(); print("sent")
PY
```

## Canary for "no content"
Send a chat containing `ZZ-CANARY-<random>` -> search the backend for that string: expected 0 hits; spans
`chat <model>` should exist with `gen_ai.usage.*`.

## Attribute names used by the kit
`gen_ai.operation.name`, `gen_ai.provider.name`, `gen_ai.request.model`, `gen_ai.request.max_tokens`,
`gen_ai.request.temperature`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.response.finish_reasons`,
`opsi.run_id`, `opsi.thread_id`, `opsi.route`, `opsi.request_id`, `opsi.llm.gateway`.
