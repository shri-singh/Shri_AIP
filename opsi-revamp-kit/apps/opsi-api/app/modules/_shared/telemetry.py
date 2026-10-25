"""OpenTelemetry wiring + GenAI spans that never carry prompt/response content.

Rules (ADR-0011):
- Spans carry ids, counts, timings, model ids and token usage - never prompts,
  completions, tool arguments with user text, log lines or headers.
- If OpenLLMetry/Traceloop instrumentations are added later, set
  ``TRACELOOP_TRACE_CONTENT=false`` (they capture content BY DEFAULT) and
  ``OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false``.
- The collector applies a second redaction layer (services/otel-collector/config.prod.yaml).

Attribute names follow the OpenTelemetry GenAI semantic conventions
(``gen_ai.operation.name``, ``gen_ai.provider.name``, ``gen_ai.request.model``,
``gen_ai.usage.input_tokens`` ...). The conventions are still evolving - check the
version your backend (Dynatrace/Elastic) understands; older ones use ``gen_ai.system``.
"""
from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

log = logging.getLogger(__name__)

try:  # optional dependency: everything degrades to no-ops without it
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode

    _tracer = trace.get_tracer("opsi.revamp")
except ImportError:  # pragma: no cover
    trace = None  # type: ignore[assignment]
    _tracer = None


def hash_id(value: str) -> str:
    """Stable pseudonym for user ids in telemetry (not reversible without the id)."""
    salt = os.environ.get("OPSI_TELEMETRY_SALT", "opsi")
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()[:16]


def setup_tracing(service_name: str = "opsi-api") -> None:
    """Configure an OTLP/HTTP exporter to the local collector. Call once at startup.

    Reads standard env vars: OTEL_EXPORTER_OTLP_ENDPOINT (default http://127.0.0.1:4318),
    OTEL_TRACES_SAMPLER / OTEL_TRACES_SAMPLER_ARG, OTEL_RESOURCE_ATTRIBUTES.
    """
    if trace is None or os.environ.get("OTEL_SDK_DISABLED", "").lower() == "true":
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    os.environ.setdefault("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "false")
    os.environ.setdefault("TRACELOOP_TRACE_CONTENT", "false")
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)


def instrument_fastapi(app: Any) -> None:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError:  # pragma: no cover
        return
    # No header capture, health endpoints excluded.
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz,metrics")


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    if _tracer is None:
        yield None
        return
    with _tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(key, value)
        try:
            yield current
        except Exception as exc:
            current.set_status(Status(StatusCode.ERROR, type(exc).__name__))
            raise


@contextmanager
def genai_span(*, model: str, max_tokens: int, temperature: float, run_id: str, thread_id: str) -> Iterator[Any]:
    with span(f"chat {model or 'unknown'}", **{
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": "aws.bedrock",
        "gen_ai.request.model": model,
        "gen_ai.request.max_tokens": max_tokens,
        "gen_ai.request.temperature": temperature,
        "opsi.run_id": run_id,
        "opsi.thread_id": thread_id,
        "opsi.llm.gateway": "portkey",
    }) as current:
        yield current


def record_usage(current: Any, *, input_tokens: int | None, output_tokens: int | None,
                 finish_reason: str | None) -> None:
    if current is None:
        return
    if input_tokens is not None:
        current.set_attribute("gen_ai.usage.input_tokens", input_tokens)
    if output_tokens is not None:
        current.set_attribute("gen_ai.usage.output_tokens", output_tokens)
    if finish_reason:
        current.set_attribute("gen_ai.response.finish_reasons", [finish_reason])


def current_trace_id() -> str | None:
    if trace is None:
        return None
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx and ctx.trace_id else None
