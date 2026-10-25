"""HTTP with bounded retries for vendor APIs.

- Retries 429 and 500/502/503/504 plus connection errors/timeouts.
- Honours ``Retry-After`` (seconds or HTTP-date), capped by ``max_sleep``.
- Fails fast on other 4xx (bad token, missing scope, bad query) with a
  ``PermanentSourceError`` whose message never contains headers or bodies
  that could carry secrets.
"""
from __future__ import annotations

import email.utils
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests

from .errors import PermanentSourceError, TransientSourceError
from .redaction import scrub_for_log

log = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class RetryPolicy:
    max_retries: int = 5
    base_delay: float = 1.0
    max_sleep: float = 60.0
    timeout: float = 60.0


def _retry_after_seconds(response: requests.Response) -> float | None:
    header = response.headers.get("Retry-After")
    if not header:
        return None
    try:
        return max(0.0, float(header))
    except ValueError:
        parsed = email.utils.parsedate_to_datetime(header)
        if parsed is None:
            return None
        return max(0.0, parsed.timestamp() - time.time())


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    policy: RetryPolicy,
    sleep: Callable[[float], None] = time.sleep,
    what: str = "vendor API",
    **kwargs: Any,
) -> requests.Response:
    kwargs.setdefault("timeout", policy.timeout)
    attempt = 0
    while True:
        try:
            response = session.request(method, url, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as exc:
            if attempt >= policy.max_retries:
                raise TransientSourceError(f"{what}: network error after {attempt + 1} attempts: {type(exc).__name__}") from None
            delay = _backoff(policy, attempt)
            log.warning("%s network error (%s); retry %d in %.1fs", what, type(exc).__name__, attempt + 1, delay)
            sleep(delay)
            attempt += 1
            continue

        if response.status_code < 400:
            return response

        if response.status_code in RETRYABLE_STATUS:
            if attempt >= policy.max_retries:
                raise TransientSourceError(
                    f"{what}: HTTP {response.status_code} after {attempt + 1} attempts"
                )
            delay = _retry_after_seconds(response)
            delay = _backoff(policy, attempt) if delay is None else min(delay, policy.max_sleep)
            log.warning("%s HTTP %d; retry %d in %.1fs", what, response.status_code, attempt + 1, delay)
            sleep(delay)
            attempt += 1
            continue

        raise PermanentSourceError(_describe_failure(what, response))


def _backoff(policy: RetryPolicy, attempt: int) -> float:
    exp = policy.base_delay * (2 ** attempt)
    return min(policy.max_sleep, exp) * (0.5 + random.random() / 2)  # "equal jitter"


def _describe_failure(what: str, response: requests.Response) -> str:
    hint = {
        400: "query/parameters rejected - check DQL/selector/time format",
        401: "authentication failed - token expired or wrong token type",
        403: "authorized identity lacks a scope/permission for this API or bucket",
        404: "endpoint not found - check base URL (classic vs platform URL)",
        413: "request too large",
    }.get(response.status_code, "client error")
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            err = body.get("error")
            detail = (err.get("message") if isinstance(err, dict) else err) or body.get("message") or ""
    except ValueError:
        detail = ""
    detail = scrub_for_log(str(detail))[:300]
    return f"{what}: HTTP {response.status_code} ({hint}){': ' + detail if detail else ''}"
