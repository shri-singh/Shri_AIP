#!/usr/bin/env bash
# One-shot health view of the revamp components on this host (read-only).
set -uo pipefail
check() { # name url
  code=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "$2"); [[ "$code" == 200 ]] && echo "OK    $1 ($2)" || echo "FAIL  $1 ($2) -> HTTP $code"
}
check "opsi-api revamp"      "${API_HEALTH_URL:-http://127.0.0.1:8000/api/v2/healthz}"
check "copilot-runtime"      "${RUNTIME_HEALTH_URL:-http://127.0.0.1:4000/healthz}"
check "otel-collector"       "${OTEL_HEALTH_URL:-http://127.0.0.1:13133/}"
check "openmetadata"         "${OM_HEALTH_URL:-http://127.0.0.1:8586/healthcheck}"
if [[ -x "${KIT:-/opt/opsi-revamp-kit}/.venv/bin/python" ]]; then
  echo "--- ingestion (last 6h)"
  (cd "${KIT:-/opt/opsi-revamp-kit}/services/ingestion" && WORKER_STATE_DB="${WORKER_STATE_DB:-/var/lib/opsi-ingest/state.sqlite3}" \
    ../../.venv/bin/python -m opsi_ingest status --hours 6) || echo "FAIL  ingestion has failed windows/dead letters"
fi
systemctl list-timers --no-pager 2>/dev/null | grep -E 'opsi-' || true
