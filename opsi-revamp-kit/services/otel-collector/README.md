# OpenTelemetry Collector configs

| File | Use | Exporter |
|---|---|---|
| `config.prod.yaml` | staging/prod | OTLP/HTTP to `OTLP_EXPORT_ENDPOINT` with `OTLP_EXPORT_AUTH_HEADER`; content/auth attributes dropped, token/email patterns redacted, metrics converted to delta (Dynatrace) |
| `config.lab.yaml` | lab only | `debug` (basic verbosity) - never in prod |

Both validated with `otelcol-contrib validate` 0.137.0 during kit build. Run via `infrastructure/compose/opsi-revamp.compose.yml`
(receivers published on 127.0.0.1 only). Validate after any edit:
```bash
docker run --rm -v $PWD/config.prod.yaml:/c.yaml -e OTLP_EXPORT_ENDPOINT=https://x -e OTLP_EXPORT_AUTH_HEADER=x \
  -e DEPLOYMENT_ENVIRONMENT=lab otel/opentelemetry-collector-contrib:0.137.0 validate --config=/c.yaml
```
Policy: ADR-0011, consultation 09.
