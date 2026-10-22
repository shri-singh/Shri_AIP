// Example to adapt into EXISTING Opsi React app. Not a standalone runnable app.
// Verify exports against installed/pinned CopilotKit V2 package.
import React from 'react';
import { CopilotKitProvider, CopilotSidebar } from '@copilotkit/react-core/v2';
import '@copilotkit/react-core/v2/styles.css';

export type OpsiUiContext = {
  page: 'dashboard' | 'incident' | 'services' | 'metadata' | 'settings' | 'chat';
  serviceId?: string;
  incidentId?: string;
  timeFrom?: string;
  timeTo?: string;
};

export function OpsiCopilotHost({ children }: { children: React.ReactNode }) {
  return (
    <CopilotKitProvider runtimeUrl="/api/copilotkit" agentId="opsi-investigator">
      {children}
      <CopilotSidebar defaultOpen={false} />
    </CopilotKitProvider>
  );
}
// TODO Claude Code: wire actual CopilotKit V2 runtime route (/api/copilotkit) to
// approved FastAPI AG-UI agent endpoint; do not map raw FastAPI text SSE directly.
// TODO: register a well-defined, permission-checked client state and UI-action bridge.
// TODO: implement Opsi persistent conversation/thread adapters as separate services.
