// Typed client for /api/v2/chat (apps/opsi-api/app/modules/chat/router.py).
import { api } from "../../shared/apiClient";

export interface Thread {
  id: string;
  owner_id: string;
  title: string;
  folder_id: string | null;
  visibility: "private" | "tenant";
  linked_incident_id: string | null;
  linked_service_id: string | null;
  tags: string[];
  created_at: string;
  updated_at: string;
  last_message_at: string | null;
  archived_at: string | null;
}
export interface Folder { id: string; name: string; parent_id: string | null; created_at: string }
export interface Tag { id: string; name: string; color: string | null }
export interface Evidence {
  citation_key: string; source_type: string; source_ref: string; title: string | null;
  event_time: string | null; snippet: string | null; url: string | null; message_id: string | null;
}
/** AG-UI wire-format message (camelCase), ready for agent.setMessages(). */
export type AgUiMessage = { id: string; role: string; content?: unknown; toolCalls?: unknown[]; toolCallId?: string };

export interface RestoredThread {
  thread: Thread;
  messages: AgUiMessage[];
  evidence: Evidence[];
  state: Record<string, unknown>;
}

export interface ThreadQuery {
  folder_id?: string; tag?: string; q?: string; incident_id?: string;
  include_archived?: boolean; include_shared?: boolean; limit?: number; before?: string;
}

const qs = (q: Record<string, unknown>) =>
  new URLSearchParams(Object.entries(q).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)]));

export const chatApi = {
  listThreads: (q: ThreadQuery = {}) => api<Thread[]>(`/api/v2/chat/threads?${qs({ ...q })}`),
  createThread: (body: { id?: string; title?: string; folder_id?: string; linked_incident_id?: string }) =>
    api<Thread>("/api/v2/chat/threads", { method: "POST", body: JSON.stringify(body) }),
  updateThread: (id: string, body: Partial<{ title: string; folder_id: string; clear_folder: boolean;
    visibility: "private" | "tenant"; archived: boolean }>) =>
    api<Thread>(`/api/v2/chat/threads/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  restore: (id: string) => api<RestoredThread>(`/api/v2/chat/threads/${id}/messages`),
  listFolders: () => api<Folder[]>("/api/v2/chat/folders"),
  createFolder: (name: string, parent_id?: string) =>
    api<Folder>("/api/v2/chat/folders", { method: "POST", body: JSON.stringify({ name, parent_id }) }),
  listTags: () => api<Tag[]>("/api/v2/chat/tags"),
  createTag: (name: string, color?: string) =>
    api<Tag>("/api/v2/chat/tags", { method: "POST", body: JSON.stringify({ name, color }) }),
  setTags: (threadId: string, tag_ids: string[]) =>
    api<Thread>(`/api/v2/chat/threads/${threadId}/tags`, { method: "PUT", body: JSON.stringify({ tag_ids }) }),
  search: (q: string) =>
    api<Array<{ thread_id: string; thread_title: string; message_id: string | null; snippet: string }>>(
      `/api/v2/chat/search?${qs({ q })}`),
  feedback: (threadId: string, message_id: string, rating: 1 | -1, reason_code?: string, comment?: string) =>
    api<void>(`/api/v2/chat/threads/${threadId}/feedback`, {
      method: "POST", body: JSON.stringify({ message_id, rating, reason_code, comment }),
    }),
};

/** Browser -> S3 upload via presigned POST; the API never proxies file bytes. */
export async function uploadAttachment(threadId: string, file: File): Promise<{ id: string; status: string }> {
  const init = await api<{ attachment_id: string; upload_url: string; fields: Record<string, string> }>(
    `/api/v2/chat/threads/${threadId}/attachments`,
    { method: "POST", body: JSON.stringify({ filename: file.name, mime_type: file.type, size_bytes: file.size }) },
  );
  const form = new FormData();
  for (const [k, v] of Object.entries(init.fields)) form.append(k, v);
  form.append("file", file); // must be the LAST field for S3 POST policies
  const put = await fetch(init.upload_url, { method: "POST", body: form });
  if (!put.ok) throw new Error(`upload failed (${put.status})`);
  return api(`/api/v2/chat/attachments/${init.attachment_id}/finalize`, { method: "POST" });
}
