# Phase 4 - CopilotKit V2, persistent chat, agent

## 4.1 Backend: graft the modules into the existing FastAPI app
See [../../apps/opsi-api/README.md](../../apps/opsi-api/README.md). Summary:
1. Copy `apps/opsi-api/app/modules/` into the Opsi API package (keep the `modules` name or adjust imports).
2. Merge `requirements/api.txt` (resolve conflicts deliberately; run Opsi's own tests).
3. In the app factory/lifespan, behind `OPSI_REVAMP_ENABLED`:
   `install_revamp(app, await build_services(get_settings()), tracing=True)`.
4. Auth: implement the `existing` adapter (returns a `Principal` from Opsi's current user) or configure OIDC.
5. DB: migrations 0003-0005 applied; app login member of `opsi_app`; `OPSI_API_DATABASE_URL` set.
6. Run `pytest tests/api` against the grafted code (adjust import paths) - 52 tests.

## 4.2 Portkey -> Bedrock smoke
```bash
.venv/bin/python - <<'PY'
import asyncio, os
from app.modules._shared.settings import get_settings
from app.modules.llm.gateway import PortkeyGateway, TextDelta
async def main():
    gw = PortkeyGateway(get_settings())
    async for ev in gw.stream_chat([{"role": "user", "content": "Reply with the word ok."}], []):
        if isinstance(ev, TextDelta): print(ev.text, end="")
    print()
asyncio.run(main())
PY
```
Failures: [../handbook/TROUBLESHOOTING.md#llm--portkey--bedrock](../handbook/TROUBLESHOOTING.md#llm--portkey--bedrock).

## 4.3 Runtime bridge
```bash
cd /opt/opsi-revamp-kit/apps/copilot-runtime
SCARF_ANALYTICS=false npm ci && npm run build && npm test && npm run check:exports
sudo cp ../../infrastructure/systemd/opsi-copilot-runtime.service /etc/systemd/system/
sudo install -m 0600 -o opsi-runtime /dev/null /etc/opsi/copilot-runtime.env   # OPSI_AGENT_BASE_URL etc.
sudo systemctl daemon-reload && sudo systemctl enable --now opsi-copilot-runtime
curl -s http://127.0.0.1:4000/healthz
```
NGINX: include `infrastructure/nginx/opsi-revamp.locations.conf` in the revamp server block; `sudo nginx -t && sudo systemctl reload nginx`.
End-to-end on the host (lab app, no real backends): `python tests/e2e/bridge_smoke.py`.

## 4.4 Frontend
See [../../apps/opsi-web/README.md](../../apps/opsi-web/README.md):
1. `SCARF_ANALYTICS=false npm i -E @copilotkit/react-core@1.79.1 echarts@6.1.0 @xyflow/react@12.12.0` and zod
   (keep Opsi's zod if it is >= 3.25, otherwise `zod@4.6.7`). `-E` saves exact versions.
2. Copy `src/features/{chat-v2,metadata,incident-graph,reports,shared}`.
3. `tsconfig.json`: `"moduleResolution": "bundler"` (Vite/webpack 5). Run `node scripts/verify-copilotkit-v2.mjs src`.
4. Wrap the router tree with `<OpsiCopilotProvider>` behind a UI flag; call `configureAuth(getAccessToken)`.
5. Mount `<OpsiSidebar/>` in the shell, `<OpsiChatPage/>` on an `/investigations/:threadId?` route.
6. Pages publish context: `useOpsiUiContext({page: "incident", incident_id, service_id, time_from, time_to})`.
7. Pages that support actions register listeners: `useUiActionListener("set_dashboard_filter", applyFilters)`.

## 4.5 Acceptance (staging)
Run the journey in `tests/e2e/incident_journey.spec.ts` (Playwright) or manually:
open incident -> ask "why" -> see "Searched logs" + "Looked up the catalog" cards -> answer has `[cN]` linked to the
Evidence panel -> ask to filter the dashboard -> filter changes -> tag/folder the thread -> log out/in -> thread,
tags, citations, attachments are back. Also test: a viewer cannot approve, another tenant cannot open the thread URL.

## Exit criteria
All acceptance steps pass in staging with real IdP/Portkey/Elastic/OM; audit events visible; flags allow instant disable.
