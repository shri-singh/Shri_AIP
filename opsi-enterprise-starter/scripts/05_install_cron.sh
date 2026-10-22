#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[[ -x "$ROOT/.venv/bin/python" ]] || { echo 'Create venv first' >&2; exit 1; }
[[ -f "$ROOT/.env" ]] || { echo 'Provide restricted .env first' >&2; exit 1; }
mkdir -p "$ROOT/.state" "$ROOT/logs"; chmod 700 "$ROOT/.state" "$ROOT/logs"
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
crontab -l 2>/dev/null | grep -v '# OPSI-INGEST ' > "$TMP" || true
for src in elastic dynatrace_problems dynatrace_grail; do
 cat >> "$TMP" <<EOF
*/5 * * * * cd '$ROOT' && /usr/bin/flock -n '$ROOT/.state/$src.lock' '$ROOT/.venv/bin/python' -m ingestion.run_once --source '$src' >> '$ROOT/logs/$src.log' 2>&1 # OPSI-INGEST $src
EOF
done
cat "$TMP"
read -r -p 'Install these crontab entries? Type YES: ' answer
[[ "$answer" == YES ]] || exit 1
crontab "$TMP"
echo 'Installed. Ensure the collector load_dotenv() reads your env; cron has minimal environment.'
