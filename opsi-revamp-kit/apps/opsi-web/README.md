# opsi-web features (CopilotKit V2, metadata, incident graph, reports)

Feature folders to copy into the **existing** Opsi React app. `package.json`/`tsconfig.json` here are only a
type-check harness pinned to the verified versions; merge the dependency versions into Opsi's own `package.json`.

```
src/features/
  shared/apiClient.ts                 fetch wrapper (+ configureAuth(getToken)), same-origin, x-request-id
  chat-v2/OpsiCopilotProvider.tsx     CopilotKitProvider (V2) with async auth headers, UI actions, renderers
  chat-v2/OpsiChatSurfaces.tsx        OpsiSidebar, OpsiPopup, OpsiChatPage (history + evidence panel)
  chat-v2/useOpsiUiContext.ts         allowlisted page context -> useAgentContext("opsi.ui_context")
  chat-v2/uiActions.tsx               useFrontendTool x4, useRenderTool (chart), useHumanInTheLoop (approval card)
  chat-v2/actionBridge.ts             pages subscribe to UI actions: useUiActionListener(kind, fn)
  chat-v2/renderers.tsx               default renderer for server tool calls (route cards with citations)
  chat-v2/threads/{api.ts, useRestoreThread.ts, ThreadSidebar.tsx}   history, folders, tags, search, restore, uploads
  metadata/{catalogApi.ts, TableOwnershipCard.tsx}                   OpenMetadata via /api/v2/catalog proxy
  incident-graph/IncidentGraph.tsx    React Flow 12 view of /api/v2/ontology neighbourhood
  reports/{chartSpec.ts, EChart.tsx}  declarative ChartSpec -> ECharts option (no model-supplied code)
scripts/verify-copilotkit-v2.mjs      V2 export check + V1-usage scan (comments ignored)
```

## Verify here (harness)
```bash
export SCARF_ANALYTICS=false
npm install && npx tsc -p tsconfig.json --noEmit && node scripts/verify-copilotkit-v2.mjs src
```
Verified 2026-10-24: 15 files type-check (strict, moduleResolution bundler) against @copilotkit/react-core 1.79.1,
React 19.1, zod 4.6.7, echarts 6.1.0, @xyflow/react 12.12.0.

## Integrate into Opsi
Consultation 11 + phase guide 4.4. Key points: provider inside the router and auth provider, behind a flag;
`configureAuth`; `moduleResolution: "bundler"`; `useOpsiUiContext` on pages; `useUiActionListener` where actions apply;
lazy-load `OpsiChatPage`. Selectors in `tests/e2e/incident_journey.spec.ts` expect some `data-testid`s - add them.
