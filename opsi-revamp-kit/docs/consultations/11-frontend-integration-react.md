# 11 - Integrating into the existing React app

## The question
"How do we add CopilotKit V2, charts and the graph into the current Opsi UI without breaking it?"

## Short answer
Add four feature folders, one provider around the router, a feature flag, and exact-pinned dependencies. Use
`moduleResolution: bundler` (Vite/webpack 5). Pages opt into context and actions with two hooks.

## Compatibility checks (from Phase 0)
| Requirement | Why | If not met |
|---|---|---|
| React 18 or 19 | CopilotKit peer range | upgrade React first (separate project) |
| zod >= 3.25 | CopilotKit peer | upgrade zod (4.x fine) |
| Bundler resolves package `exports` subpaths (`/v2`, `/v2/styles.css`) | V2 entry points | Vite/webpack 5 OK; CRA: eject/craco or migrate to Vite |
| TS `moduleResolution: bundler` (or `node16`/`nodenext`) | resolves `exports` types | set in tsconfig; may surface other type errors - fix them |
| CSS imports allowed | `@copilotkit/react-core/v2/styles.css`, `@xyflow/react/dist/style.css` | add CSS loader |
| No V1 CopilotKit in the app | avoid mixed providers | `verify-copilotkit-v2.mjs` flags it |

## Wiring
```tsx
// main.tsx / App.tsx (existing)
import { configureAuth } from "./features/shared/apiClient";
import { OpsiCopilotProvider } from "./features/chat-v2/OpsiCopilotProvider";
import { OpsiSidebar } from "./features/chat-v2/OpsiChatSurfaces";
configureAuth(() => authService.getAccessToken());            // existing auth getter
<AuthProvider><BrowserRouter>
  {flags.revampChat ? (
    <OpsiCopilotProvider><AppRoutes /><OpsiSidebar /></OpsiCopilotProvider>
  ) : <AppRoutes />}
</BrowserRouter></AuthProvider>
```
In pages:
```tsx
useOpsiUiContext({ page: "incident", incident_id, service_id, time_from, time_to });
const apply = useCallback((f) => setFilters((prev) => ({ ...prev, ...f })), []);
useUiActionListener("set_dashboard_filter", apply);
```

## Styling
CopilotKit V2 ships Tailwind-based styles in `v2/styles.css`; isolate if your app uses a different design system
(load it only where the chat renders, or scope overrides). Customise texts with `labels` and slots (`chatView`, header).

## State management
Agent state (`useAgent().agent.state`) is display-only and server-authored; app state (filters, selection) stays in your
existing store; the action bridge connects them explicitly.

## Charts and graphs
- `reports/chartSpec.ts` validates and maps model data to ECharts options; use `EChart` anywhere (also for Perses-style
  dashboards later).
- `incident-graph/IncidentGraph.tsx` uses React Flow 12 (MIT); OpenMetadata uses reactflow 11 - don't mix versions in
  one bundle unless necessary.

## Bundle size
CopilotKit pulls markdown/katex/radix/lucide; lazy-load the chat page (`React.lazy`) and load the sidebar after first
paint. Measure with `vite build --mode production` + `rollup-plugin-visualizer`.

## Future: agent canvas
Only after events/actions are stable: a canvas page subscribing to `agent.state` (evidence, hypotheses) rendering the
graph + charts side by side; consider AG-UI activity events (`ACTIVITY_SNAPSHOT/DELTA`) for long-running steps.

## Verify
`npm run build` of the real app; `tsc --noEmit`; V2 scan; Playwright journey.
