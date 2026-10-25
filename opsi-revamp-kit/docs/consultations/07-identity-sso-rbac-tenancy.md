# 07 - Identity, SSO, RBAC, service scope and tenant isolation

## The question
"How do users authenticate through all the hops, how are permissions decided, and how sure are we about isolation?"

## Short answer
Reuse the identity Opsi already trusts (existing adapter) or validate OIDC access tokens in FastAPI. Map IdP groups to
a few Opsi roles, roles to permissions and service scopes. Enforce in three layers: route dependencies
(`require(permission)`), service-scope checks in routes/actions, and PostgreSQL RLS keyed on per-transaction settings.

## Choosing the auth mode
| Situation | Mode | Implementation |
|---|---|---|
| Opsi already validates users (session or token) | `existing` | write `async def adapter(request) -> Principal` that calls Opsi's current-user logic; `set_existing_auth_adapter(adapter)` at startup |
| Opsi is moving to corporate OIDC access tokens | `oidc` | set `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL`, claim names, group map |
| Local lab | `dev` | refused outside dev/lab |

### Example `existing` adapter
```python
from app.modules.identity.principal import Principal
from app.modules._shared.errors import Unauthorized
from app.auth import get_current_user_from_request   # Opsi's existing function (name will differ)

async def opsi_adapter(request):
    user = await get_current_user_from_request(request)       # raises/returns None if not logged in
    if user is None:
        raise Unauthorized()
    roles = {"admin"} if user.is_admin else {"investigator"}
    return Principal(user_id=str(user.id), tenant_id=user.tenant_slug or "default", roles=frozenset(roles),
                     display_name=user.name, service_scope=None, auth_source="existing")
```

## OIDC specifics by IdP
| IdP | Issuer | Audience | Stable user claim | Groups claim |
|---|---|---|---|---|
| Entra ID | `https://login.microsoftonline.com/<tenant>/v2.0` | `api://<app-id>` | `oid` | `groups` (or app `roles`); beware group overage (>200) -> use app roles |
| Okta | `https://<org>.okta.com/oauth2/<server>` | custom API audience | `sub` / `uid` | custom `groups` claim |
| Keycloak | `https://<host>/realms/<realm>` | client id / audience mapper | `sub` | `groups` mapper |
| Cognito | `https://cognito-idp.<region>.amazonaws.com/<pool>` | access tokens carry `client_id`, not `aud` -> validate `client_id` (adapt `oidc.py`) | `sub` | `cognito:groups` |
Always validate **access tokens** for the API audience, not ID tokens. Clock skew: leeway 60 s + chrony.

## Roles and permissions (default)
`viewer` (read/search), `investigator` (+ chat share, request actions, upload, feedback), `approver` (+ approve),
`ontology_editor` (graph writes), `admin`. Change in `identity/principal.py` (`ROLE_PERMISSIONS`) - keep it small.

## Service scope
`OPSI_ROLE_SERVICE_SCOPE_JSON={"investigator":["checkout","payments"],"approver":["*"]}` - union over roles, `*` = all,
configured-but-missing role = no services. Enforced in: route args (`scoped_services`), result filtering (graph), UI
actions (`service_id`), thread creation (`linked_service_id`). Not enforced by RLS (services aren't a DB tenant) - keep
checks in code and tests.

## Tenancy models
- **Single tenant per deployment** (common): `OIDC_TENANT_CLAIM` empty -> `OPSI_DEFAULT_TENANT_ID`; RLS still protects
  user-private chat data.
- **Multi-tenant**: tenant from a token claim (or adapter lookup); each tenant's Elastic indices in
  `SEARCH_ELASTIC_TENANT_INDEX_MAP_JSON`; collectors run per tenant (`OPSI_TENANT_ID`) with separate state/prefixes.

## RLS mechanics recap
`tenant_tx` -> `set_config('opsi.tenant_id', ..., true)`, `set_config('opsi.user_id', ..., true)`; policies read them via
`opsi_meta.current_tenant()/current_user_id()`; RESTRICTIVE tenant policy + permissive owner/visibility policies; FORCE
RLS. Superusers/BYPASSRLS/owners (without FORCE) bypass - the app must not use them.

## Testing isolation
`tests/api/test_chat_api.py::test_isolation_between_users_and_tenants`, RLS checks in the migration validator,
`tests/integration/test_pg_chat.py`. Add a staging check: two real users, attempt to open each other's thread URL -> 404.
