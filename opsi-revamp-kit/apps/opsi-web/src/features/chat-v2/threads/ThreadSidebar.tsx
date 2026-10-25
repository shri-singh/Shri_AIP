// Thread history panel: folders, tags, full-text search, archive. Selecting a thread restores it.
import { useCallback, useEffect, useState } from "react";

import { chatApi, type Folder, type Tag, type Thread } from "./api";

export interface ThreadSidebarProps {
  activeThreadId: string | null;
  onSelect: (threadId: string) => void;
  onNew: () => void;
  incidentId?: string;
}

export function ThreadSidebar({ activeThreadId, onSelect, onNew, incidentId }: ThreadSidebarProps) {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [folder, setFolder] = useState<string | undefined>();
  const [tag, setTag] = useState<string | undefined>();
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setError(null);
      const [t, f, g] = await Promise.all([
        chatApi.listThreads({ folder_id: folder, tag, q: q.length >= 2 ? q : undefined, incident_id: incidentId }),
        chatApi.listFolders(),
        chatApi.listTags(),
      ]);
      setThreads(t);
      setFolders(f);
      setTags(g);
    } catch (e) {
      setError(e instanceof Error ? e.message : "could not load history");
    }
  }, [folder, tag, q, incidentId]);

  useEffect(() => {
    const timer = setTimeout(reload, 250); // debounce search typing
    return () => clearTimeout(timer);
  }, [reload]);

  return (
    <nav className="opsi-threads" aria-label="Investigation history">
      <button onClick={onNew}>New investigation</button>
      <input type="search" placeholder="Search history" value={q} onChange={(e) => setQ(e.target.value)}
             aria-label="Search history" />
      <select value={folder ?? ""} onChange={(e) => setFolder(e.target.value || undefined)} aria-label="Folder">
        <option value="">All folders</option>
        {folders.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
      </select>
      <select value={tag ?? ""} onChange={(e) => setTag(e.target.value || undefined)} aria-label="Tag">
        <option value="">All tags</option>
        {tags.map((t) => <option key={t.id} value={t.name}>{t.name}</option>)}
      </select>
      {error && <p role="alert">{error}</p>}
      <ul>
        {threads.map((t) => (
          <li key={t.id} aria-current={t.id === activeThreadId ? "true" : undefined}>
            <button onClick={() => onSelect(t.id)}>{t.title}</button>
            {t.tags.map((name) => <span key={name} className="opsi-tag">{name}</span>)}
            <button aria-label={`Archive ${t.title}`}
                    onClick={async () => { await chatApi.updateThread(t.id, { archived: true }); await reload(); }}>
              Archive
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
