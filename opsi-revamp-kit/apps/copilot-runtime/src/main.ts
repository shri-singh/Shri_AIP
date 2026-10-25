// Process entrypoint: `npm start` (node dist/main.js). Binds to 127.0.0.1 by default - expose only via NGINX.
import "./env-guard.js";

import { createServer } from "node:http";

import { loadConfig } from "./config.js";
import { buildNodeListener, log } from "./server.js";

const cfg = loadConfig();
const server = createServer(buildNodeListener(cfg));
server.headersTimeout = 30_000;
server.requestTimeout = 0; // SSE streams are long-lived; idle protection = keep-alive comments + NGINX timeouts
server.listen(cfg.port, cfg.host, () => {
  log("info", "runtime_listening", {
    host: cfg.host, port: cfg.port, basePath: cfg.basePath, agents: cfg.agentIds, upstream: cfg.agentBaseUrl,
    telemetryDisabled: process.env.COPILOTKIT_TELEMETRY_DISABLED === "true",
  });
});
const shutdown = () => server.close(() => process.exit(0));
process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);
