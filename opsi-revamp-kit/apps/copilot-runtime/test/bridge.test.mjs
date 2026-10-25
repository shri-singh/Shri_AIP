// Bridge contract tests: real CopilotKit V2 runtime (this package) <-> a recording AG-UI upstream.
// The upstream speaks the same wire format as FastAPI (text/event-stream, "data: {json}\n\n").
// End-to-end against the real FastAPI agent: tests/e2e/bridge_smoke.py.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { after, before, test } from "node:test";

import { loadConfig } from "../dist/config.js";
import { buildNodeListener } from "../dist/server.js";

let upstream, runtime, upstreamUrl, runtimeUrl;
const seen = [];

function sse(events) {
  return events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
}

before(async () => {
  upstream = createServer(async (req, res) => {
    let body = "";
    for await (const chunk of req) body += chunk;
    seen.push({ url: req.url, headers: req.headers, body: body ? JSON.parse(body) : null });
    if (req.url.endsWith("/broken-agent")) {
      res.writeHead(500, { "content-type": "application/json" });
      res.end(JSON.stringify({ detail: "Traceback: secret internal path /opt/opsi/app.py" }));
      return;
    }
    const input = JSON.parse(body);
    res.writeHead(200, { "content-type": "text/event-stream" });
    res.end(sse([
      { type: "RUN_STARTED", threadId: input.threadId, runId: input.runId },
      { type: "STATE_SNAPSHOT", snapshot: { phase: "retrieving", evidence: [] } },
      { type: "TOOL_CALL_START", toolCallId: "t1", toolCallName: "exact_logs", parentMessageId: "m1" },
      { type: "TOOL_CALL_ARGS", toolCallId: "t1", delta: "{\"query\":\"timeout\"}" },
      { type: "TOOL_CALL_END", toolCallId: "t1" },
      { type: "TOOL_CALL_RESULT", messageId: "tr1", toolCallId: "t1", content: "{\"items\":[]}", role: "tool" },
      { type: "STATE_DELTA", delta: [{ op: "replace", path: "/phase", value: "answering" }] },
      { type: "TEXT_MESSAGE_START", messageId: "m2", role: "assistant" },
      { type: "TEXT_MESSAGE_CONTENT", messageId: "m2", delta: "No timeouts found [c1]." },
      { type: "TEXT_MESSAGE_END", messageId: "m2" },
      { type: "RUN_FINISHED", threadId: input.threadId, runId: input.runId },
    ]));
  });
  await new Promise((r) => upstream.listen(0, "127.0.0.1", r));
  upstreamUrl = `http://127.0.0.1:${upstream.address().port}/api/v2/agents`;
  const cfg = loadConfig({ OPSI_AGENT_BASE_URL: upstreamUrl, OPSI_COPILOT_AGENT_IDS: "opsi-investigator,broken-agent" });
  runtime = createServer(buildNodeListener(cfg));
  await new Promise((r) => runtime.listen(0, "127.0.0.1", r));
  runtimeUrl = `http://127.0.0.1:${runtime.address().port}`;
});

after(() => {
  runtime?.close();
  upstream?.close();
});

function runInput() {
  return {
    threadId: "8f4b655f-a696-4b8d-9601-61b57fc00001", runId: "run-1", state: {}, tools: [], context: [],
    forwardedProps: {}, messages: [{ id: "u1", role: "user", content: "any timeouts?" }],
  };
}

async function run(agent, headers = {}) {
  return fetch(`${runtimeUrl}/api/copilotkit/agent/${agent}/run`, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "text/event-stream", ...headers },
    body: JSON.stringify(runInput()),
  });
}

function parse(text) {
  return text.split("\n\n").map((b) => b.trim()).filter((b) => b.startsWith("data:"))
    .map((b) => JSON.parse(b.slice(5)));
}

test("telemetry is disabled before the runtime loads", () => {
  assert.equal(process.env.COPILOTKIT_TELEMETRY_DISABLED, "true");
});

test("healthz", async () => {
  const res = await fetch(`${runtimeUrl}/healthz`);
  assert.equal(res.status, 200);
  assert.deepEqual((await res.json()).agents, ["opsi-investigator", "broken-agent"]);
});

test("run streams AG-UI events from the Python agent and forwards only allowlisted headers", async () => {
  const res = await run("opsi-investigator", {
    authorization: "Bearer user-token", cookie: "session=abc", "x-forwarded-for": "10.0.0.9", "x-internal-debug": "1",
  });
  assert.equal(res.status, 200);
  assert.match(res.headers.get("content-type"), /text\/event-stream/);
  const events = parse(await res.text());
  const types = events.map((e) => e.type);
  assert.equal(types[0], "RUN_STARTED");
  assert.equal(types.at(-1), "RUN_FINISHED");
  for (const t of ["STATE_SNAPSHOT", "STATE_DELTA", "TOOL_CALL_RESULT", "TEXT_MESSAGE_CONTENT"]) assert.ok(types.includes(t), t);
  const call = seen.at(-1);
  assert.equal(call.url, "/api/v2/agents/opsi-investigator");
  assert.equal(call.headers.authorization, "Bearer user-token");
  assert.ok(call.headers["x-request-id"], "request id added by onRequest hook");
  assert.equal(call.headers.cookie, undefined, "cookie is not forwarded unless allowlisted");
  assert.equal(call.headers["x-forwarded-for"], undefined);
  assert.equal(call.headers["x-internal-debug"], undefined);
  assert.equal(call.body.threadId, runInput().threadId);
  assert.equal(call.body.messages.at(-1).content, "any timeouts?");
});

test("requests without credentials are rejected before reaching the agent", async () => {
  const before = seen.length;
  const res = await run("opsi-investigator");
  assert.equal(res.status, 401);
  assert.equal(seen.length, before);
});

test("unknown agents and unused runtime routes are 404", async () => {
  assert.equal((await run("other-agent", { authorization: "Bearer t" })).status, 404);
  for (const path of ["threads", "memories", "transcribe", "agent/opsi-investigator/suggest"]) {
    const res = await fetch(`${runtimeUrl}/api/copilotkit/${path}`, {
      method: "POST", headers: { authorization: "Bearer t", "content-type": "application/json" }, body: "{}",
    });
    assert.ok([404, 405].includes(res.status), `${path} -> ${res.status}`);
  }
});

test("upstream failures do not leak internal details to the browser", async () => {
  const res = await run("broken-agent", { authorization: "Bearer t" });
  const text = await res.text();
  assert.ok(!text.includes("Traceback") && !text.includes("/opt/opsi"), text.slice(0, 300));
  const events = res.headers.get("content-type")?.includes("event-stream") ? parse(text) : [];
  if (events.length) assert.equal(events.at(-1).type, "RUN_ERROR");
  else assert.ok(res.status >= 400);
});

test("info lists the configured agent", async () => {
  const res = await fetch(`${runtimeUrl}/api/copilotkit/info`, { headers: { authorization: "Bearer t" } });
  assert.equal(res.status, 200);
  assert.ok(JSON.stringify(await res.json()).includes("opsi-investigator"));
});
