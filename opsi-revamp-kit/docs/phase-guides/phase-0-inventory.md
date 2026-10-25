# Phase 0 - inventory and compatibility (no changes)

Goal: know exactly what Opsi is today, what the host can do, and decide the integration options - **without
changing anything**. Time: 0.5-1 day.

## Step 1 - host facts
```bash
cd ~/opsi-revamp-kit
scripts/preflight.sh                       # versions, time sync, disk, env-file permissions
scripts/phase0/inventory_host.sh --check-egress
less inventory/phase0-host-*.md
```
Look for: Python >= 3.11 available (`dnf list available 'python3.1*'`), Node >= 20.18, Docker Compose >= 2.24, free
memory for the OpenMetadata lab, egress to pypi/npm/docker/Dynatrace/Portkey (`000` = blocked -> raise a network ticket).

## Step 2 - clone the baseline read-only (Phase 1 does the revamp remote)
If you only want to inspect first: `git clone <opsi-url> ~/workspaces/opsi-baseline-snapshot && git -C ~/workspaces/opsi-baseline-snapshot remote set-url --push origin DISABLED`.

## Step 3 - source inventory
```bash
python3 scripts/phase0/inventory_opsi.py ~/workspaces/opsi-baseline-snapshot --out inventory/
less inventory/phase0-opsi-*.md
```
The report lists: frontend packages (React, TS, build tool, router, state, charts, existing CopilotKit and whether V1),
`tsconfig` `moduleResolution`, Python deps, FastAPI app/routers, auth signals (OAuth2PasswordBearer, jwt.decode,
session cookies), DB libraries, Alembic, Redis, integrations (Elastic/OpenSearch/Dynatrace/Portkey/Bedrock/LLM SDKs),
env var **names**, Docker/Compose/NGINX/CI files and published ports, and **possible secrets** (file + pattern only).
If secrets show up: tell the owners, rotate, do not copy the report anywhere public.

Manual follow-ups the script cannot answer:
```bash
cd ~/workspaces/opsi-baseline-snapshot
grep -rn "FastAPI(" --include=*.py | head          # app factory location
grep -rn "include_router" --include=*.py | head    # existing prefixes; check for /api/v2 collisions
grep -rn "get_current_user\|Depends(.*auth" --include=*.py | head
grep -rn "localStorage.*token\|Authorization" --include=*.ts --include=*.tsx src | head   # how the SPA sends auth
grep -rn "EventSource\|text/event-stream" -r . --include=*.ts* | head                    # existing SSE use
cat package.json | python3 -c "import json,sys;d=json.load(sys.stdin);print({k:v for k,v in {**d.get('dependencies',{}),**d.get('devDependencies',{})}.items() if k in ('react','vite','react-scripts','webpack','typescript','react-router-dom','zod')})"
```

## Step 4 - vendor facts (already done for you on 2026-10-24; re-check if months have passed)
- CopilotKit V2 exports/props: [../verified-facts.md](../verified-facts.md); re-verify with `apps/opsi-web/scripts/verify-copilotkit-v2.mjs`.
- OpenMetadata release + requirements + licence: same file; UI deps: [../reference/](../reference/openmetadata-ui-2.0.6-components.md).
- Optional deeper study: `OM_REF=2.0.6-release scripts/fetch_upstreams.sh vendor/` then browse
  `vendor/OpenMetadata/openmetadata-ui/src/main/resources/ui/src/components/`.

## Step 5 - decide (fill this table, put it in the PR of commit-plan step 0)

| Decision | Options | Choose based on | Decision |
|---|---|---|---|
| React compatibility | React 18/19 OK (peer `^18 \|\| ^19`); older -> upgrade first | inventory | |
| Build tool supports package `exports` + `moduleResolution: bundler` | Vite / webpack 5 yes; CRA (react-scripts 5) needs workarounds -> consider Vite migration | inventory | |
| zod in app | needs >= 3.25 for CopilotKit; zod 4 fine | inventory | |
| Auth for API modules | `existing` adapter (reuse Opsi session) / `oidc` | how Opsi authenticates today | |
| Browser credential to runtime | bearer via provider `headers` / HttpOnly cookie forwarded | SPA token handling | |
| DB migration mechanism | Alembic wrapper / `scripts/migrate.sh` | inventory (alembic.ini?) | |
| Where revamp schemas live | Opsi app DB (default) / separate DB | DBA | |
| Collector state | SQLite on host / PostgreSQL | single vs multiple collector hosts | |
| OpenMetadata placement | separate EC2 + RDS + OpenSearch (recommended) / lab only for now | budget, security | |
| Search backend for OM | OpenSearch 3.x (managed) / Elasticsearch 9.x | corporate standard | |
| Elastic client major | must equal log cluster major | `curl $ELASTIC_URL` version | |
| LLM routing | Portkey provider slug / Portkey config / direct Bedrock fallback | AI platform | |
| OTLP destination | Dynatrace / Elastic APM / other | observability team | |

## Exit criteria
- Host and source reports exist; decisions table filled; blockers list sent (see
  [../requirements-traceability.md](../requirements-traceability.md#blocking-identifiers-to-collect-ask-the-owners)).
- Nothing in production changed.
