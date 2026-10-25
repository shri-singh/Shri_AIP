// OpenMetadata access goes through the Opsi API proxy (/api/v2/catalog), so the browser never holds an
// OpenMetadata bot token and Opsi RBAC applies. For deep catalog work, link users to the OpenMetadata UI.
import { api } from "../shared/apiClient";

export interface CatalogEntity {
  entity_type: string;
  id: string | null;
  name: string | null;
  fqn: string | null;
  description: string;
  owners: string[];
  domains: string[];
  tags: string[];
  service: string | null;
  columns?: Array<{ name: string; type: string; tags: string[] }>;
}

export interface Lineage {
  entity: string;
  nodes: Array<{ id: string; fqn: string; type: string }>;
  edges: Array<{ from: string; to: string }>;
}

export const catalogApi = {
  search: (q: string, entityType = "table", size = 10) =>
    api<CatalogEntity[]>(`/api/v2/catalog/search?${new URLSearchParams({ q, entity_type: entityType, size: String(size) })}`),
  table: (fqn: string) => api<CatalogEntity>(`/api/v2/catalog/tables/${encodeURIComponent(fqn)}`),
  lineage: (fqn: string, upstream = 1, downstream = 1) =>
    api<Lineage>(`/api/v2/catalog/lineage/table/${encodeURIComponent(fqn)}?upstream=${upstream}&downstream=${downstream}`),
};
