# Tests

| Folder | What | Needs | Command |
|---|---|---|---|
| `ingestion/` | 93 tests: time, windows, redaction, HTTP retry, Elastic/Problems/Grail adapters (synthetic shapes), pipeline scenarios (S3/PG failures, restart, duplicates, late data, caps), S3 request parameters | Python deps | `pytest tests/ingestion` |
| `api/` | 52 tests: AG-UI contract (schema of every event, ordering, tools, frontend actions, approvals, errors, cancellation, forged history, restore), identity (RSA JWTs), chat/attachments/isolation, search safety, UI actions, redaction sync | Python deps | `pytest tests/api` |
| `repo/` | 18 tests: workspace roles and push protection, pinned upstream refs, policy violations, vendoring provenance/licence/approval/modification/update/notices, repo hygiene, mirror script (all on throwaway local git repos) | git (+ bash for the mirror test) | `pytest tests/repo` |
| `integration/` | PostgreSQL state store, curated sink (run-order guard), chat repository under RLS, ontology + stores on seed data | `TEST_DATABASE_URL` (PGlite server or scratch DB) | `make test-integration` |
| `e2e/bridge_smoke.py` | real runtime <-> real FastAPI lab app; event validation; restore | built runtime + uvicorn | `make e2e` |
| `e2e/incident_journey.spec.ts` | Playwright journey for staging (template) | staging + Playwright | see file header |

Default `pytest` skips `integration`. Never point `TEST_DATABASE_URL` at shared or production databases.
Fake secrets in tests are assembled at runtime so secret scanners stay quiet.
