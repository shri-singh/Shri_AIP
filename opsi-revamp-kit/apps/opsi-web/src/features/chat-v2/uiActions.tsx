// Browser-side "frontend tools". Names and schemas MUST match the server allowlist in
// apps/opsi-api/app/modules/agents/ui_actions.py - the server validates arguments before they
// reach this code, and these zod schemas validate them again here (defence in depth).
// Verified hooks (react-core 1.79.1 /v2): useFrontendTool, useRenderTool, useHumanInTheLoop.
import { useFrontendTool, useHumanInTheLoop, useRenderTool } from "@copilotkit/react-core/v2";
import { useState } from "react";
import { z } from "zod";

import { api } from "../shared/apiClient";
import { EChart } from "../reports/EChart";
import { ChartSpecSchema } from "../reports/chartSpec";
import { dispatchUiAction } from "./actionBridge";

const id = z.string().regex(/^[A-Za-z0-9_.:\-/]{1,200}$/);

const OpenIncident = z.object({ incident_id: id });
const SetDashboardFilter = z.object({
  panel_id: z.string().max(64).optional(),
  service_id: id.optional(),
  severity: z.enum(["CRITICAL", "ERROR", "WARN", "INFO"]).optional(),
  environment: z.string().max(40).optional(),
  time_from: z.string().optional(),
  time_to: z.string().optional(),
});
const RenderChart = z.object({ chart: ChartSpecSchema });
const HighlightGraph = z.object({ entity_keys: z.array(z.string().max(300)).min(1).max(50) });
const DraftIncidentUpdate = z.object({
  incident_id: id,
  summary: z.string().min(10).max(4000),
  citations: z.array(z.string()).max(20).optional(),
  approval_id: z.string().uuid(),
  expires_at: z.string().optional(),
});

export function OpsiUiActions() {
  useFrontendTool({
    name: "open_incident",
    description: "Open an incident page in the user's Opsi UI.",
    parameters: OpenIncident,
    handler: async ({ incident_id }) => dispatchUiAction("open_incident", { incident_id }),
  });

  useFrontendTool({
    name: "set_dashboard_filter",
    description: "Change filters on the dashboard the user is viewing.",
    parameters: SetDashboardFilter,
    handler: async (args) => dispatchUiAction("set_dashboard_filter", args),
  });

  useFrontendTool({
    name: "highlight_graph_nodes",
    description: "Highlight entities in the incident dependency graph view.",
    parameters: HighlightGraph,
    handler: async (args) => dispatchUiAction("highlight_graph_nodes", args),
  });

  useFrontendTool({
    name: "render_chart",
    description: "Show a chart in the chat from data you retrieved with tools. Data only.",
    parameters: RenderChart,
    handler: async () => "chart rendered",
  });
  useRenderTool({
    name: "render_chart",
    parameters: RenderChart,
    render: ({ parameters }) => {
      const parsed = RenderChart.safeParse(parameters);
      return parsed.success ? <EChart spec={parsed.data.chart} /> : <em>Preparing chart…</em>;
    },
  });

  useHumanInTheLoop({
    name: "draft_incident_update",
    description: "Propose an incident update. A human must approve it before anything is saved.",
    parameters: DraftIncidentUpdate,
    render: ApprovalCard,
  });

  return null;
}

type ApprovalProps = {
  args: Partial<z.infer<typeof DraftIncidentUpdate>>;
  respond?: (result: unknown) => Promise<void>;
  result?: unknown;
};

/** Approve/Reject goes to the Opsi API with the USER's session; the model never approves anything. */
function ApprovalCard({ args, respond, result }: ApprovalProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (result !== undefined) return <div className="opsi-approval done">Decision recorded.</div>;
  if (!respond || !args.approval_id) return <div className="opsi-approval">Preparing proposal…</div>;

  const decide = async (decision: "approve" | "reject") => {
    setBusy(true);
    setError(null);
    try {
      const outcome = await api<{ status: string }>(`/api/v2/actions/${args.approval_id}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision }),
      });
      await respond({ decision, status: outcome.status });
    } catch (e) {
      setError(e instanceof Error ? e.message : "decision failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="opsi-approval" role="group" aria-label="Approval required">
      <strong>Proposed update for {args.incident_id}</strong>
      <p style={{ whiteSpace: "pre-wrap" }}>{args.summary}</p>
      {error && <p role="alert">{error}</p>}
      <button disabled={busy} onClick={() => decide("approve")}>Approve</button>{" "}
      <button disabled={busy} onClick={() => decide("reject")}>Reject</button>
    </div>
  );
}
