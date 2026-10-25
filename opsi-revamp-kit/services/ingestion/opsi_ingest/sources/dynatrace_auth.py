"""Dynatrace platform authentication for Grail.

Two supported modes:

- ``oauth`` (recommended): OAuth2 *client credentials* against the Dynatrace SSO
  token endpoint. Tokens are short-lived (``expires_in`` is typically 300 s), so a
  static bearer token in ``.env`` - as in the starter - stops working within
  minutes. This provider refreshes automatically 60 s before expiry.
- ``platform_token``: a long-lived Dynatrace *platform token* (if your tenant
  issues them and policy allows). Sent as ``Authorization: Bearer <token>``.

Classic API tokens (``Api-Token ...``) are for the classic Environment API
(Problems v2) only and do not work for Grail.

The OAuth client needs the Grail permissions/scopes (e.g. ``storage:logs:read``,
``storage:buckets:read``) granted in Account Management -> IAM; requesting a
scope the client was not granted fails with 400 ``invalid_scope``/``invalid_request``.
"""
from __future__ import annotations

import threading
import time

import requests

from ..config import Settings
from ..errors import ConfigError, PermanentSourceError
from ..http import RetryPolicy, request_with_retry


class DynatraceTokenProvider:
    def __init__(self, settings: Settings, session: requests.Session | None = None,
                 clock=time.monotonic) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self._clock = clock
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at = 0.0
        if settings.dynatrace_auth_mode == "platform_token":
            if not settings.dynatrace_platform_token:
                raise ConfigError("DYNATRACE_PLATFORM_TOKEN is required when DYNATRACE_AUTH_MODE=platform_token")
        else:
            settings.require("dynatrace_oauth_client_id", "dynatrace_oauth_client_secret", "dynatrace_oauth_token_url")

    def authorization_header(self) -> str:
        if self.settings.dynatrace_auth_mode == "platform_token":
            return "Bearer " + self.settings.dynatrace_platform_token
        with self._lock:
            if self._token is None or self._clock() >= self._expires_at - 60:
                self._refresh()
            return "Bearer " + str(self._token)

    def invalidate(self) -> None:
        with self._lock:
            self._token = None

    def _refresh(self) -> None:
        data = {
            "grant_type": "client_credentials",
            "client_id": self.settings.dynatrace_oauth_client_id,
            "client_secret": self.settings.dynatrace_oauth_client_secret,
            "scope": self.settings.dynatrace_oauth_scope,
        }
        if self.settings.dynatrace_oauth_resource:
            data["resource"] = self.settings.dynatrace_oauth_resource
        response = request_with_retry(
            self.session, "POST", self.settings.dynatrace_oauth_token_url,
            policy=RetryPolicy(max_retries=3, timeout=30), what="dynatrace oauth token",
            data=data, headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        body = response.json()
        token = body.get("access_token")
        if not token:
            raise PermanentSourceError("dynatrace oauth: response has no access_token")
        self._token = token
        self._expires_at = self._clock() + float(body.get("expires_in", 300))
