"""Shared agent state (AG-UI STATE_SNAPSHOT / STATE_DELTA).

The server is the only author of this state. Client-sent ``state`` in
RunAgentInput is ignored except as a hint already covered by ui context.
Deltas are RFC 6902 JSON Patch computed with ``jsonpatch.make_patch``.
"""
from __future__ import annotations

from typing import Any, Literal

import jsonpatch
from pydantic import BaseModel, Field

Phase = Literal["idle", "retrieving", "answering", "awaiting_user", "done", "error"]


class EvidenceRef(BaseModel):
    key: str
    title: str | None = None
    source_type: str


class InvestigationState(BaseModel):
    phase: Phase = "idle"
    incident_id: str | None = None
    service_id: str | None = None
    time_from: str | None = None
    time_to: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    budget: dict[str, float] = Field(default_factory=dict)
    pending_approvals: list[str] = Field(default_factory=list)


class StateTracker:
    MAX_EVIDENCE = 200

    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self.state = InvestigationState.model_validate(initial or {})
        self._last = self.dump()

    def dump(self) -> dict[str, Any]:
        return self.state.model_dump(mode="json")

    def update(self, **changes: Any) -> list[dict[str, Any]]:
        """Apply changes and return the JSON Patch since the last emitted snapshot/delta (may be empty)."""
        data = {**self.dump(), **changes}
        data["evidence"] = data["evidence"][-self.MAX_EVIDENCE:]
        self.state = InvestigationState.model_validate(data)
        current = self.dump()
        patch = jsonpatch.make_patch(self._last, current).patch
        self._last = current
        return patch

    def mark_emitted(self) -> None:
        self._last = self.dump()
