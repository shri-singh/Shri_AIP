"""LLM gateway: FastAPI -> Portkey -> Amazon Bedrock. Server-side only (no model keys in the browser).

Portkey exposes an OpenAI-compatible Chat Completions API and translates to
Bedrock. Configure ONE of:
- ``PORTKEY_PROVIDER`` (Model Catalog provider slug, e.g. ``@bedrock-prod``) + ``LLM_MODEL``
  (the Bedrock model id or inference-profile id exactly as enabled in your account), or
- ``PORTKEY_CONFIG`` (a Portkey config id holding routing/fallbacks/guardrails).
``PORTKEY_BASE_URL`` points at a self-hosted gateway if your company runs one.

Verified against portkey-ai 2.3.x (constructor accepts api_key, base_url,
provider, config, trace_id, metadata, request_timeout). Model ids are NOT
hard-coded: list what your account can use with
``aws bedrock list-inference-profiles`` / ``list-foundation-models``.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

from .._shared.errors import UpstreamUnavailable
from .._shared.settings import ApiSettings


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolCallDelta:
    index: int
    id: str | None = None
    name: str | None = None
    arguments: str = ""


@dataclass
class Finish:
    reason: str | None
    input_tokens: int | None = None
    output_tokens: int | None = None


LLMEvent = TextDelta | ToolCallDelta | Finish


class LLMGateway(Protocol):
    model_ref: str

    def stream_chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *,
                    trace_id: str | None = None, metadata: dict[str, str] | None = None) -> AsyncIterator[LLMEvent]: ...

    async def embed(self, text: str) -> list[float]: ...


class PortkeyGateway:
    def __init__(self, settings: ApiSettings, client: Any | None = None) -> None:
        if not settings.portkey_api_key:
            raise ValueError("PORTKEY_API_KEY is required")
        if not (settings.portkey_provider or settings.portkey_config):
            raise ValueError("set PORTKEY_PROVIDER (+ LLM_MODEL) or PORTKEY_CONFIG")
        self.s = settings
        self.model_ref = settings.llm_model or "portkey-config-default"
        if client is None:
            from portkey_ai import AsyncPortkey

            kwargs: dict[str, Any] = {"api_key": settings.portkey_api_key,
                                      "request_timeout": settings.llm_request_timeout_s}
            if settings.portkey_base_url:
                kwargs["base_url"] = settings.portkey_base_url
            if settings.portkey_provider:
                kwargs["provider"] = settings.portkey_provider
            if settings.portkey_config:
                kwargs["config"] = settings.portkey_config
            client = AsyncPortkey(**kwargs)
        self.client = client

    async def stream_chat(self, messages, tools, *, trace_id=None, metadata=None):
        kwargs: dict[str, Any] = {
            "messages": messages, "stream": True, "max_tokens": self.s.llm_max_output_tokens,
            "temperature": self.s.llm_temperature,
        }
        if self.s.llm_stream_usage:
            kwargs["stream_options"] = {"include_usage": True}
        if self.s.llm_model:
            kwargs["model"] = self.s.llm_model
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        client = self.client
        if trace_id or metadata:
            client = client.with_options(trace_id=trace_id, metadata=metadata or {})
        try:
            stream = await client.chat.completions.create(**kwargs)
            finish: Finish | None = None
            async for chunk in stream:
                usage = getattr(chunk, "usage", None)
                for choice in getattr(chunk, "choices", None) or []:
                    delta = choice.delta
                    if getattr(delta, "content", None):
                        yield TextDelta(delta.content)
                    for tc in getattr(delta, "tool_calls", None) or []:
                        fn = getattr(tc, "function", None)
                        yield ToolCallDelta(index=tc.index or 0, id=getattr(tc, "id", None),
                                            name=getattr(fn, "name", None) if fn else None,
                                            arguments=(getattr(fn, "arguments", None) or "") if fn else "")
                    if choice.finish_reason:
                        finish = Finish(choice.finish_reason)
                if usage is not None:
                    finish = finish or Finish(None)
                    finish.input_tokens = getattr(usage, "prompt_tokens", None)
                    finish.output_tokens = getattr(usage, "completion_tokens", None)
            yield finish or Finish("stop")
        except Exception as exc:  # noqa: BLE001 - provider errors must not leak request details
            raise UpstreamUnavailable(f"model gateway error ({type(exc).__name__})") from None

    async def embed(self, text: str) -> list[float]:
        if not self.s.embedding_model:
            raise UpstreamUnavailable("EMBEDDING_MODEL is not configured")
        try:
            result = await self.client.embeddings.create(model=self.s.embedding_model, input=text[:8000])
            return list(result.data[0].embedding)
        except Exception as exc:  # noqa: BLE001
            raise UpstreamUnavailable(f"embedding gateway error ({type(exc).__name__})") from None


@dataclass
class ScriptedTurn:
    """One model turn: optional text, optional tool calls [(name, args_dict)], finish reason."""

    text: str = ""
    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    fail: bool = False


class ScriptedLLM:
    """Deterministic fake used by tests and the lab app. Streams text in small chunks like a real model."""

    model_ref = "scripted-test-model"

    def __init__(self, turns: list[ScriptedTurn], chunk: int = 12) -> None:
        self.turns = list(turns)
        self.chunk = chunk
        self.requests: list[dict[str, Any]] = []

    async def stream_chat(self, messages, tools, *, trace_id=None, metadata=None):
        self.requests.append({"messages": messages, "tools": [t["function"]["name"] for t in tools],
                              "metadata": metadata})
        if not self.turns:
            yield TextDelta("I have no further steps.")
            yield Finish("stop", 10, 5)
            return
        turn = self.turns.pop(0)
        if turn.fail:
            raise UpstreamUnavailable("model gateway error (SimulatedOutage)")
        for i in range(0, len(turn.text), self.chunk):
            yield TextDelta(turn.text[i:i + self.chunk])
        for index, (name, args) in enumerate(turn.tool_calls):
            payload = json.dumps(args)
            yield ToolCallDelta(index=index, id=f"call_{len(self.requests)}_{index}", name=name, arguments=payload[:5])
            yield ToolCallDelta(index=index, arguments=payload[5:])
        yield Finish("tool_calls" if turn.tool_calls else "stop", 100, 20)

    async def embed(self, text: str) -> list[float]:
        return [0.01] * 1024
