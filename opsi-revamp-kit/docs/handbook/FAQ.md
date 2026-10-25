# FAQ

Search this file (or everything) with `python3 tools/kb/ask.py "<question>"`.
Sections: [General](#general) · [Repos & Git](#repos--git) · [Ingestion](#ingestion) · [Database](#database) ·
[API modules](#api-modules) · [Agent & chat](#agent--chat) · [CopilotKit & frontend](#copilotkit--frontend) ·
[OpenMetadata](#openmetadata) · [LLM](#llm) · [Security](#security) · [Operations](#operations)

## General

### What do I touch first on the EC2 box?
`START_HERE.md` section 1: preflight -> host inventory -> clones -> source inventory -> `make venv smoke`.

### Is any of this deployed?
No. The kit is tested reference code + docs. See README "Verification evidence" for what ran where.

### OpenMetadata or OpenStack?
**OpenMetadata** (data catalog). OpenStack (cloud platform) is not part of this project at all.

### Where is the decision for X recorded?
`docs/adr/README.md` lists all decisions; consultations explain trade-offs.

### What Python/Node versions?
Python >= 3.11 (pyarrow 26 needs it; 3.12 recommended), Node >= 20.18 (22 LTS recommended), Docker Compose >= 2.24.

## Repos & Git

### Why two clones instead of a branch?
Master prompt requirement + safety: the baseline is an untouchable reference; the revamp has a different remote. ADR-0001.

### How do I make sure I can't push to the legacy repo?
`git remote -v` -> legacy push URL must be `DISABLED-...`. `scripts/clone_repos.sh` sets it.

### How do I bring a hotfix from legacy into the revamp?
`git -C revamp fetch legacy-opsi && git -C revamp cherry-pick <sha>` (resolve, test, note it in the PR).

### Should we fork OpenMetadata / CopilotKit on GitHub?
No. Forks of public repos are public and their visibility can't be changed; GHES can't fork github.com. Use private
mirrors (`scripts/repo/mirror_upstream.sh`). [repository-strategy.md](../repository-strategy.md) section 3, ADR-0020.

### Do we copy the whole OpenMetadata/CopilotKit repo into our repo?
No. Packages (CopilotKit, AG-UI, ECharts ...) and services (OpenMetadata server via REST) cover almost everything;
the few source files you need enter via `scripts/repo/vendor_component.py` into `third_party/` with provenance.
Decision ladder: [repository-strategy.md](../repository-strategy.md#5-decision-ladder-how-a-component-enters-the-product).

### Can we use git submodules for the upstreams?
Not in the product repo (`repo_hygiene.py` fails on them). Fine in a personal study setup.

### I edited a vendored file and CI fails.
Record it: `python3 scripts/repo/vendor_component.py mark-modified --id <id> --note "what and why"`, then regenerate
`THIRD_PARTY_NOTICES.md` with `vendor_component.py notices --out THIRD_PARTY_NOTICES.md`.

### How do I see if upstream has a newer release than we pinned?
`python3 scripts/repo/workspace.py upstream-updates --manifest ~/workspaces/workspace.json`; for vendored files
`vendor_component.py diff-upstream --id <id> --upstream <clone> --to <tag>`.

### Can I use a personal GitHub token on the corporate box?
Only per corporate policy, via `gh auth login`/credential manager. Never in URLs, scripts or history. See cheatsheets/git-and-gh.md.

## Ingestion

### How do I run a collector once without writing anything?
`python -m opsi_ingest collect --source elastic --dry-run` (from `services/ingestion`, env loaded).

### How do I add a new source?
Consultation 04 "Adding a source": capture + redact fixtures, implement `sources/<name>.py` (`fetch(window)`, `FieldMap`,
`window_semantics`, `WindowTooLarge`, `request_with_retry`), tests, register in `sources/__init__.py`, dry-run, timer.

### What happens if the collector host reboots mid-run?
The window stays `running` in the ledger and is retried next run; parts without a manifest are ignored. No loss.

### What happens if PostgreSQL is down?
Bronze collection continues; index items retry with backoff, then dead-letter; `requeue-dead` after recovery.

### Why do I see `event_outside_window` in quarantine?
Records with timestamps outside `[start,end)`. A few at boundaries are normal; many mean timestamp field/zone problems.

### Why are open Dynatrace problems in every window?
Problems v2 returns problems relevant to the timeframe (snapshot semantics). Curated upsert keeps the latest observation.

### How do I find the raw record behind a citation?
`source_ref` + `event_uid` -> bronze parts for that window (`raw/<source>/.../window=.../run=<latest>/`), filter by `event_uid`
(Athena or `pyarrow.parquet.read_table(...).filter(...)`).

### How do I add a redaction rule?
Edit `services/ingestion/opsi_ingest/redaction.py` (`_SECRET_PATTERNS`, `_PII_PATTERNS` or `EXTRA_PATTERNS`), add a test
in `tests/ingestion/test_redaction.py`, then `python scripts/sync_redaction.py` to copy it to the API. Build test strings at
runtime (`"AKIA" + "..."`) so scanners don't flag the repo.

### How big will S3 get?
Consultation 13: roughly 15 % of filtered log bytes per day x retention.

### Can I change the window size later?
Yes, carefully: runbook "Changing the window size" (watermark must be on the new grid).

### Grail says RESULT_GONE / query takes too long.
Results live ~1 min after completion; poll promptly (the adapter does). Long queries: narrow DQL, smaller window, raise
`DYNATRACE_GRAIL_POLL_BUDGET_SECONDS`, check scan limits.

## Database

### Where do the revamp tables live?
Opsi app DB, schemas `opsi_ingest`, `opsi_chat`, `opsi_knowledge`, `opsi_audit`, `opsi_meta` (migrations 0000-0007).

### Do I need Alembic?
If Opsi uses Alembic, wrap each SQL file in a revision (`op.execute(Path(...).read_text())`); else use `scripts/migrate.sh`.

### How do I test migrations without a database server?
`cd database/validate && npm ci && node validate_migrations.mjs` (PGlite, PostgreSQL 18 in WASM) - 40 checks incl. RLS.

### Why does my psql query return no rows from opsi tables?
RLS: set `SELECT set_config('opsi.tenant_id','<tenant>',false);` (and `opsi.user_id` for chat). Superusers bypass RLS - don't
use them for app checks.

### How do I see another user's thread for support?
Use an audited admin procedure: as owner with a ticket, set the user's ids in the session (`set_config`) in a read-only
transaction, or build an admin endpoint with an `admin:read` permission and audit - never disable RLS.

## API modules

### How do I graft the modules into Opsi?
`apps/opsi-api/README.md`: copy `app/modules`, merge requirements, call `install_revamp` behind a flag, pick auth mode.

### How do I test one route by hand?
Run inside the API environment with the full env loaded (`build_services` opens the DB pool and builds the Portkey
gateway, so `OPSI_API_DATABASE_URL` and `PORTKEY_*` must be set):
```python
import asyncio
from app.modules._shared.settings import get_settings
from app.modules.install import build_services
from app.modules.identity.principal import Principal
from app.modules.search.contracts import RouteContext, RunBudget
from app.modules.rag.citations import CitationRegistry
async def main():
    svc = await build_services(get_settings())
    p = Principal(user_id="me", tenant_id="default", roles=frozenset({"investigator"}))
    out = await svc.search.execute("historical_incident_search",
        {"query": "timeout", "time_from": "2026-10-01T00:00:00Z", "time_to": "2026-10-24T00:00:00Z"},
        RouteContext(p, RunBudget(5, 50, 60)), CitationRegistry())
    print(out.model_items, out.result.notes)
asyncio.run(main())
```

### How do I add a new retrieval route?
Create `search/routes/<name>.py` with an args model (`RouteArgs`/`TimeWindowArgs`, `extra=forbid`, limits), class with
`name/description/args_model/permission/cost_units/timeout_seconds/max_items` and `async run()` returning `RouteResult`
with citations; register in `install.py`; tests in `tests/api/`.

### How do I add a UI action?
Server: model + `UiAction` in `agents/ui_actions.py`. Client: `useFrontendTool` with a matching zod schema in
`chat-v2/uiActions.tsx` and a page listener via `useUiActionListener`. Tests: validation + contract. ADR-0013.

### How do I make `draft_incident_update` actually save?
Replace `record_only_executor` in `agents/approvals.py` `EXECUTORS` with a function that calls Opsi's incident service
**as the deciding user** (pass their identity/session; let Opsi authorise), returns `{saved: true, id: ...}`; test it.

## Agent & chat

### Why are some client messages ignored?
Server-owned history (ADR-0005): only new user messages and results for pending browser actions are accepted.

### Why did the answer lose a `[c9]`?
It cited a key the server never issued; removed and reported via `CUSTOM opsi.answer_check`.

### How do threads come back after login?
`GET /api/v2/chat/threads/{id}/messages` -> `agent.setMessages` + `setState` (`useRestoreThread`).

### How do I share a thread?
`PATCH /api/v2/chat/threads/{id}` `{"visibility":"tenant"}` (needs `chat:share`); colleagues can read, not write.

### Where are attachments stored?
S3 `chat-attachments/tenant=<t>/thread=<id>/<uuid>`; metadata in `opsi_chat.attachments`; download only when scan is clean.

## CopilotKit & frontend

### Which CopilotKit APIs are V2?
Imports from `@copilotkit/react-core/v2` (`CopilotKitProvider`, `CopilotChat`, `CopilotSidebar`, `CopilotPopup`, hooks
`useAgent`, `useAgentContext`, `useFrontendTool`, `useHumanInTheLoop`, `useRenderTool`, ...). `<CopilotKit>` is the V1
compatibility wrapper. Check: `node scripts/verify-copilotkit-v2.mjs src`.

### Online examples use `useCopilotAction` / `useCopilotReadable` - can I?
No - those are V1. Equivalents: `useFrontendTool` / `useAgentContext`.

### Can the browser talk to FastAPI directly?
Only `agents__unsafe_dev_only` (dev). Use the runtime bridge (ADR-0004).

### How do I pass the user's token?
`CopilotKitProvider headers={async () => ({Authorization: ...})}` - already in `OpsiCopilotProvider`.

### Build fails resolving `@copilotkit/react-core/v2`.
Bundler/TS must support package `exports`: `moduleResolution: "bundler"` and Vite/webpack 5. CRA needs migration.

## OpenMetadata

### Can Opsi use OpenMetadata's database for its tables?
No (ADR-0002). Separate DBs, API only.

### Which search engine for OpenMetadata 2.0?
OpenSearch 3.x (>= 3.0, 3.3 recommended) or Elasticsearch 9.x; PostgreSQL >= 15 for its DB.

### The ingestion package licence?
Collate Community License (not Apache) - legal review (ADR-0018).

### Does OpenMetadata lineage tell us incident causes?
No - data lineage only. Incident causality is in Opsi's ontology (ADR-0003).

## LLM

### Which model id do I put in `LLM_MODEL`?
Whatever your account can invoke: `aws bedrock list-inference-profiles` (many models require a profile id) - and what
your Portkey provider expects.

### Can I cache prompts?
Only with approval; client data in prompts. Portkey cache off by default for sensitive tenants.

### How do I estimate cost?
Consultation 13; read `agent_runs.input_tokens/output_tokens` after a pilot week.

## Security

### Is the agent endpoint exposed?
It must not be: loopback binding + NGINX `return 404` for `/api/v2/agents/`.

### What about secrets in logs going to the model?
Redacted at ingestion and again in routes; fenced as untrusted data; telemetry carries no content.

### Can the AI change production data?
Only through approval-gated actions executed by the REST endpoint with a human's session (ADR-0013).

## Operations

### Daily health check?
`scripts/health.sh` + `journalctl -t opsi-alert --since yesterday`.

### How do I roll everything back?
Flags off -> stop runtime + timers -> remove NGINX include -> (if needed) down migrations after snapshot. Runbook "Rollback".

### Where do I record drills/rotations?
Evidence log in your ticket system (runbook "Evidence log").
