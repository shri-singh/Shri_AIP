"""Agent loop: AG-UI RunAgentInput -> AG-UI events.

Per run:
  RUN_STARTED -> STATE_SNAPSHOT -> [ per model turn:
      TEXT_MESSAGE_START/CONTENT.../END                      (streamed answer text)
      TOOL_CALL_START/ARGS/END + TOOL_CALL_RESULT            (server retrieval routes)
      TOOL_CALL_START/ARGS/END (no result)                   (browser UI actions -> run ends, client
                                                              executes and starts a new run with the result)
      STATE_DELTA                                            (evidence, phase, budget) ]
  -> RUN_FINISHED   |  RUN_ERROR (safe message + code)

Trust model (ADR-0005/0010/0013):
- The database is the source of truth for history. Only NEW user messages and tool
  results for PENDING browser tool calls are accepted from the client; client-supplied
  assistant/system messages are ignored, so history cannot be forged.
- Identity comes from the Principal; ``state``/``forwardedProps``/context are hints.
- Tool and action arguments are validated server-side; budgets bound every run.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from ag_ui.core import (
    BaseEvent,
    CustomEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

from .._shared.container import OpsiServices
from .._shared.errors import BudgetExceeded, UpstreamUnavailable
from .._shared.redaction import Redactor
from .._shared.telemetry import current_trace_id, genai_span, hash_id, record_usage
from ..chat.models import StoredMessage
from ..identity.principal import Principal
from ..llm.gateway import Finish, TextDelta, ToolCallDelta
from ..rag.citations import CitationRegistry
from ..rag.prompt import SYSTEM_PROMPT, fence, ui_context_block
from ..search.contracts import RouteContext, RunBudget
from ..search.router import ToolError
from .approvals import Approval
from .context import extract_ui_context
from .state import EvidenceRef, StateTracker
from .ui_actions import UI_ACTIONS, ActionRejected, approval_expiry, validate_ui_action

log = logging.getLogger(__name__)

MAX_USER_CHARS = 20_000
MAX_TOOL_RESULT_CHARS = 8_000
HISTORY_MESSAGES = 40


class RunRejected(Exception):
    """Raised before streaming starts; the endpoint maps it to an HTTP error."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class _Call:
    id: str
    name: str
    arguments: str


def _text_of(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for part in content:
        text = getattr(part, "text", None) if not isinstance(part, dict) else part.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def _wire(message: Any) -> dict[str, Any]:
    return message.model_dump(by_alias=True, exclude_none=True, mode="json")


def pending_frontend_calls(history: list[StoredMessage]) -> dict[str, str]:
    """tool_call_id -> action name for browser actions that have no result yet."""
    issued: dict[str, str] = {}
    answered: set[str] = set()
    for m in history:
        data = m.content_json
        if m.role == "assistant":
            for call in data.get("toolCalls") or []:
                name = (call.get("function") or {}).get("name")
                if name in UI_ACTIONS:
                    issued[call["id"]] = name
        elif m.role == "tool" and data.get("toolCallId"):
            answered.add(data["toolCallId"])
    return {cid: name for cid, name in issued.items() if cid not in answered}


def to_model_messages(history: list[StoredMessage]) -> list[dict[str, Any]]:
    """Stored AG-UI messages -> OpenAI-style messages for Portkey, starting at a user turn,
    with every tool call paired with a (possibly synthetic) tool result."""
    window = history[-HISTORY_MESSAGES:]
    while window and window[0].role != "user":
        window = window[1:]
    out: list[dict[str, Any]] = []
    answered = {m.content_json.get("toolCallId") for m in window if m.role == "tool"}
    for m in window:
        data = m.content_json
        if m.role == "user":
            out.append({"role": "user", "content": m.content_text or _text_of(data.get("content"))})
        elif m.role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": data.get("content") or None}
            calls = data.get("toolCalls") or []
            if calls:
                entry["tool_calls"] = [{"id": c["id"], "type": "function", "function": c["function"]} for c in calls]
            out.append(entry)
            for c in calls:
                if c["id"] not in answered:
                    out.append({"role": "tool", "tool_call_id": c["id"],
                                "content": fence({"error": "no_result", "message": "No result was returned."}, "system")})
        elif m.role == "tool":
            name = data.get("toolName") or "tool"
            out.append({"role": "tool", "tool_call_id": data.get("toolCallId"),
                        "content": fence(_text_of(data.get("content"))[:MAX_TOOL_RESULT_CHARS], f"tool:{name}")})
    return out


class Orchestrator:
    def __init__(self, svc: OpsiServices, principal: Principal, request_id: str | None = None) -> None:
        self.svc = svc
        self.p = principal
        self.request_id = request_id
        self.redactor = Redactor("strict")
        self.approvals = (svc.extras or {}).get("approvals")

    # ------------------------------------------------------------------ pre-flight (before streaming)
    async def prepare(self, inp: Any, agent_id: str) -> None:
        if agent_id not in self.svc.settings.copilot_agent_ids:
            raise RunRejected(404, "unknown agent")
        try:
            self.thread_id = uuid.UUID(str(inp.thread_id))
        except ValueError:
            raise RunRejected(400, "threadId must be a UUID") from None
        thread = await self.svc.chat.get_thread(self.p, self.thread_id)
        if thread is not None and thread.owner_id != self.p.user_id:
            raise RunRejected(404, "thread not found")  # visible-but-shared threads are read-only
        self.thread = thread

    # ------------------------------------------------------------------ main
    async def run(self, inp: Any, agent_id: str) -> AsyncIterator[BaseEvent]:
        run_id = str(inp.run_id)[:100]
        thread_key = str(self.thread_id)
        open_text: str | None = None
        status, error_code = "finished", None
        budget = RunBudget(self.svc.settings.agent_max_tool_calls, self.svc.settings.agent_max_cost_units,
                           self.svc.settings.agent_max_seconds)
        usage_in = usage_out = 0
        yield RunStartedEvent(thread_id=thread_key, run_id=run_id)
        try:
            ui_context, warnings = extract_ui_context(inp.context, self.p)
            history = await self.svc.chat.list_messages(self.p, self.thread_id, 2000) if self.thread else []
            accepted, ignored = self._reconcile(inp.messages, history, run_id)
            if self.thread is None:
                first = next((m.content_text for m in accepted if m.role == "user"), None) or "New investigation"
                self.thread = await self.svc.chat.create_thread(
                    self.p, self.thread_id, title=first[:80], folder_id=None,
                    linked_incident_id=ui_context.get("incident_id"), linked_service_id=ui_context.get("service_id"),
                    agent_id=agent_id)
            if accepted:
                await self.svc.chat.append_messages(self.p, self.thread_id, accepted)
            if ignored:
                warnings.append(f"{ignored} client-supplied message(s) ignored")
                await self.svc.audit.record(tenant_id=self.p.tenant_id, actor_id=self.p.user_id,
                                            action="agent.client_messages_ignored", target=thread_key,
                                            outcome="denied", request_id=self.request_id, detail={"count": ignored})
            stored_state = await self.svc.chat.get_agent_state(self.p, self.thread_id)
            tracker = StateTracker({**stored_state, "phase": "retrieving", "pending_approvals": [],
                                    **{k: ui_context[k] for k in ("incident_id", "service_id") if k in ui_context},
                                    **({"time_from": ui_context["time_from"], "time_to": ui_context["time_to"]}
                                       if "time_from" in ui_context and "time_to" in ui_context else {})})
            yield StateSnapshotEvent(snapshot=tracker.dump())
            tracker.mark_emitted()
            if warnings:
                yield CustomEvent(name="opsi.warnings", value=warnings)
            if not accepted:
                yield RunFinishedEvent(thread_id=thread_key, run_id=run_id)
                return

            await self.svc.chat.start_run(self.p, self.thread_id, run_id, self.svc.llm.model_ref, current_trace_id())
            history = history + accepted
            citations = CitationRegistry(await self.svc.chat.list_evidence(self.p, self.thread_id))
            offered = {t.name for t in (inp.tools or [])}
            ui_tools = [a.tool_spec() for a in UI_ACTIONS.values() if a.name in offered and self.p.can(a.permission)]
            route_ctx = RouteContext(self.p, budget, self.request_id, ui_context)
            context_note = ui_context_block(ui_context)
            last_assistant_id: str | None = None
            tools_allowed = True

            for turn in range(self.svc.settings.agent_max_llm_turns + 1):
                final_turn = turn == self.svc.settings.agent_max_llm_turns or not tools_allowed
                messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                if context_note:
                    messages.append({"role": "system", "content": context_note})
                if final_turn and turn > 0:
                    messages.append({"role": "system", "content": "Tool use is finished for this run (step or "
                                     "budget limit). Answer now with the evidence you have and say what is missing."})
                messages += to_model_messages(history)
                tools = [] if final_turn else self.svc.search.tool_specs() + ui_tools

                msg_id = f"asst-{uuid.uuid4().hex[:16]}"
                text_parts: list[str] = []
                calls: dict[int, _Call] = {}
                with genai_span(model=self.svc.llm.model_ref, max_tokens=self.svc.settings.llm_max_output_tokens,
                                temperature=self.svc.settings.llm_temperature, run_id=run_id,
                                thread_id=thread_key) as llm_span:
                    async for ev in self.svc.llm.stream_chat(messages, tools, trace_id=current_trace_id(),
                                                             metadata={"_user": hash_id(self.p.user_id),
                                                                       "thread": thread_key}):
                        if isinstance(ev, TextDelta) and ev.text:
                            if open_text is None:
                                open_text = msg_id
                                yield TextMessageStartEvent(message_id=msg_id, role="assistant")
                            text_parts.append(ev.text)
                            yield TextMessageContentEvent(message_id=msg_id, delta=ev.text)
                        elif isinstance(ev, ToolCallDelta):
                            call = calls.setdefault(ev.index, _Call(ev.id or "", ev.name or "", ""))
                            call.id = call.id or (ev.id or "")
                            call.name = call.name or (ev.name or "")
                            call.arguments += ev.arguments
                        elif isinstance(ev, Finish):
                            usage_in += ev.input_tokens or 0
                            usage_out += ev.output_tokens or 0
                            record_usage(llm_span, input_tokens=ev.input_tokens, output_tokens=ev.output_tokens,
                                         finish_reason=ev.reason)
                if open_text is not None:
                    yield TextMessageEndEvent(message_id=open_text)
                    open_text = None

                text = "".join(text_parts)
                check = citations.check_answer(text)
                if check.unknown:
                    yield CustomEvent(name="opsi.answer_check", value={"messageId": msg_id,
                                                                       "unknownCitations": check.unknown})
                ordered = [calls[i] for i in sorted(calls)] if not final_turn else []
                for i, call in enumerate(ordered):
                    call.id = call.id or f"call-{run_id}-{turn}-{i}"
                # Validate browser actions first so the persisted assistant message carries exactly
                # the normalised arguments (incl. approval ids) that the browser will receive.
                frontend: list[_Call] = []
                rejected: dict[str, ActionRejected] = {}
                for call in ordered:
                    if call.name not in UI_ACTIONS:
                        continue
                    try:
                        if call.name not in offered:
                            raise ActionRejected("unavailable", f"{call.name} is not available in the current view")
                        args = validate_ui_action(call.name, call.arguments or "{}", self.p)
                        if UI_ACTIONS[call.name].requires_approval:
                            args = await self._create_approval(call, args, run_id)
                            tracker.state.pending_approvals.append(args["approval_id"])
                        call.arguments = json.dumps(args, separators=(",", ":"))
                        frontend.append(call)
                    except ActionRejected as exc:
                        rejected[call.id] = exc
                assistant: dict[str, Any] = {"id": msg_id, "role": "assistant"}
                if check.text:
                    assistant["content"] = check.text
                if ordered:
                    assistant["toolCalls"] = [{"id": c.id, "type": "function",
                                               "function": {"name": c.name, "arguments": c.arguments or "{}"}}
                                              for c in ordered]
                if check.text or ordered:
                    stored = StoredMessage(message_id=msg_id, role="assistant", content_text=check.text or None,
                                           content_json=assistant, run_id=run_id, author_id=f"agent:{agent_id}")
                    history.append(stored)
                    await self.svc.chat.append_messages(self.p, self.thread_id, [stored])
                    last_assistant_id = msg_id
                if not ordered:
                    break

                for call in ordered:
                    if call.id in rejected:
                        exc = rejected[call.id]
                        async for e in self._server_result(call, {"error": exc.code, "message": exc.message},
                                                           msg_id, run_id, history, status="denied"):
                            yield e
                    elif call.name not in UI_ACTIONS:
                        async for e in self._run_route(call, msg_id, run_id, route_ctx, citations, history, tracker):
                            yield e
                        if budget.calls >= budget.max_calls or budget.cost >= budget.max_cost:
                            tools_allowed = False
                patch = tracker.update(budget={"calls": budget.calls, "max_calls": budget.max_calls,
                                               "cost": budget.cost, "max_cost": budget.max_cost})
                if patch:
                    yield StateDeltaEvent(delta=patch)

                if frontend:
                    for call in frontend:
                        yield ToolCallStartEvent(tool_call_id=call.id, tool_call_name=call.name,
                                                 parent_message_id=msg_id)
                        yield ToolCallArgsEvent(tool_call_id=call.id, delta=call.arguments)
                        yield ToolCallEndEvent(tool_call_id=call.id)
                    patch = tracker.update(phase="awaiting_user")
                    if patch:
                        yield StateDeltaEvent(delta=patch)
                    break

            patch = tracker.update(phase="done" if tracker.state.phase != "awaiting_user" else "awaiting_user")
            if patch:
                yield StateDeltaEvent(delta=patch)
            await self.svc.chat.add_evidence(self.p, self.thread_id, citations.new_evidence(last_assistant_id))
            await self.svc.chat.save_agent_state(self.p, self.thread_id, tracker.dump(), ui_context)
            yield RunFinishedEvent(thread_id=thread_key, run_id=run_id)
        except asyncio.CancelledError:
            status, error_code = "cancelled", "client_disconnected"
            raise
        except UpstreamUnavailable as exc:
            status, error_code = "error", "llm_unavailable"
            if open_text is not None:
                yield TextMessageEndEvent(message_id=open_text)
            yield RunErrorEvent(message=f"{exc} - please retry.", code=error_code)
        except Exception:  # noqa: BLE001
            log.exception("agent run failed request_id=%s", self.request_id)
            status, error_code = "error", "internal_error"
            if open_text is not None:
                yield TextMessageEndEvent(message_id=open_text)
            yield RunErrorEvent(message=f"Internal error (request {self.request_id or 'n/a'}).", code=error_code)
        finally:
            if self.thread is not None:
                try:
                    await asyncio.shield(self.svc.chat.finish_run(
                        self.p, run_id, status, input_tokens=usage_in or None, output_tokens=usage_out or None,
                        tool_calls=budget.calls, cost_units=budget.cost, error_code=error_code))
                except Exception:  # noqa: BLE001 - never mask the original outcome
                    log.warning("could not record run status for %s", run_id)

    # ------------------------------------------------------------------ helpers
    def _reconcile(self, incoming: list[Any], history: list[StoredMessage], run_id: str):
        known = {m.message_id for m in history}
        pending = pending_frontend_calls(history)
        accepted: list[StoredMessage] = []
        ignored = 0
        for m in incoming or []:
            if m.id in known:
                continue
            if m.role == "user":
                text = _text_of(m.content).strip()[:MAX_USER_CHARS]
                if not text:
                    continue
                accepted.append(StoredMessage(message_id=m.id[:128], role="user", content_text=text,
                                              content_json={"id": m.id[:128], "role": "user", "content": text},
                                              run_id=run_id, author_id=self.p.user_id))
            elif m.role == "tool" and getattr(m, "tool_call_id", None) in pending:
                text = self.redactor.redact_text(_text_of(m.content)[:MAX_TOOL_RESULT_CHARS]).text
                accepted.append(StoredMessage(
                    message_id=m.id[:128], role="tool", content_text=text, run_id=run_id, author_id=self.p.user_id,
                    content_json={"id": m.id[:128], "role": "tool", "toolCallId": m.tool_call_id, "content": text,
                                  "toolName": pending[m.tool_call_id]}))
            else:
                ignored += 1
        return accepted, ignored

    async def _create_approval(self, call: _Call, args: dict[str, Any], run_id: str) -> dict[str, Any]:
        if self.approvals is None:
            raise ActionRejected("unavailable", "approvals are not configured on this server")
        approval = Approval(id=uuid.uuid4(), thread_id=self.thread_id, run_id=run_id, tool_call_id=call.id,
                            action_kind=call.name, action_args=args, requested_for=self.p.user_id,
                            expires_at=approval_expiry())
        await self.approvals.create(self.p, approval)
        return {**args, "approval_id": str(approval.id), "expires_at": approval.expires_at.isoformat()}

    async def _server_result(self, call: _Call, payload: dict[str, Any], parent_id: str, run_id: str,
                             history: list[StoredMessage], status: str = "ok", summary: dict | None = None,
                             citations_count: int = 0, latency_ms: int | None = None):
        content = json.dumps(payload, ensure_ascii=False, default=str)
        result_id = f"tool-{call.id}"[:128]
        yield ToolCallStartEvent(tool_call_id=call.id, tool_call_name=call.name, parent_message_id=parent_id)
        yield ToolCallArgsEvent(tool_call_id=call.id, delta=call.arguments or "{}")
        yield ToolCallEndEvent(tool_call_id=call.id)
        yield ToolCallResultEvent(message_id=result_id, tool_call_id=call.id, content=content, role="tool")
        stored = StoredMessage(message_id=result_id, role="tool", content_text=content[:2000], run_id=run_id,
                               author_id=f"tool:{call.name}",
                               content_json={"id": result_id, "role": "tool", "toolCallId": call.id,
                                             "content": content, "toolName": call.name})
        history.append(stored)
        await self.svc.chat.append_messages(self.p, self.thread_id, [stored])
        try:
            args = json.loads(call.arguments or "{}")
        except json.JSONDecodeError:
            args = {"_unparseable": True}
        await self.svc.chat.record_tool_run(
            self.p, self.thread_id, run_id, call.id, call.name, "server" if call.name not in UI_ACTIONS else "frontend",
            self.redactor.redact_value(args)[0] if isinstance(args, dict) else {}, status, summary,
            citations_count, 0, latency_ms, payload.get("error"))

    async def _run_route(self, call: _Call, parent_id: str, run_id: str, ctx: RouteContext,
                         citations: CitationRegistry, history: list[StoredMessage], tracker: StateTracker):
        try:
            outcome = await self.svc.search.execute(call.name, call.arguments or "{}", ctx, citations)
        except ToolError as exc:
            async for e in self._server_result(call, {"error": exc.code, "message": exc.message}, parent_id,
                                               run_id, history, status="denied" if exc.code == "denied" else "error"):
                yield e
            return
        except BudgetExceeded as exc:
            async for e in self._server_result(call, {"error": "budget_exceeded", "message": str(exc)}, parent_id,
                                               run_id, history, status="budget_exceeded"):
                yield e
            return
        payload = {"route": outcome.route, "items": outcome.model_items, "notes": outcome.result.notes,
                   "truncated": outcome.result.truncated, "total_hint": outcome.result.total_hint,
                   "chart_hint": outcome.result.chart_hint}
        async for e in self._server_result(call, payload, parent_id, run_id, history,
                                           summary={"items": len(outcome.model_items), "citations": outcome.citation_keys},
                                           citations_count=len(outcome.citation_keys), latency_ms=outcome.latency_ms):
            yield e
        evidence = [EvidenceRef(key=k, title=(citations.get(k).title if citations.get(k) else None),
                                source_type=citations.get(k).source_type if citations.get(k) else "unknown")
                    for k in outcome.citation_keys]
        known = {e.key for e in tracker.state.evidence}
        patch = tracker.update(
            evidence=[*tracker.state.evidence, *[e for e in evidence if e.key not in known]],
            tools_used=[*tracker.state.tools_used, call.name], phase="answering")
        if patch:
            yield StateDeltaEvent(delta=patch)
