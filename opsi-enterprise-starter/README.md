# Opsi 3.0 — enterprise architecture + portable starter kit

**Scope:** Non-destructive scaffolding for a React + FastAPI + PostgreSQL Opsi application, with OpenMetadata, OpenSearch, CopilotKit V2, Portkey/Bedrock, OTEL, S3 archival and EC2 collectors.

**Status:** Source starter, **not** a deployed or production-approved solution. All endpoints, data mappings, IAM boundaries and license provenance require review in the target environment. Keep corporate data out of external personal devices and source repositories unless authorized.

## Start in this order
1. Read `docs/ARCHITECTURE.md`, `docs/DECISIONS_AND_SAFETY.md`, `docs/INSTALL_RUNBOOK.md`.
2. Hand `CLAUDE_CODE_MASTER_PROMPT.md` to Claude Code together with this kit and the Opsi source.
3. Review prerequisites: `bash scripts/00_check_prereqs.sh`.
4. Using approved corporate Git credentials, create **two clones** (no branch): `scripts/01_clone_opsi.sh`; don't point them to the same writable production directories.
5. Fetch read-only upstream source into `vendor/` with `scripts/02_fetch_upstreams.sh`.
6. Start OpenMetadata **only in isolated dev** via `scripts/03_openmetadata_dev.sh` after reviewing upstream compose.
7. Create an S3 bucket with `scripts/04_create_s3.sh` under an approved IAM role, then configure `.env` locally (`chmod 600`).
8. Install Python collector deps: `python3 -m venv .venv && . .venv/bin/activate && pip install -r ingestion/requirements.txt`.
9. Create curated PostgreSQL schema with `psql "$DATABASE_URL" -f sql/001_opsi_extensions.sql` (DBA review first).
10. Dry-run a 5-minute source window with `python -m ingestion.run_once --source elastic` or `dynatrace_problems` / `dynatrace_grail`.
11. Review output and permission boundaries. Install cron **only after** one-shot tests succeed.

## Reference source repositories
- OpenMetadata: https://github.com/open-metadata/OpenMetadata
- CopilotKit: https://github.com/CopilotKit/CopilotKit
- CopilotKit V2 docs: https://docs.copilotkit.ai/reference/v2
- Dynatrace Grail API: https://developer.dynatrace.com/develop/platform-services/services/grail-service/

## What's deliberately NOT included
- A replacement for Opsi's existing app; no destructive merge or auto-commit/push.
- A production-secure OpenMetadata install; upstream development Compose disables OpenSearch security.
- A completed CopilotKit V2 runtime or Bedrock client (the implementation contract is in the prompt).
- A complete extraction of all Elastic/Grail logs at unlimited scale. Export jobs use bounded windows and fail rather than silently truncate.
- Production data replication into OpenMetadata tables (use APIs/ingestion). For analytics and backups, see the separate retention and RDS/S3 plans.

## Generated deliverables
- `CLAUDE_CODE_MASTER_PROMPT.md`: implementation prompt and acceptance criteria.
- `docs/`: architecture, runbook, design decisions, voice.
- `scripts/`: Git, Docker, S3, cron, DB export, probes.
- `ingestion/`: executable Python collector starter, Parquet/S3/curated PG sink.
- `sql/`: application-side curated schema and graph tables.
- `backend/`: search/tool/state/voice interface stubs for Claude Code.
- `frontend/`: CopilotKit V2 integration example (not an isolated app).
- `compose/`: local-only OpenTelemetry collector example.

Run scripts from project root, or change `cd` to this folder first. Never commit `.env`, GitHub tokens, OAuth bearer tokens, client secrets or actual log payloads.
