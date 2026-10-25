// Shares an ALLOWLISTED snapshot of what the user is looking at with the agent.
// Arrives server-side as RunAgentInput.context[{description: "opsi.ui_context", value}] and is validated
// there (apps/opsi-api/app/modules/agents/context.py). It is a hint: identity and permissions are never
// taken from it, so do not put tenant ids, user ids, tokens or free text here.
import { useAgentContext } from "@copilotkit/react-core/v2";

export type OpsiPage = "dashboard" | "incident" | "services" | "metadata" | "settings" | "chat" | "graph" | "reports";

export interface OpsiUiContext {
  page: OpsiPage;
  incident_id?: string;
  service_id?: string;
  time_from?: string; // ISO-8601 UTC
  time_to?: string;
  selected_panel_id?: string;
  selected_chart_id?: string;
  filters?: Record<string, string>;
}

export function useOpsiUiContext(ctx: OpsiUiContext): void {
  // Drop undefined keys: the server rejects unknown fields and nulls are noise.
  const value: Record<string, string | Record<string, string>> = {};
  for (const [k, v] of Object.entries(ctx)) if (v !== undefined && v !== null) value[k] = v as string;
  useAgentContext({ description: "opsi.ui_context", value });
}
