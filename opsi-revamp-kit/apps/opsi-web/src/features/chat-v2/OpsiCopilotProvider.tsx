// CopilotKit V2 provider for the EXISTING Opsi React app.
// Verified against @copilotkit/react-core 1.79.1 (`@copilotkit/react-core/v2`): CopilotKitProvider props
// runtimeUrl, agentId, headers (record or async builder), credentials, onError, enableInspector.
// Do NOT use the V1 `<CopilotKit>` wrapper or imports from "@copilotkit/react-core" without "/v2".
//
// Mount it INSIDE the router (so hooks can read the location) and INSIDE the existing auth provider:
//   <AuthProvider><BrowserRouter><OpsiCopilotProvider>...existing routes...</OpsiCopilotProvider></BrowserRouter></AuthProvider>
import { CopilotKitProvider } from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";
import type { ReactNode } from "react";

import { authHeaders } from "../shared/apiClient";
import { OpsiUiActions } from "./uiActions";
import { OpsiToolRenderers } from "./renderers";

export const OPSI_AGENT_ID = "opsi-investigator";
export const RUNTIME_URL = "/api/copilotkit"; // NGINX -> copilot-runtime (127.0.0.1:4000), never FastAPI directly

export function OpsiCopilotProvider({ children }: { children: ReactNode }) {
  return (
    <CopilotKitProvider
      runtimeUrl={RUNTIME_URL}
      agentId={OPSI_AGENT_ID}
      // Async builder runs per request -> always a fresh access token. The runtime forwards
      // `authorization` to FastAPI, which validates it on every run.
      headers={async () => ({ ...(await authHeaders()), "x-request-id": crypto.randomUUID() })}
      credentials="same-origin"
      enableInspector={false}
      onError={({ error, code }) => {
        // Hook into the existing Opsi error reporting; never log message contents.
        console.warn("copilot error", code, error.name);
      }}
    >
      <OpsiUiActions />
      <OpsiToolRenderers />
      {children}
    </CopilotKitProvider>
  );
}
