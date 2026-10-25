// CopilotKit V2 runtime bridge.
//
//   browser  --(CopilotKitProvider runtimeUrl="/api/copilotkit")-->  NGINX  -->  this process (127.0.0.1:4000)
//   this process  --(AG-UI over HTTP+SSE, HttpAgent)-->  FastAPI POST /api/v2/agents/<agentId>
//
// Verified against @copilotkit/runtime 1.79.1 (exports "./v2" and "./v2/node") and @ag-ui/client 1.0.3:
//   CopilotRuntime({ agents, forwardHeaders, sseKeepAliveIntervalSeconds })
//   createCopilotRuntimeHandler({ runtime, basePath, mode, hooks })  -> (Request) => Promise<Response>
//   createCopilotNodeHandler(fetchHandler)                            -> (req, res) => Promise<void>
//   HttpAgent({ url, headers? })
// Re-check with `npm run check:exports` after every upgrade.
//
// Responsibilities kept here are deliberately small: route + header allowlists, auth presence check,
// request ids, error masking. Authentication/authorization is enforced by FastAPI on every run.
import "./env-guard.js";

import { randomUUID } from "node:crypto";
import type { IncomingMessage, ServerResponse } from "node:http";

import { HttpAgent } from "@ag-ui/client";
import { CopilotRuntime, createCopilotRuntimeHandler } from "@copilotkit/runtime/v2";
import { createCopilotNodeHandler } from "@copilotkit/runtime/v2/node";

import { loadConfig, type RuntimeConfig } from "./config.js";

const ALLOWED_METHODS = new Set(["info", "agent/run", "agent/connect", "agent/stop"]);

export function log(level: "info" | "warn" | "error", event: string, fields: Record<string, unknown> = {}): void {
  // JSON lines; never log headers or bodies (they carry tokens and user text).
  process.stdout.write(JSON.stringify({ ts: new Date().toISOString(), level, event, ...fields }) + "\n");
}

function jsonResponse(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

const SAFE_ERRORS: Record<number, string> = { 400: "bad_request", 401: "unauthenticated", 403: "forbidden",
  404: "not_found", 409: "conflict", 413: "request_too_large", 422: "invalid_request", 429: "rate_limited" };

/**
 * fetch used by HttpAgent. On a non-2xx answer from FastAPI the runtime would otherwise put the raw
 * response body into the RUN_ERROR message streamed to the browser (verified in 1.79.1). Replace it
 * with a stable, non-sensitive error code; the real body stays in FastAPI's logs.
 */
export async function sanitizingFetch(url: string, init: RequestInit): Promise<Response> {
  const response = await fetch(url, init);
  if (response.ok) return response;
  await response.body?.cancel();
  log("warn", "agent_http_error", { status: response.status });
  const code = SAFE_ERRORS[response.status] ?? "agent_error";
  return new Response(JSON.stringify({ error: code }), {
    status: response.status, headers: { "content-type": "application/json" },
  });
}

export function buildFetchHandler(cfg: RuntimeConfig) {
  const agents = Object.fromEntries(
    cfg.agentIds.map((id) => [id, new HttpAgent({
      url: `${cfg.agentBaseUrl}/${encodeURIComponent(id)}`, fetch: sanitizingFetch,
    })]),
  );
  const runtime = new CopilotRuntime({
    agents,
    forwardHeaders: { allow: cfg.forwardHeaders },
    sseKeepAliveIntervalSeconds: cfg.keepAliveSeconds,
  });

  return createCopilotRuntimeHandler({
    runtime,
    basePath: cfg.basePath,
    mode: "multi-route",
    hooks: {
      onRequest: ({ request }) => {
        const length = Number(request.headers.get("content-length") ?? 0);
        if (length > cfg.maxBodyBytes) throw jsonResponse(413, { error: "request_too_large" });
        const hasAuth = cfg.requireAnyAuthHeader.some((h) => request.headers.get(h));
        if (!hasAuth) throw jsonResponse(401, { error: "unauthenticated" });
        if (request.headers.get("x-request-id")) return;
        const headers = new Headers(request.headers);
        headers.set("x-request-id", randomUUID());
        return new Request(request, { headers, duplex: "half" } as RequestInit);
      },
      onBeforeHandler: ({ route, request }) => {
        const allowed =
          ALLOWED_METHODS.has(route.method) || (route.method === "agent/suggest" && cfg.allowSuggestions);
        if (!allowed) throw jsonResponse(404, { error: "not_found" });
        if ("agentId" in route && !cfg.agentIds.includes(route.agentId)) throw jsonResponse(404, { error: "unknown_agent" });
        log("info", "runtime_request", { method: route.method, requestId: request.headers.get("x-request-id") });
      },
      onError: ({ error, route, request }) => {
        // The default error response includes error.message; never leak internals to the browser.
        log("error", "runtime_error", {
          method: route?.method,
          requestId: request.headers.get("x-request-id"),
          error: error instanceof Error ? error.name : "unknown",
        });
        return jsonResponse(502, { error: "agent_unavailable", requestId: request.headers.get("x-request-id") });
      },
    },
  });
}

export function buildNodeListener(cfg: RuntimeConfig) {
  const handle = createCopilotNodeHandler(buildFetchHandler(cfg));
  return async (req: IncomingMessage, res: ServerResponse) => {
    if (req.url === "/healthz") {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ status: "ok", agents: cfg.agentIds }));
      return;
    }
    try {
      await handle(req, res);
    } catch (error) {
      log("error", "listener_error", { error: error instanceof Error ? error.name : "unknown" });
      if (!res.headersSent) {
        res.writeHead(500, { "content-type": "application/json" });
        res.end(JSON.stringify({ error: "internal_error" }));
      } else {
        res.end();
      }
    }
  };
}
