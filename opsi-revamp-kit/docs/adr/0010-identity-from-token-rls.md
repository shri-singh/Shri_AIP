# ADR-0010: Identity only from verified tokens; PostgreSQL RLS as defence in depth
- Status: Accepted
- Date: 2026-10-24

## Context
PHI/PII and client log data require per-tenant isolation. Agent requests arrive through a Node runtime and carry
client-controlled fields (`state`, `context`, `forwardedProps`) that could claim any tenant. A single forgotten
`WHERE tenant_id = ...` in application code must not leak data.

## Decision
- `Principal` (user, tenant, roles, service scope) is built only from: a validated OIDC access token
  (`OPSI_AUTH_MODE=oidc`; JWKS, iss, aud, exp, alg allowlist - never `none`/HS*), or the existing Opsi session via an
  adapter (`existing`), or a fixed dev principal that refuses to run outside dev/lab.
- Roles come from IdP groups via `OPSI_GROUP_ROLE_MAP_JSON`; service scope from `OPSI_ROLE_SERVICE_SCOPE_JSON`
  (deny by default when configured).
- Every DB unit of work runs in `tenant_tx`: `set_config('opsi.tenant_id'|'opsi.user_id', ..., true)` in the
  transaction. RLS (0005): RESTRICTIVE tenant policy on every tenant table + owner/visibility policies for chat;
  FORCE RLS; app connects as an `opsi_app` member (never owner/superuser/BYPASSRLS).
- Request models reject unknown fields (`extra="forbid"`), so `tenant_id` in a body is a 422, not ignored.

## Consequences
- Background jobs must also set the session context (the curated sink does).
- Superusers bypass RLS - DBA access to raw tables must be audited separately.

## Verification
`tests/api/test_identity.py` (RSA-signed tokens, bad aud/iss/exp/alg), `tests/api/test_chat_api.py::test_isolation_*`,
`database/validate/validate_migrations.mjs` (RLS checks), `tests/integration/test_pg_chat.py`.
