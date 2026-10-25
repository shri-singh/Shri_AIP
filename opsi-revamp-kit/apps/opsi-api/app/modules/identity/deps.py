"""FastAPI dependencies: ``current_principal`` and ``require(permission)``.

Auth modes (``OPSI_AUTH_MODE``):
- ``oidc``     : validate the ``Authorization: Bearer`` access token here.
- ``existing`` : reuse the existing Opsi authentication. Register an adapter at
                 startup with ``set_existing_auth_adapter(fn)``, where ``fn(request)``
                 returns a Principal (or raises). This is the least invasive option when
                 Opsi already has SSO/session handling. See apps/opsi-api/README.md.
- ``dev``      : fixed principal for local labs. Refused unless OPSI_ENV is dev/lab.

The CopilotKit Node runtime forwards ``authorization`` (and ``x-*``) headers to the
agent endpoint by default, so the same dependency protects the AG-UI route.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, Request

from .._shared.errors import Forbidden, Unauthorized
from .._shared.settings import ApiSettings, get_settings
from .oidc import OidcValidator
from .principal import Principal

ExistingAuthAdapter = Callable[[Request], Awaitable[Principal]]
_existing_adapter: ExistingAuthAdapter | None = None
_validator: OidcValidator | None = None


def set_existing_auth_adapter(adapter: ExistingAuthAdapter) -> None:
    global _existing_adapter
    _existing_adapter = adapter


def set_oidc_validator(validator: OidcValidator | None) -> None:
    """Tests and custom wiring can inject a validator (e.g. with a local JWKS)."""
    global _validator
    _validator = validator


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthorized()
    return token.strip()


def _settings_for(request: Request) -> ApiSettings:
    # The installed container's settings win, so tests/lab apps and the real app agree on auth mode.
    container = getattr(request.app.state, "opsi", None)
    return getattr(container, "settings", None) or get_settings()


async def current_principal(request: Request) -> Principal:
    cached = getattr(request.state, "principal", None)
    if isinstance(cached, Principal):
        return cached
    settings = _settings_for(request)
    if settings.auth_mode == "dev":
        settings.assert_safe_for_env()
        principal = Principal(user_id=settings.dev_user, tenant_id=settings.default_tenant_id,
                              roles=frozenset(settings.dev_roles), auth_source="dev")
    elif settings.auth_mode == "existing":
        if _existing_adapter is None:
            raise Unauthorized("existing-auth adapter not configured")
        principal = await _existing_adapter(request)
    else:
        global _validator
        if _validator is None:
            _validator = OidcValidator(settings)
        principal = _validator.principal_from_claims(_validator.validate(_bearer(request)))
    request.state.principal = principal
    return principal


def require(permission: str) -> Callable[..., Awaitable[Principal]]:
    async def _dep(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.can(permission):
            raise Forbidden(f"missing permission {permission}")
        return principal

    return _dep
