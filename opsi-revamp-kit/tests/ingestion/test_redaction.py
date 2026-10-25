import json

import pytest
from opsi_ingest.redaction import Redactor, scrub_for_log

# Fake secrets are assembled at runtime so secret scanners (gitleaks, push protection) do not flag the repo.
AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
GH_TOKEN = "ghp" + "_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef123456"
PEM_HEAD, PEM_TAIL = "-----BEGIN RSA " + "PRIVATE KEY-----", "-----END RSA " + "PRIVATE KEY-----"
DB_URL = "postgres://app:" + "SuperSecret1" + "@db.internal:5432/app"

SECRETS = {
    "aws key id": f"found {AWS_KEY} in config",
    "jwt": "token eyJhbGciOiJIUzI1NiJ9" + ".eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    "bearer": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345",
    "dynatrace": "using dt0c01.ABCDEFGHIJKLMNOPQRSTUVWX.ABCDEFGHIJKLMNOPQRSTUVWXABCDEFGHIJKLMNOPQRSTUVWX",
    "url creds": f"connect {DB_URL}",
    "password kv": "login failed password=hunter2 user=bob",
    "github": GH_TOKEN,
    "private key": f"{PEM_HEAD}\nMIIBOgIBAAJBAK\n{PEM_TAIL}",
}


@pytest.mark.parametrize("label,text", SECRETS.items(), ids=list(SECRETS))
def test_secrets_are_removed_in_both_levels(label, text):
    for level in ("standard", "strict"):
        result = Redactor(level).redact_text(text)
        assert result.hits >= 1, label
        for needle in (AWS_KEY, "SuperSecret1", "hunter2", "abcdefghijklmnopqrstuvwxyz012345",
                       "ghp_ABCDEF", "MIIBOgIBAAJBAK", "eyJhbGciOiJIUzI1NiJ9", "dt0c01.ABCDEF"):
            assert needle not in result.text, f"{label}/{level} leaked {needle}"


def test_strict_removes_pii_but_standard_keeps_it():
    text = "user jane.doe@example.com paid with 4111 1111 1111 1111, ssn 123-45-6789"
    strict = Redactor("strict").redact_text(text).text
    assert "jane.doe@example.com" not in strict and "4111" not in strict and "123-45-6789" not in strict
    assert "jane.doe@example.com" in Redactor("standard").redact_text(text).text


def test_card_pattern_requires_luhn():
    # 16 digits that fail Luhn (e.g. an order number) are left alone
    assert "1234 5678 9012 3456" in Redactor("strict").redact_text("order 1234 5678 9012 3456").text


def test_nested_payload_and_secret_keys():
    payload = {"headers": {"Authorization": "Basic Zm9vOmJhcg==", "X-Trace": "ok"},
               "items": [{"password": "p@ss"}, AWS_KEY], "count": 3}
    text, hits = Redactor("strict").redact_json(payload)
    data = json.loads(text)
    assert data["headers"]["Authorization"] == "[REDACTED]"
    assert data["items"][0]["password"] == "[REDACTED]"
    assert "AKIA" not in data["items"][1]
    assert data["count"] == 3 and hits >= 3


def test_scrub_for_log_masks_exception_text():
    url = "https://svc:" + "SuperSecret1" + "@host/x"
    assert "SuperSecret1" not in scrub_for_log(f"ConnectionError: {url} refused")
