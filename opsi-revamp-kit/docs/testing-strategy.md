# Testing strategy and definition of done

## 1. Test layers in the kit

| Layer | Location | Runs where | Command |
|---|---|---|---|
| Unit - ingestion (windows, time, redaction, retry, sources with recorded shapes, pipeline scenarios, S3 params) | `tests/ingestion/` | anywhere, no network | `pytest tests/ingestion` |
| Unit/contract - API (AG-UI event schema + lifecycle, auth, chat, attachments, search, actions, approvals) | `tests/api/` | anywhere | `pytest tests/api` |
| Integration - PostgreSQL (state store, curated sink, chat repo with RLS, ontology, stores) | `tests/integration/` | needs a throwaway PostgreSQL (PGlite server or a scratch RDS) | `make test-integration` |
| SQL migrations + RLS behaviour | `database/validate/validate_migrations.mjs` | node only | `make validate-sql` |
| Runtime bridge contract | `apps/copilot-runtime/test/` | node | `make runtime` |
| Frontend type-check + V2-only scan | `apps/opsi-web/` | node | `make web` |
| E2E bridge (runtime <-> FastAPI, restore) | `tests/e2e/bridge_smoke.py` | node + python | `make e2e` |
| Config validation | compose/otel/nginx | docker / otelcol / nginx | see [runbooks.md](runbooks.md) |

All of the above passed when the kit was built (see README "Verification evidence").

## 2. Master prompt definition of done -> evidence

| Requirement | Evidence in kit | Still needed in your environment |
|---|---|---|
| No changes to original remote/prod DB/NGINX/network | `clone_repos.sh` disables legacy push; NGINX snippet only for revamp server block | change-control evidence |
| `docker compose config` validates; services isolated; health shows readiness | `compose_safe.sh` + port check (3 stacks passed); healthchecks in compose; `scripts/health.sh` | run on EC2; measure CPU/RAM |
| `npm run build`, TS tests, V2 import checks | `make web` (tsc strict, V2 scan), runtime `npm test` | real Opsi build with the features grafted |
| FastAPI tests: authorization, thread persistence, after-login retrieval, tags/folders, attachments, signed-URL expiry, action allowlist, AG-UI contracts | `tests/api/*` (52 tests) | re-run inside the Opsi app after grafting |
| Ingestion: pagination, 429/5xx, overlapping windows, late events, duplicate ids, S3/PG partial failure, restart without loss, result caps, token scrubbing | `tests/ingestion/*` (93 tests) + integration | real captures as fixtures |
| E2E: open incident -> ask why -> Elastic logs + metadata ownership -> citations -> chart filter via UI action -> save -> logout/login -> thread/files/tags/citations reappear | partial: `bridge_smoke.py` + `test_agui_contract.py` cover run, citations, UI action, restore | full browser E2E (Playwright script below) against staging |
| Backups, restore drills, tenant isolation, least privilege documented | runbooks, `backup_restore_drill.sh`, RLS tests, IAM templates | executed drills + evidence log |

## 3. Browser E2E (Playwright) - run in staging
`tests/e2e/incident_journey.spec.ts` (template) automates the master-prompt journey. Prerequisites: staging URL,
a test user with role `investigator` and scope including the demo service, seeded incident, Playwright installed
(`npm i -D @playwright/test@<pinned> && npx playwright install chromium`).

## 4. What "done" means per change
1. Unit tests for new logic, including at least one negative/security case.
2. Contract change -> update docs/data-contracts.md + both sides' tests.
3. `make smoke` green; secret scan clean.
4. Evidence (command + output summary) in the PR description.
5. Rollback path stated in the PR.

## 5. Writing tests without vendor access
- Capture once in a sandbox with `curl`, redact (`tools/redact_file.py`), review by hand, store under `services/ingestion/fixtures/`.
- Write the adapter against the fixture; keep a "contract test" asserting the fields you depend on.
- For APIs you cannot capture yet, write a **failing** stub (like `broadcom_oi.py`) - never invent a response shape.
