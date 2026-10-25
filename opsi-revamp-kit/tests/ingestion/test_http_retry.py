import pytest
import requests
from opsi_ingest.errors import PermanentSourceError, TransientSourceError
from opsi_ingest.http import RetryPolicy, request_with_retry

from .fakes import ScriptedSession, make_response

POLICY = RetryPolicy(max_retries=3, base_delay=0.01, max_sleep=5)


def test_429_honours_retry_after_then_succeeds():
    sleeps = []
    session = ScriptedSession([make_response(429, headers={"Retry-After": "2"}), make_response(200, {"ok": True})])
    response = request_with_retry(session, "GET", "https://x/api", policy=POLICY, sleep=sleeps.append)
    assert response.json() == {"ok": True}
    assert sleeps == [2.0]


def test_retry_after_is_capped():
    sleeps = []
    session = ScriptedSession([make_response(503, headers={"Retry-After": "9999"}), make_response(200)])
    request_with_retry(session, "GET", "https://x/api", policy=POLICY, sleep=sleeps.append)
    assert sleeps == [5]


def test_5xx_exhaustion_raises_transient():
    session = ScriptedSession([make_response(502)] * 4)
    with pytest.raises(TransientSourceError, match="HTTP 502 after 4 attempts"):
        request_with_retry(session, "GET", "https://x/api", policy=POLICY, sleep=lambda s: None)


def test_connection_errors_are_retried():
    session = ScriptedSession([requests.ConnectionError("boom"), make_response(200)])
    assert request_with_retry(session, "GET", "https://x", policy=POLICY, sleep=lambda s: None).status_code == 200


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_client_errors_fail_fast_without_retry(status):
    session = ScriptedSession([make_response(status, {"error": {"message": "token dt0c01.SECRETSECRETSECRET bad"}})])
    with pytest.raises(PermanentSourceError) as info:
        request_with_retry(session, "GET", "https://x", policy=POLICY, sleep=lambda s: None)
    assert len(session.calls) == 1
    assert "dt0c01.SECRET" not in str(info.value)  # vendor error text is scrubbed
