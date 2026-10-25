#!/usr/bin/env python3
"""End-to-end bridge smoke: CopilotKit V2 runtime (Node) <-> FastAPI AG-UI agent (Python).

Starts the FastAPI *lab* app (in-memory stores, scripted model, dev auth) and the built
copilot-runtime on loopback ports, sends the same request a browser's CopilotKitProvider
sends (POST /api/copilotkit/agent/opsi-investigator/run), and validates every streamed
event against the AG-UI schema plus the lifecycle rules. Then restores the thread via
the chat API (the "log out / log in" step).

Usage (from the kit root, venv active, runtime built with `npm ci && npm run build`):
    python tests/e2e/bridge_smoke.py --runtime-dir apps/copilot-runtime
Exit code 0 = pass. Nothing leaves 127.0.0.1.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_http(url: str, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:  # noqa: S310 - loopback only
                if r.status < 500:
                    return
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    raise SystemExit(f"timed out waiting for {url}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime-dir", default=str(ROOT / "apps" / "copilot-runtime"))
    args = ap.parse_args()
    sys.path.insert(0, str(ROOT / "apps" / "opsi-api"))
    from ag_ui.core import Event
    from pydantic import TypeAdapter

    validator = TypeAdapter(Event)
    api_port, rt_port = free_port(), free_port()
    env = {**os.environ, "OPSI_ENV": "lab", "OPSI_AUTH_MODE": "dev", "OPSI_DEV_USER": "e2e-user",
           "OPSI_DEFAULT_TENANT_ID": "lab-tenant", "PYTHONPATH": str(ROOT / "apps" / "opsi-api")}
    api = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main_example:lab_app", "--factory",
                            "--host", "127.0.0.1", "--port", str(api_port), "--log-level", "warning"],
                           cwd=ROOT / "apps" / "opsi-api", env=env)
    rt_env = {**os.environ, "RUNTIME_PORT": str(rt_port),
              "OPSI_AGENT_BASE_URL": f"http://127.0.0.1:{api_port}/api/v2/agents"}
    runtime = subprocess.Popen(["node", "dist/main.js"], cwd=args.runtime_dir, env=rt_env)
    try:
        wait_http(f"http://127.0.0.1:{api_port}/api/v2/healthz")
        wait_http(f"http://127.0.0.1:{rt_port}/healthz")
        thread_id = str(uuid.uuid4())
        body = {"threadId": thread_id, "runId": f"run-{uuid.uuid4().hex[:8]}", "state": {}, "tools": [],
                "context": [{"description": "opsi.ui_context", "value": json.dumps({"page": "incident"})}],
                "forwardedProps": {}, "messages": [{"id": "u1", "role": "user", "content": "Why is payments failing?"}]}
        req = urllib.request.Request(
            f"http://127.0.0.1:{rt_port}/api/copilotkit/agent/opsi-investigator/run", data=json.dumps(body).encode(),
            headers={"content-type": "application/json", "accept": "text/event-stream",
                     "authorization": "Bearer lab-token"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            assert resp.status == 200, resp.status
            raw = resp.read().decode()
        events = []
        for block in raw.split("\n\n"):
            block = block.strip()
            if block.startswith("data:"):
                payload = json.loads(block[5:])
                validator.validate_python(payload)
                events.append(payload)
        kinds = [e["type"] for e in events]
        print("events:", " ".join(kinds))
        assert kinds[0] == "RUN_STARTED" and kinds[-1] == "RUN_FINISHED", kinds
        for needed in ("STATE_SNAPSHOT", "TOOL_CALL_START", "TOOL_CALL_RESULT", "TEXT_MESSAGE_CONTENT"):
            assert needed in kinds, f"missing {needed}"
        text = "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")
        assert "[c1]" in text, text
        # "log out / log in": restore the thread through the REST API
        with urllib.request.urlopen(f"http://127.0.0.1:{api_port}/api/v2/chat/threads/{thread_id}/messages",
                                    timeout=10) as r:  # noqa: S310
            restored = json.loads(r.read())
        roles = [m["role"] for m in restored["messages"]]
        assert roles == ["user", "assistant", "tool", "assistant"], roles
        assert restored["evidence"] and restored["evidence"][0]["citation_key"] == "c1"
        print("BRIDGE SMOKE PASSED: runtime -> FastAPI AG-UI -> runtime -> client; thread restored with citations")
        return 0
    finally:
        for proc in (runtime, api):
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
