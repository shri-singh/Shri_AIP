// Renders SERVER tool calls (retrieval routes) inside the chat. The server streams TOOL_CALL_START/ARGS/END
// plus TOOL_CALL_RESULT; `result` is the JSON payload built in agents/orchestrator.py (items with "cite" keys).
import { useDefaultRenderTool } from "@copilotkit/react-core/v2";

interface RoutePayload {
  route?: string;
  items?: Array<Record<string, unknown> & { cite?: string }>;
  notes?: string[];
  truncated?: boolean;
  error?: string;
  message?: string;
}

function parse(result: string | undefined): RoutePayload | null {
  if (!result) return null;
  try {
    return JSON.parse(result) as RoutePayload;
  } catch {
    return null;
  }
}

const LABELS: Record<string, string> = {
  exact_logs: "Searched logs",
  historical_incident_search: "Searched past incidents",
  metadata_search: "Looked up the catalog",
  service_graph: "Explored dependencies",
  sql_aggregation: "Aggregated metrics",
  vector_knowledge: "Searched runbooks",
};

function RouteCard({ name, status, result }: { name: string; status: string; result?: string }) {
  const payload = parse(result);
  const label = LABELS[name] ?? name;
  if (status !== "complete") return <div className="opsi-tool running">{label}…</div>;
  if (!payload) return <div className="opsi-tool">{label}</div>;
  if (payload.error) return <div className="opsi-tool error">{label}: {payload.message ?? payload.error}</div>;
  const items = payload.items ?? [];
  return (
    <details className="opsi-tool">
      <summary>
        {label}: {items.length} result{items.length === 1 ? "" : "s"}
        {payload.truncated ? " (truncated)" : ""}
      </summary>
      <ul>
        {items.slice(0, 20).map((item, i) => (
          <li key={i}>
            {item.cite && <span className="opsi-cite">[{item.cite}]</span>}{" "}
            {String(item.title ?? item.message ?? item.fqn ?? item.problem ?? item.relation ?? "")}
          </li>
        ))}
      </ul>
      {payload.notes?.map((n) => <small key={n}>{n}</small>)}
    </details>
  );
}

export function OpsiToolRenderers() {
  useDefaultRenderTool({
    render: ({ name, status, result }) => <RouteCard name={name} status={status} result={result} />,
  });
  // Named renderers can be added per route with useRenderTool({ name, parameters, render }) when a
  // richer view is needed (e.g. service_graph -> <IncidentGraph/> preview).
  return null;
}
