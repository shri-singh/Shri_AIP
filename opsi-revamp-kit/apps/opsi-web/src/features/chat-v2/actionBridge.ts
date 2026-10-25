// Decouples agent UI actions from page components. Existing Opsi pages opt in with
// `useUiActionListener("set_dashboard_filter", applyFilters)`; when no page is listening the
// action reports "not available on this page" back to the agent instead of failing silently.
import { useEffect } from "react";

export interface UiActionArgs {
  open_incident: { incident_id: string };
  set_dashboard_filter: {
    panel_id?: string; service_id?: string; severity?: "CRITICAL" | "ERROR" | "WARN" | "INFO";
    environment?: string; time_from?: string; time_to?: string;
  };
  highlight_graph_nodes: { entity_keys: string[] };
}

type Listener<K extends keyof UiActionArgs> = (args: UiActionArgs[K]) => void | Promise<void>;
type AnyListener = (args: unknown) => void | Promise<void>;
const listeners = new Map<keyof UiActionArgs, Set<AnyListener>>();

export async function dispatchUiAction<K extends keyof UiActionArgs>(kind: K, args: UiActionArgs[K]): Promise<string> {
  const set = listeners.get(kind);
  if (!set || set.size === 0) return `${kind} is not available on the current page`;
  for (const fn of set) await fn(args);
  return `${kind} applied`;
}

export function useUiActionListener<K extends keyof UiActionArgs>(kind: K, fn: Listener<K>): void {
  useEffect(() => {
    const set = listeners.get(kind) ?? new Set<AnyListener>();
    listeners.set(kind, set);
    const wrapped = fn as AnyListener;
    set.add(wrapped);
    return () => {
      set.delete(wrapped);
    };
  }, [kind, fn]);
}
