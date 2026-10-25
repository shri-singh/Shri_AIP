"""Dynatrace Problems API v2 (classic Environment API).

``GET {DYNATRACE_ENV_URL}/api/v2/problems`` with ``Authorization: Api-Token <token>``
(token scope ``problems.read``).

Pagination: the first request carries ``from``/``to``/``pageSize``/selectors;
follow-up requests send **only** ``nextPageKey`` (the API rejects other
parameters alongside it).

Semantics: the API returns problems *relevant to* the timeframe, so a problem
that stays OPEN for hours appears in many windows. That is expected; the
dataset is a series of observations ("snapshot semantics"). Downstream upserts
by ``problemId`` keep the latest ``record_version``. Do not filter by
``startTime`` inside the window or you will lose long-running problems' updates.

Grail alternative: newer tenants can query problems via DQL
(``fetch dt.davis.problems``) with ``storage:events:read``; switch only after
validating field parity in your tenant.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import requests

from ..config import Settings
from ..errors import SourceContractError
from ..http import RetryPolicy, request_with_retry
from ..timeutil import to_epoch_ms
from ..windows import Window
from .base import FieldMap, SourceRecord


class DynatraceProblemsSource:
    name = "dynatrace_problems"
    dataset = "problems"
    window_semantics = "overlap_snapshot"

    field_map = FieldMap(
        time=("startTime",),
        severity=("severityLevel",),
        status=("status",),
        service=("rootCauseEntity.entityId.id", "affectedEntities.0.entityId.id", "impactedEntities.0.entityId.id"),
        title=("displayId",),
        message=("title",),
    )

    def __init__(self, settings: Settings, session: requests.Session | None = None, sleep=None) -> None:
        settings.require("dynatrace_env_url", "dynatrace_api_token")
        self.settings = settings
        self.url = settings.dynatrace_env_url + "/api/v2/problems"
        self.session = session or requests.Session()
        self.policy = RetryPolicy(max_retries=settings.http_max_retries, timeout=settings.http_timeout_seconds)
        self._sleep = sleep

    def fetch(self, window: Window) -> Iterator[SourceRecord]:
        headers = {"Authorization": "Api-Token " + self.settings.dynatrace_api_token, "Accept": "application/json"}
        params: dict[str, Any] = {
            "from": str(to_epoch_ms(window.start)),
            "to": str(to_epoch_ms(window.end)),
            "pageSize": self.settings.dynatrace_problems_page_size,
        }
        if self.settings.dynatrace_problems_selector:
            params["problemSelector"] = self.settings.dynatrace_problems_selector
        if self.settings.dynatrace_problems_fields:
            params["fields"] = self.settings.dynatrace_problems_fields
        seen_keys: set[str] = set()
        while True:
            kwargs: dict[str, Any] = {"policy": self.policy, "what": "dynatrace problems", "headers": headers,
                                      "params": params}
            if self._sleep is not None:
                kwargs["sleep"] = self._sleep
            response = request_with_retry(self.session, "GET", self.url, **kwargs)
            body = response.json()
            if not isinstance(body, dict) or not isinstance(body.get("problems", []), list):
                raise SourceContractError("dynatrace problems: unexpected response shape (no 'problems' list)")
            for problem in body.get("problems", []):
                problem_id = problem.get("problemId")
                yield SourceRecord(
                    origin_id=str(problem_id) if problem_id else None,
                    payload=problem,
                    source_ref=f"dynatrace-problem://{problem_id or problem.get('displayId', 'unknown')}",
                )
            next_key = body.get("nextPageKey")
            if not next_key:
                return
            if next_key in seen_keys:
                raise SourceContractError("dynatrace problems: nextPageKey repeated; aborting to avoid an infinite loop")
            seen_keys.add(next_key)
            params = {"nextPageKey": next_key}

    def close(self) -> None:
        self.session.close()
