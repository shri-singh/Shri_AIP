# ADR-0017: Exact version pins and export-verification scripts for fast-moving vendors
- Status: Accepted
- Date: 2026-10-24

## Context
CopilotKit ships frequently (1.79.1 at writing; V2 API under active development), AG-UI reached 1.0 with
breaking renames (THINKING_* -> REASONING_*), OpenMetadata 2.0 changed APIs and DB schemas, elasticsearch-py majors
are not cross-compatible. Online examples often show V1 or outdated APIs.

## Decision
- Exact pins in `requirements/*.txt`, `apps/*/package.json` (no `^`). Lockfiles committed in the real repos.
- `@ag-ui/client` pinned to the version `@copilotkit/runtime` itself depends on.
- Verification scripts: `apps/copilot-runtime/scripts/verify-runtime-exports.mjs`,
  `apps/opsi-web/scripts/verify-copilotkit-v2.mjs` (exports + V1-usage scan), `docs/verified-facts.md` procedures.
- Upgrades follow the checklist in [../runbooks.md](../runbooks.md#dependency-upgrades): read changelog, bump in a branch,
  run verify scripts + all tests + E2E smoke, update `verified-facts.md`.

## Verification
CI/`make smoke` fails on missing exports or V1 usage; `npm ls @ag-ui/client` shows a single version.
