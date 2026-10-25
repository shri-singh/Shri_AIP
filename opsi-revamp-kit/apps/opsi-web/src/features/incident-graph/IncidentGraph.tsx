// Evidence/dependency graph for an incident or service, from GET /api/v2/ontology/entities/{key}/neighborhood.
// React Flow (@xyflow/react, MIT). Agent action "highlight_graph_nodes" is wired through the action bridge.
import { Background, Controls, type Edge, type Node, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useUiActionListener } from "../chat-v2/actionBridge";
import { api } from "../shared/apiClient";

interface Entity { id: string; kind: string; natural_key: string; name: string }
interface GraphEdge {
  id: string; src_id: string; dst_id: string; relation: string; confidence: number; source_system: string;
  depth: number | null;
}
interface Neighborhood { root: Entity; entities: Entity[]; edges: GraphEdge[]; truncated: boolean }

const KIND_COLORS: Record<string, string> = {
  service: "#2563eb", host: "#64748b", incident: "#dc2626", table: "#7c3aed", team: "#059669", runbook: "#d97706",
};

function layout(data: Neighborhood, highlighted: Set<string>): { nodes: Node[]; edges: Edge[] } {
  const all = new Map<string, Entity>([[data.root.id, data.root], ...data.entities.map((e) => [e.id, e] as const)]);
  const depthOf = new Map<string, number>([[data.root.id, 0]]);
  for (const e of [...data.edges].sort((a, b) => (a.depth ?? 9) - (b.depth ?? 9))) {
    for (const id of [e.src_id, e.dst_id]) if (!depthOf.has(id)) depthOf.set(id, e.depth ?? 1);
  }
  const perLevel = new Map<number, number>();
  const nodes: Node[] = [...all.values()].map((ent) => {
    const level = depthOf.get(ent.id) ?? 1;
    const index = perLevel.get(level) ?? 0;
    perLevel.set(level, index + 1);
    const hot = highlighted.has(ent.natural_key) || highlighted.has(ent.name);
    return {
      id: ent.id,
      position: { x: level * 260, y: index * 90 },
      data: { label: `${ent.kind}: ${ent.name}` },
      style: { border: `2px solid ${KIND_COLORS[ent.kind] ?? "#94a3b8"}`, borderRadius: 8, padding: 6,
               boxShadow: hot ? "0 0 0 4px rgba(250,204,21,.8)" : undefined },
    };
  });
  const edges: Edge[] = data.edges.map((e) => ({
    id: e.id, source: e.src_id, target: e.dst_id, label: `${e.relation}${e.confidence < 1 ? ` (${e.confidence})` : ""}`,
    animated: e.source_system === "agent", style: { strokeDasharray: e.confidence < 1 ? "4 4" : undefined },
  }));
  return { nodes, edges };
}

export function IncidentGraph({ entityKey, depth = 2 }: { entityKey: string; depth?: number }) {
  const [data, setData] = useState<Neighborhood | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [highlighted, setHighlighted] = useState<Set<string>>(new Set());

  useEffect(() => {
    api<Neighborhood>(`/api/v2/ontology/entities/${encodeURIComponent(entityKey)}/neighborhood?depth=${depth}`)
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, [entityKey, depth]);

  const onHighlight = useCallback((args: { entity_keys: string[] }) => setHighlighted(new Set(args.entity_keys)), []);
  useUiActionListener("highlight_graph_nodes", onHighlight);

  const graph = useMemo(() => (data ? layout(data, highlighted) : null), [data, highlighted]);
  if (error) return <div role="alert">Graph unavailable: {error}</div>;
  if (!graph) return <div aria-busy="true">Loading dependency graph…</div>;
  return (
    <div style={{ height: 480 }} aria-label="Dependency graph">
      <ReactFlow nodes={graph.nodes} edges={graph.edges} fitView nodesDraggable={false}>
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
      {data?.truncated && <small>Graph truncated - narrow the depth or open a specific entity.</small>}
    </div>
  );
}
