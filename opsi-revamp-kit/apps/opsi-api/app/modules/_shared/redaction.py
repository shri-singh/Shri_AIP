# Copy of services/ingestion/opsi_ingest/redaction.py for the API process.
# Kept byte-identical below the marker line; tests/api/test_redaction_sync.py fails if they drift.
# Edit the ingestion copy first, then run: python scripts/sync_redaction.py
# --- BEGIN SHARED REDACTION (do not edit here) ---
"""Credential and PII scrubbing for log text, payloads, error messages and traces.

``strict`` (default) removes secrets *and* common PII; ``standard`` removes
secrets only. Patterns are deliberately conservative regexes: they are a
safety net, not a DLP product. Extend ``EXTRA_PATTERNS`` for your estate
(see docs/handbook/FAQ.md "How do I add a redaction rule?").
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

REDACTED = "[REDACTED]"

# (name, pattern, replacement). Order matters: specific before generic.
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[REDACTED:private_key]"),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA|AIDA|AROA)[0-9A-Z]{16}\b"), "[REDACTED:aws_key_id]"),
    ("aws_secret", re.compile(r"(?i)(aws_secret_access_key|aws_session_token)(\s*[=:]\s*)([^\s\"',;]+)"), r"\1\2[REDACTED]"),
    ("dynatrace_token", re.compile(r"\bdt0[a-z]\d{2}\.[A-Za-z0-9]{12,}(?:\.[A-Za-z0-9]{12,})?\b"), "[REDACTED:dynatrace_token]"),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"), "[REDACTED:github_token]"),
    ("slack_token", re.compile(r"\bxox[abpors]-[A-Za-z0-9-]{10,}\b"), "[REDACTED:slack_token]"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[REDACTED:jwt]"),
    ("bearer", re.compile(r"(?i)\b(bearer|api-token|apikey|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [REDACTED]"),
    ("url_credentials", re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^/\s@]+)@"), r"\1[REDACTED]:[REDACTED]@"),
    ("kv_secret", re.compile(r"(?i)\b(password|passwd|pwd|secret|client_secret|api[_-]?key|access[_-]?token|refresh[_-]?token|token)(\"?\s*[=:]\s*\"?)([^\s\"',;&}]+)"), r"\1\2[REDACTED]"),
    ("portkey_key", re.compile(r"\bpk-[A-Za-z0-9]{20,}\b"), "[REDACTED:api_key]"),
]

_PII_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED:email]"),
    ("us_ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED:ssn]"),
    ("card", re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[CARD?]"),  # confirmed by Luhn below
    ("phone", re.compile(r"(?<![\w.])\+?1?[ .-]?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b"), "[REDACTED:phone]"),
]

EXTRA_PATTERNS: list[tuple[str, re.Pattern[str], str]] = []


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


@dataclass
class RedactionResult:
    text: str
    hits: int


class Redactor:
    def __init__(self, level: str = "strict") -> None:
        if level not in ("strict", "standard"):
            raise ValueError("level must be strict or standard")
        self.level = level
        self._patterns = list(_SECRET_PATTERNS) + list(EXTRA_PATTERNS)
        if level == "strict":
            self._patterns += _PII_PATTERNS

    def redact_text(self, text: str) -> RedactionResult:
        if not text:
            return RedactionResult(text, 0)
        hits = 0
        for name, pattern, replacement in self._patterns:
            if name == "card":
                def _card(match: re.Match[str]) -> str:
                    nonlocal hits
                    digits = re.sub(r"\D", "", match.group(0))
                    if 13 <= len(digits) <= 19 and _luhn_ok(digits):
                        hits += 1
                        return "[REDACTED:card]"
                    return match.group(0)

                text = pattern.sub(_card, text)
                continue
            text, count = pattern.subn(replacement, text)
            hits += count
        return RedactionResult(text, hits)

    def redact_value(self, value: Any) -> tuple[Any, int]:
        """Recursively redact strings inside JSON-like structures. Keys named like secrets are blanked."""
        if isinstance(value, str):
            result = self.redact_text(value)
            return result.text, result.hits
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            hits = 0
            for key, item in value.items():
                if isinstance(key, str) and _SECRET_KEY.search(key):
                    out[key] = REDACTED if item not in (None, "") else item
                    hits += 1 if item not in (None, "") else 0
                    continue
                out[key], h = self.redact_value(item)
                hits += h
            return out, hits
        if isinstance(value, list):
            items, hits = [], 0
            for item in value:
                red, h = self.redact_value(item)
                items.append(red)
                hits += h
            return items, hits
        return value, 0

    def redact_json(self, value: Any) -> tuple[str, int]:
        redacted, hits = self.redact_value(value)
        return json.dumps(redacted, ensure_ascii=False, default=str, sort_keys=True), hits


_SECRET_KEY = re.compile(
    r"(?i)^(authorization|cookie|set-cookie|x-api-key|password|passwd|secret|client_secret|api[_-]?key|"
    r"access[_-]?token|refresh[_-]?token|private[_-]?key|session[_-]?token)$"
)


def scrub_for_log(message: str) -> str:
    """Use for exception text and log lines (always strict)."""
    return _LOG_REDACTOR.redact_text(message).text


_LOG_REDACTOR = Redactor("strict")
