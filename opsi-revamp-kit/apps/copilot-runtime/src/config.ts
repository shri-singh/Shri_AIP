// Environment-driven configuration. Documented in the kit's .env.example (section "copilot-runtime").

export interface RuntimeConfig {
  host: string;
  port: number;
  basePath: string;
  /** FastAPI AG-UI endpoint prefix; the agent id is appended: <agentBaseUrl>/<agentId> */
  agentBaseUrl: string;
  agentIds: string[];
  /** Inbound headers forwarded to FastAPI (allowlist mode). Lower-case names. */
  forwardHeaders: string[];
  /** Require one of these headers on every request (fail fast before reaching FastAPI). */
  requireAnyAuthHeader: string[];
  allowSuggestions: boolean;
  maxBodyBytes: number;
  keepAliveSeconds: number;
}

function list(value: string | undefined, fallback: string[]): string[] {
  if (!value) return fallback;
  return value.split(",").map((v) => v.trim().toLowerCase()).filter(Boolean);
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): RuntimeConfig {
  const agentBaseUrl = (env.OPSI_AGENT_BASE_URL ?? "http://127.0.0.1:8000/api/v2/agents").replace(/\/+$/, "");
  const parsed = new URL(agentBaseUrl);
  if (!["http:", "https:"].includes(parsed.protocol)) throw new Error("OPSI_AGENT_BASE_URL must be http(s)");
  if (parsed.username || parsed.password) throw new Error("OPSI_AGENT_BASE_URL must not embed credentials");
  const forward = list(env.RUNTIME_FORWARD_HEADERS, ["authorization", "x-request-id", "traceparent", "tracestate"]);
  for (const forbidden of ["host", "content-length", "connection", "x-forwarded-for", "x-real-ip"]) {
    if (forward.includes(forbidden)) throw new Error(`RUNTIME_FORWARD_HEADERS must not include ${forbidden}`);
  }
  return {
    host: env.RUNTIME_HOST ?? "127.0.0.1",
    port: Number(env.RUNTIME_PORT ?? 4000),
    basePath: env.RUNTIME_BASE_PATH ?? "/api/copilotkit",
    agentBaseUrl,
    agentIds: list(env.OPSI_COPILOT_AGENT_IDS, ["opsi-investigator"]),
    forwardHeaders: forward,
    requireAnyAuthHeader: list(env.RUNTIME_REQUIRE_AUTH_HEADERS, ["authorization", "cookie"]),
    allowSuggestions: (env.RUNTIME_ALLOW_SUGGESTIONS ?? "false") === "true",
    maxBodyBytes: Number(env.RUNTIME_MAX_BODY_BYTES ?? 2 * 1024 * 1024),
    keepAliveSeconds: Number(env.RUNTIME_SSE_KEEPALIVE_SECONDS ?? 15),
  };
}
