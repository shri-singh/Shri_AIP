# Incremental commit plan, code ownership and rollback

Target: the new `opsi-enterprise-revamp` clone (never the legacy remote). Each step is one PR, reviewable in
under an hour, independently revertible, behind a flag where user-visible. **Nothing is pushed without approval.**

## Code ownership (suggested CODEOWNERS)

```
/apps/opsi-api/app/modules/identity/     @security-team @backend-leads
/apps/opsi-api/app/modules/agents/       @ai-platform @backend-leads
/apps/opsi-api/app/modules/search/       @ai-platform
/apps/opsi-api/app/modules/chat/         @backend-leads
/apps/opsi-web/src/features/             @frontend-leads
/apps/copilot-runtime/                   @ai-platform @frontend-leads
/services/ingestion/                     @data-platform
/database/migrations/                    @dba @backend-leads
/infrastructure/                         @platform-ops @security-team
/docs/adr/                               @architects
```

## Steps

| # | Branch / PR | Content (from kit) | Flag / safety | Verify | Roll back |
|---|---|---|---|---|---|
| 0 | `revamp/phase-0-inventory` | Phase 0 reports (redacted, no secrets), decisions table filled | docs only | review | revert |
| 1 | `revamp/kit-docs` | `docs/`, `START_HERE.md`, `.env.example`, `.gitignore`, `Makefile`, `scripts/`, `tools/` | no runtime effect | `make smoke` (docs/tools) | revert |
| 1a | `revamp/repo-policy` | `infrastructure/repo/*` templates copied to `.github/`, `.gitattributes`, `third_party/README.md`; `scripts/repo/` | CI only | `repo_hygiene.py`, secret scan; then admins mark checks required | revert |
| 2 | `revamp/db-migrations` | `database/` (0000-0005; optional 0006/0007 later) | applied only via `migrate.sh` in a window | validator + rehearsal on snapshot | down scripts after snapshot |
| 3 | `revamp/ingestion` | `services/ingestion`, `requirements/ingestion.txt`, systemd/cron units | timers disabled until dry-run OK | `pytest tests/ingestion`, dry-run on EC2 | stop timers; delete bronze prefix if needed |
| 4 | `revamp/api-core` | `_shared`, `identity`, `chat`, `install.py` (routers mounted under `/api/v2`, not exposed by NGINX yet) | `OPSI_REVAMP_ENABLED` flag around `install_revamp` | API tests inside the Opsi app | flag off / revert |
| 5 | `revamp/search-rag` | `search`, `rag`, `catalog`, `ontology` | same flag | tests | flag off |
| 6 | `revamp/agent` | `agents`, `llm` + Portkey config | same flag; agent endpoint loopback only | contract tests + Portkey smoke | flag off |
| 7 | `revamp/copilot-runtime` | `apps/copilot-runtime`, systemd unit, NGINX location in the **revamp** server block | runtime not started until approved | bridge tests + E2E smoke | stop unit, remove include |
| 8 | `revamp/web-chat` | `apps/opsi-web/src/features/*` grafted, provider behind a UI flag, `package.json` deps pinned | UI flag default off | `npm run build`, tsc, V2 scan, Playwright on staging | flag off / revert |
| 9 | `revamp/observability` | OTel wiring + collector config | sampling low first | traces visible, no content | disable exporter |
| 10 | `revamp/openmetadata` | compose templates + metadata ingestion config | separate stack | health + catalog search | `down`, restore OM DB snapshot |
| 11 | `revamp/voice` (later) | voice module enabled in lab only | `OPSI_VOICE_ENABLED` | manual | flag off |

Commit message convention: `area: imperative summary` + body with evidence (commands run, results) + rollback line.

## Before any push
- [ ] `git remote -v` shows `origin` = the NEW private repo, `legacy-opsi` push disabled.
- [ ] `python3 scripts/secret_scan.py` = 0 findings; no `.env`, dumps, Parquet, inventory reports with secrets.
- [ ] Tests green; evidence in the PR description.
- [ ] Explicit approval to push recorded.

## Global rollback
Because every user-visible piece is behind a flag and the legacy app is untouched, the fastest rollback is:
flags off -> stop runtime + timers -> remove NGINX include -> (only if needed) DB down scripts after snapshot.
Production Opsi keeps running from the legacy repository throughout.
