# Opsi 3.0 revamp kit

A self-contained **reference repository + overlay kit** for the Opsi/ObservAI 3.0 enterprise revamp,
built from `opsi-enterprise-starter/CLAUDE_CODE_MASTER_PROMPT.md`. It is meant to be carried to the
corporate EC2 host and used **without an AI assistant**: every decision is written down, every helper
is runnable, and the docs answer the questions you would otherwise ask.

**New here? Open [START_HERE.md](START_HERE.md).**

## What this is - and is not

| It is | It is not |
|---|---|
| Working, tested reference code you graft into the *new* `opsi-enterprise-revamp` clone | A replacement for the existing Opsi app (nothing here overwrites it) |
| Verified against real package versions (Oct 2026) - see [docs/verified-facts.md](docs/verified-facts.md) | Verified against *your* Opsi source, IdP, Dynatrace tenant or AWS account (Phase 0 does that) |
| Architecture, ADRs, threat model, runbooks, cheat sheets, FAQ, troubleshooting | A deployed or production-approved system |

## Layout

```
opsi-revamp-kit/
├── START_HERE.md                      task-oriented entry point
├── REPO_SETUP_MASTER_PROMPT.md        executable prompt/runbook: mirrors, workspace, product repo policy, vendoring
├── docs/                              architecture, ADRs, consultations, handbook, cheatsheets, runbooks ...
├── apps/
│   ├── opsi-api/app/modules/          FastAPI modules: identity, chat, agents (AG-UI), search, rag, llm, catalog, ontology, voice
│   ├── opsi-web/src/features/         React: chat-v2 (CopilotKit V2), metadata, incident-graph, reports
│   └── copilot-runtime/               CopilotKit V2 Node runtime bridge -> FastAPI AG-UI endpoint
├── services/
│   ├── ingestion/opsi_ingest/         collectors: Elastic (PIT), Dynatrace Problems v2, Grail (OAuth), S3 Parquet, outbox
│   └── otel-collector/                lab + production collector configs (content redaction)
├── database/
│   ├── migrations/ (+ rollback/)      Opsi-only schemas, RLS, ontology, chat, pgvector (optional)
│   ├── samples/                       synthetic seed data
│   └── validate/                      PGlite validator + throwaway PostgreSQL server (no Docker needed)
├── infrastructure/                    compose (lab override, prod template), nginx, systemd, cron, aws (IAM/S3/KMS), opensearch, openmetadata,
│                                      repo (workspace manifest, CODEOWNERS, CI, Dependabot, mirror job templates)
├── scripts/                           preflight, phase0 inventory, clone, migrate, compose_safe, health, drills, scans, smoke,
│                                      repo/ (workspace.py, vendor_component.py, repo_hygiene.py, mirror_upstream.sh)
├── tests/                             ingestion, api (AG-UI contracts), repo (repo tools), integration (PostgreSQL), e2e (bridge smoke)
├── tools/                             kb/ask.py (offline Q&A), redact_file.py
└── .env.example                       every variable, documented
```

## Verification evidence (what actually ran, 2026-10-24, on the authoring workstation)

| Check | Result |
|---|---|
| Python unit tests (ingestion + API: AG-UI contracts, auth, chat, attachments, search, approvals) | **145 passed** |
| PostgreSQL integration tests (state store, curated sink, chat repo with RLS, ontology, stores) on PGlite/PostgreSQL 18 | **5 passed** |
| SQL migrations: apply, idempotent re-apply, RLS isolation, append-only audit, pgvector, guarded rollbacks | **40/40 checks** |
| CopilotKit V2 runtime bridge tests against `@copilotkit/runtime` 1.79.1 | **7/7** |
| End-to-end: browser-shaped request -> real runtime -> real FastAPI AG-UI agent -> thread restored | **passed** |
| React features type-check (strict, `moduleResolution: bundler`) vs `@copilotkit/react-core` 1.79.1 + V1-usage scan | **passed (15 files)** |
| `docker compose config` + port-exposure check for 3 stacks (upstream OM dev file alone fails with 7 exposures, as expected) | **passed** |
| `otelcol-contrib validate` 0.137.0 (prod + lab) incl. negative test; `nginx -t` 1.28 for the SSE snippet | **passed** |
| Repository tools (workspace roles/push protection, vendoring provenance, hygiene, mirror script) on throwaway git repos | **18 passed** |
| Secret scan of the kit | **0 findings** |

Not executed here (needs your environment): real Dynatrace/Elastic/OpenMetadata/Portkey/Bedrock/AWS
calls, the OpenMetadata containers themselves, systemd units, IAM policies. Those have runbooks and
explicit "how to verify" steps instead.

## Quick start (EC2, Amazon Linux 2023)

```bash
sudo dnf install -y python3.12 git nodejs22 postgresql16   # names vary by AMI; see docs/cheatsheets/linux-ec2.md
cd ~/opsi-revamp-kit
scripts/preflight.sh
python3.12 -m venv .venv && .venv/bin/pip install -r requirements/dev.txt
make test                       # 145 unit tests, no network
make validate-sql               # needs node; no database server needed
make smoke                      # everything local, summarised
```

## Status and honesty rules

- Placeholders are marked `REPLACE_*`; nothing contains real credentials.
- Vendor APIs are implemented only where their contracts were verified; Broadcom OI is a deliberate failing stub.
- Every claim of "works" in these docs is backed by a test in `tests/` or a command you can rerun.
