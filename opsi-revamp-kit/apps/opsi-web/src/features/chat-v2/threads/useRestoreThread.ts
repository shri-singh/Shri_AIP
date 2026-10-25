// Restores a saved investigation into the CopilotKit agent after (re)login.
// History comes from OUR database (/api/v2/chat), not CopilotKit Intelligence (useThreads is tied to that
// hosted service). AbstractAgent.setMessages / setState are verified in @ag-ui/client 1.0.x.
import { useAgent } from "@copilotkit/react-core/v2";
import { useCallback, useState } from "react";

import { OPSI_AGENT_ID } from "../OpsiCopilotProvider";
import { chatApi, type Evidence, type RestoredThread } from "./api";

export function useRestoreThread() {
  const { agent, isReady } = useAgent({ agentId: OPSI_AGENT_ID });
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [loading, setLoading] = useState(false);

  const restore = useCallback(async (threadId: string): Promise<RestoredThread | null> => {
    if (!isReady) return null;
    setLoading(true);
    try {
      const data = await chatApi.restore(threadId);
      agent.threadId = threadId;
      // The server re-validates history on every run; this only rebuilds the visible transcript.
      agent.setMessages(data.messages as Parameters<typeof agent.setMessages>[0]);
      agent.setState(data.state);
      setEvidence(data.evidence);
      return data;
    } finally {
      setLoading(false);
    }
  }, [agent, isReady]);

  const startNew = useCallback(() => {
    const id = crypto.randomUUID(); // AG-UI threadId; the server creates the thread on the first run
    agent.threadId = id;
    agent.setMessages([]);
    agent.setState({});
    setEvidence([]);
    return id;
  }, [agent]);

  return { restore, startNew, evidence, loading, ready: isReady };
}
