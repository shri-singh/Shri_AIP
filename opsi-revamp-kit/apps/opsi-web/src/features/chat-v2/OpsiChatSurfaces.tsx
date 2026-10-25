// The three chat surfaces from the master prompt, all V2 components (verified props in react-core 1.79.1):
//   <CopilotSidebar defaultOpen width position labels .../>, <CopilotPopup .../>, <CopilotChat threadId .../>
import { CopilotChat, CopilotPopup, CopilotSidebar, useAgent } from "@copilotkit/react-core/v2";
import { useEffect, useState } from "react";

import { OPSI_AGENT_ID } from "./OpsiCopilotProvider";
import { ThreadSidebar } from "./threads/ThreadSidebar";
import { useRestoreThread } from "./threads/useRestoreThread";

const labels = { chatInputPlaceholder: "Ask about this incident, a service or a time range…" };

/** Global sidebar available on every page (mount once in the app shell). */
export function OpsiSidebar() {
  return <CopilotSidebar agentId={OPSI_AGENT_ID} defaultOpen={false} width={420} labels={labels} />;
}

/** Lightweight popup for pages where the sidebar would cover dense dashboards. */
export function OpsiPopup() {
  return <CopilotPopup agentId={OPSI_AGENT_ID} defaultOpen={false} labels={labels} clickOutsideToClose />;
}

/** Full-page investigation workspace with persistent history (route e.g. /investigations/:threadId?). */
export function OpsiChatPage({ initialThreadId, incidentId }: { initialThreadId?: string; incidentId?: string }) {
  const { restore, startNew, evidence, ready } = useRestoreThread();
  const [threadId, setThreadId] = useState<string | null>(initialThreadId ?? null);
  const { agent } = useAgent({ agentId: OPSI_AGENT_ID });

  useEffect(() => {
    if (!ready) return;
    if (threadId) void restore(threadId);
    else setThreadId(startNew());
  }, [ready]); // eslint-disable-line react-hooks/exhaustive-deps

  // Surface unverified citation markers flagged by the server (CUSTOM event "opsi.answer_check").
  const [flagged, setFlagged] = useState<string[]>([]);
  useEffect(() => {
    const sub = agent.subscribe({
      onCustomEvent: ({ event }) => {
        if (event.name === "opsi.answer_check") {
          setFlagged((event.value as { unknownCitations?: string[] }).unknownCitations ?? []);
        }
      },
    });
    return () => sub.unsubscribe();
  }, [agent]);

  return (
    <div className="opsi-chat-page" style={{ display: "grid", gridTemplateColumns: "280px 1fr 300px", height: "100%" }}>
      <ThreadSidebar
        activeThreadId={threadId}
        incidentId={incidentId}
        onSelect={async (id) => { setThreadId(id); await restore(id); }}
        onNew={() => setThreadId(startNew())}
      />
      {threadId && <CopilotChat agentId={OPSI_AGENT_ID} threadId={threadId} labels={labels} />}
      <aside aria-label="Evidence">
        <h3>Evidence</h3>
        {flagged.length > 0 && <p role="status">Unverified markers removed: {flagged.join(", ")}</p>}
        <ol>
          {evidence.map((e) => (
            <li key={e.citation_key} id={`cite-${e.citation_key}`}>
              <strong>[{e.citation_key}]</strong> {e.title ?? e.source_ref}
              {e.url && <> — <a href={e.url} target="_blank" rel="noreferrer noopener">open</a></>}
              {e.snippet && <blockquote>{e.snippet}</blockquote>}
            </li>
          ))}
        </ol>
      </aside>
    </div>
  );
}
