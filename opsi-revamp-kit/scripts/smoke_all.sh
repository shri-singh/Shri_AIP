#!/usr/bin/env bash
# Run every LOCAL check the kit has, report pass/fail/skip per step. No network, no AWS, no real DB.
# Usage (kit root, venv active):  scripts/smoke_all.sh
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"
PY="${PYTHON:-python3}"
declare -a RESULTS
step() { # name, command...
  local name="$1"; shift
  if "$@" > "/tmp/opsi-smoke-$$.log" 2>&1; then RESULTS+=("PASS  $name"); else RESULTS+=("FAIL  $name (see output above)"); tail -30 "/tmp/opsi-smoke-$$.log"; fi
}
skip() { RESULTS+=("SKIP  $1 ($2)"); }

step "python unit tests (ingestion + api)" "$PY" -m pytest -q
step "redaction copies in sync" "$PY" scripts/sync_redaction.py --check
if "$PY" -m ruff --version >/dev/null 2>&1; then step "ruff lint" "$PY" -m ruff check services apps/opsi-api tests tools scripts; else skip "ruff lint" "pip install ruff"; fi
step "shell syntax" bash -c 'for f in scripts/*.sh scripts/phase0/*.sh infrastructure/cron/*.sh infrastructure/openmetadata/*.sh; do bash -n "$f" || exit 1; done'
step "secret scan (tracked files)" "$PY" scripts/secret_scan.py
if [[ -d database/validate/node_modules ]]; then step "SQL migrations on PGlite (RLS checks)" node database/validate/validate_migrations.mjs; else skip "SQL migrations on PGlite" "cd database/validate && npm ci"; fi
if [[ -f apps/copilot-runtime/dist/server.js ]]; then step "copilot-runtime bridge tests" bash -c 'cd apps/copilot-runtime && node --test "test/*.test.mjs"'; else skip "copilot-runtime tests" "cd apps/copilot-runtime && npm ci && npm run build"; fi
if [[ -d apps/opsi-web/node_modules ]]; then
  step "web features typecheck (V2)" bash -c 'cd apps/opsi-web && npx tsc -p tsconfig.json --noEmit'
  step "CopilotKit V2-only scan" bash -c 'cd apps/opsi-web && node scripts/verify-copilotkit-v2.mjs src'
else skip "web typecheck" "cd apps/opsi-web && npm ci"; fi
if [[ -f apps/copilot-runtime/dist/main.js ]] && "$PY" -c "import uvicorn" 2>/dev/null; then
  step "E2E bridge smoke (runtime <-> FastAPI)" "$PY" tests/e2e/bridge_smoke.py
else skip "E2E bridge smoke" "needs built runtime + uvicorn"; fi
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
  step "compose: opsi-revamp config + port check" bash -c 'touch /tmp/opsi-empty.env; docker compose -p t --env-file /tmp/opsi-empty.env -f infrastructure/compose/opsi-revamp.compose.yml config --format json | python3 scripts/check_port_exposure.py --allow-host-network copilot-runtime'
else skip "compose checks" "docker compose not installed"; fi
rm -f "/tmp/opsi-smoke-$$.log"
echo; printf '%s\n' "${RESULTS[@]}"
! printf '%s\n' "${RESULTS[@]}" | grep -q '^FAIL'
