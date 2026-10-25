"""Citation keys ([c1], [c2] ...) that tie every claim in an answer to evidence.

- Keys are unique per *thread* (continuing numbering across runs) and deduplicated
  by (source_type, source_ref), so the same log line cited twice gets one key.
- ``check_answer`` finds the markers the model used. Markers that were never
  issued (hallucinated citations) are removed from the text and reported, so the
  UI never shows a citation that cannot be opened.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..chat.models import Evidence
from ..search.contracts import Citation

_MARKER = re.compile(r"\[(c\d{1,4})\]")


@dataclass
class AnswerCheck:
    text: str
    used: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)


class CitationRegistry:
    def __init__(self, existing: list[Evidence] | None = None) -> None:
        self._by_key: dict[str, Evidence] = {}
        self._by_ref: dict[tuple[str, str], str] = {}
        self._new: list[str] = []
        self._next = 1
        for ev in existing or []:
            self._by_key[ev.citation_key] = ev
            self._by_ref[(ev.source_type, ev.source_ref)] = ev.citation_key
            number = int(ev.citation_key[1:]) if ev.citation_key[1:].isdigit() else 0
            self._next = max(self._next, number + 1)

    def add(self, citation: Citation) -> str:
        ref = (citation.source_type, citation.source_ref)
        if ref in self._by_ref:
            return self._by_ref[ref]
        key = f"c{self._next}"
        self._next += 1
        self._by_key[key] = Evidence(citation_key=key, source_type=citation.source_type,
                                     source_ref=citation.source_ref, title=citation.title,
                                     event_time=citation.event_time, snippet=citation.snippet, url=citation.url)
        self._by_ref[ref] = key
        self._new.append(key)
        return key

    def get(self, key: str) -> Evidence | None:
        return self._by_key.get(key)

    def new_evidence(self, message_id: str | None = None) -> list[Evidence]:
        """Evidence issued during this run (to persist), stamped with the answering message id."""
        return [self._by_key[k].model_copy(update={"message_id": message_id}) for k in self._new]

    def check_answer(self, text: str) -> AnswerCheck:
        used: list[str] = []
        unknown: list[str] = []
        for key in _MARKER.findall(text):
            target = used if key in self._by_key else unknown
            if key not in target:
                target.append(key)
        clean = _MARKER.sub(lambda m: m.group(0) if m.group(1) in self._by_key else "", text) if unknown else text
        return AnswerCheck(text=clean, used=used, unknown=unknown)
