"""OIDC access-token validation (JWT) against the corporate IdP's JWKS.

Checks: signature (JWKS, allow-listed algorithms only - never ``none``/HS*),
``iss``, ``aud``, ``exp``/``nbf``/``iat`` with small leeway, required subject.
Then maps claims -> Principal using configuration, not code:

- user id      : ``OIDC_USER_CLAIM`` (default ``sub``; ``oid`` for Entra ID is more stable)
- tenant       : ``OIDC_TENANT_CLAIM`` or the single configured ``OPSI_DEFAULT_TENANT_ID``
- roles        : IdP groups/roles (``OIDC_ROLES_CLAIM``) mapped through ``OPSI_GROUP_ROLE_MAP_JSON``
- service scope: union of ``OPSI_ROLE_SERVICE_SCOPE_JSON`` for the mapped roles ("*" = all)

Works with Entra ID, Okta, Ping, Keycloak and AWS Cognito access tokens. Use the
*access* token issued for the Opsi API audience - not the ID token.
"""
from __future__ import annotations

from typing import Any

import jwt

from .._shared.errors import Unauthorized
from .._shared.settings import ApiSettings
from .principal import Principal

_FORBIDDEN_ALGS = {"none", "HS256", "HS384", "HS512"}


class OidcValidator:
    def __init__(self, settings: ApiSettings, jwks_client: Any | None = None) -> None:
        bad = _FORBIDDEN_ALGS.intersection(settings.oidc_algorithms)
        if bad:
            raise ValueError(f"refusing insecure JWT algorithms: {sorted(bad)}")
        self.settings = settings
        self.jwks = jwks_client or jwt.PyJWKClient(settings.oidc_jwks_url, cache_keys=True, lifespan=3600,
                                                   timeout=10)

    def validate(self, token: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in self.settings.oidc_algorithms:
                raise Unauthorized("token algorithm not allowed")
            key = self.jwks.get_signing_key_from_jwt(token).key
            return jwt.decode(
                token, key, algorithms=list(self.settings.oidc_algorithms), audience=self.settings.oidc_audience,
                issuer=self.settings.oidc_issuer, leeway=self.settings.oidc_leeway_seconds,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except Unauthorized:
            raise
        except jwt.ExpiredSignatureError:
            raise Unauthorized("token expired") from None
        except jwt.PyJWTError:
            raise Unauthorized("invalid token") from None

    def principal_from_claims(self, claims: dict[str, Any]) -> Principal:
        s = self.settings
        user = claims.get(s.oidc_user_claim)
        if not isinstance(user, str) or not user:
            raise Unauthorized(f"token lacks the '{s.oidc_user_claim}' claim")
        if s.oidc_tenant_claim:
            tenant = claims.get(s.oidc_tenant_claim)
            if not isinstance(tenant, str) or not tenant:
                raise Unauthorized("token lacks the tenant claim")
        else:
            tenant = s.default_tenant_id
        raw_groups = claims.get(s.oidc_roles_claim) or []
        groups = frozenset(g for g in (raw_groups if isinstance(raw_groups, list) else [raw_groups]) if isinstance(g, str))
        roles = map_roles(groups, s.group_role_map)
        if not roles:
            raise Unauthorized("no Opsi role mapped for this user's groups")
        return Principal(
            user_id=user, tenant_id=tenant, roles=roles, groups=groups,
            display_name=claims.get("name") or claims.get("preferred_username"),
            service_scope=service_scope(roles, s.role_service_scope), auth_source="oidc",
        )


def map_roles(groups: frozenset[str], group_role_map: dict[str, list[str]]) -> frozenset[str]:
    roles: set[str] = set()
    for group in groups:
        roles.update(group_role_map.get(group, []))
    return frozenset(roles)


def service_scope(roles: frozenset[str], role_scope: dict[str, list[str]]) -> frozenset[str] | None:
    """None means unrestricted. Roles without an entry contribute nothing (deny by default)."""
    if not role_scope:
        return None
    scope: set[str] = set()
    for role in roles:
        services = role_scope.get(role, [])
        if "*" in services:
            return None
        scope.update(services)
    return frozenset(scope)
