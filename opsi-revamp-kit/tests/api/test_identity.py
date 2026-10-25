"""OIDC validation with a locally generated RSA key (no IdP needed)."""
import time

import jwt
import pytest
from app.modules._shared.errors import Unauthorized
from app.modules.identity import deps
from app.modules.identity.oidc import OidcValidator, map_roles, service_scope
from app.modules.install import build_memory_services, install_revamp
from app.modules.llm.gateway import ScriptedLLM
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from .helpers import make_settings

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class StaticJwks:
    def __init__(self, key):
        self.key = key

    def get_signing_key_from_jwt(self, token):
        return type("K", (), {"key": self.key.public_key()})()


SETTINGS = make_settings(auth_mode="oidc", oidc_issuer="https://idp.example/", oidc_audience="api://opsi",
                         oidc_jwks_url="https://idp.example/keys", oidc_tenant_claim="tid",
                         group_role_map={"grp-sre": ["investigator"], "grp-leads": ["approver"]},
                         role_service_scope={"investigator": ["checkout", "payments"], "approver": ["*"]})


def token(key=KEY, alg="RS256", **claims):
    now = int(time.time())
    body = {"iss": "https://idp.example/", "aud": "api://opsi", "sub": "user-1", "tid": "tenant-a",
            "groups": ["grp-sre"], "iat": now, "exp": now + 300, **claims}
    return jwt.encode(body, key, algorithm=alg)


def validator():
    return OidcValidator(SETTINGS, jwks_client=StaticJwks(KEY))


def test_valid_token_maps_roles_tenant_and_scope():
    v = validator()
    p = v.principal_from_claims(v.validate(token()))
    assert (p.user_id, p.tenant_id) == ("user-1", "tenant-a")
    assert p.roles == frozenset({"investigator"}) and p.service_scope == frozenset({"checkout", "payments"})
    lead = v.principal_from_claims(v.validate(token(groups=["grp-sre", "grp-leads"])))
    assert lead.service_scope is None  # '*' wins


@pytest.mark.parametrize("bad", [
    lambda: token(exp=int(time.time()) - 3600),
    lambda: token(aud="api://other"),
    lambda: token(iss="https://evil.example/"),
    lambda: token(key=OTHER_KEY),
    lambda: jwt.encode({"sub": "x", "iss": "https://idp.example/", "aud": "api://opsi"}, "secret", algorithm="HS256"),
    lambda: "not-a-jwt",
])
def test_invalid_tokens_are_rejected(bad):
    with pytest.raises(Unauthorized):
        validator().validate(bad())


def test_missing_tenant_or_unmapped_groups_rejected():
    v = validator()
    with pytest.raises(Unauthorized):
        v.principal_from_claims(v.validate(token(tid=None)))
    with pytest.raises(Unauthorized):
        v.principal_from_claims(v.validate(token(groups=["grp-unknown"])))


def test_insecure_algorithms_refused_at_construction():
    with pytest.raises(ValueError):
        OidcValidator(SETTINGS.model_copy(update={"oidc_algorithms": ("RS256", "HS256")}), jwks_client=StaticJwks(KEY))


def test_role_and_scope_helpers():
    assert map_roles(frozenset({"a", "b"}), {"a": ["viewer"], "b": ["investigator"]}) == {"viewer", "investigator"}
    assert service_scope(frozenset({"viewer"}), {"investigator": ["x"]}) == frozenset()
    assert service_scope(frozenset({"viewer"}), {}) is None


def test_bearer_flow_through_the_api():
    deps.set_oidc_validator(validator())
    app = FastAPI()
    install_revamp(app, build_memory_services(SETTINGS, ScriptedLLM([])))
    client = TestClient(app)
    assert client.get("/api/v2/chat/threads").status_code == 401
    assert client.get("/api/v2/chat/threads", headers={"Authorization": "Basic abc"}).status_code == 401
    assert client.get("/api/v2/chat/threads", headers={"Authorization": f"Bearer {token()}"}).status_code == 200


def test_dev_mode_refused_outside_dev_or_lab():
    with pytest.raises(RuntimeError):
        make_settings(env="prod", auth_mode="dev").assert_safe_for_env()
    with pytest.raises(RuntimeError):
        make_settings(env="prod", auth_mode="existing", attachments_scan_mode="none-lab").assert_safe_for_env()
