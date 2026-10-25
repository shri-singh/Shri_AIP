#!/usr/bin/env bash
# Cron wrapper (use systemd timers in production; this is the simple first step).
# Crontab (crontab -e as the opsi-ingest user), see crontab.example:
#   */5 * * * * /opt/opsi-revamp-kit/infrastructure/cron/opsi-ingest-run.sh collect elastic
#   2-59/5 * * * * /opt/opsi-revamp-kit/infrastructure/cron/opsi-ingest-run.sh index
# - flock prevents overlapping runs of the same job (cron does not)
# - cron has a minimal environment: everything comes from the env file
# - output goes to a per-job log; rotate it with logrotate.opsi-ingest
set -euo pipefail
KIT="${OPSI_KIT_DIR:-/opt/opsi-revamp-kit}"
ENV_FILE="${OPSI_ENV_FILE:-/etc/opsi/ingest.env}"
LOG_DIR="${OPSI_LOG_DIR:-/var/log/opsi-ingest}"
STATE_DIR="${OPSI_STATE_DIR:-/var/lib/opsi-ingest}"
JOB="${1:?usage: $0 collect <source> | index | status}"
SOURCE="${2:-}"
mkdir -p "$LOG_DIR" "$STATE_DIR"
[[ -r "$ENV_FILE" ]] || { echo "$(date -u +%FT%TZ) missing $ENV_FILE" >> "$LOG_DIR/wrapper.log"; exit 2; }
set -a; . "$ENV_FILE"; set +a
export WORKER_STATE_DB="$STATE_DIR/state.sqlite3" PYTHONUNBUFFERED=1
LOCK="$STATE_DIR/${JOB}${SOURCE:+-$SOURCE}.lock"
LOG="$LOG_DIR/${JOB}${SOURCE:+-$SOURCE}.log"
cd "$KIT/services/ingestion"
case "$JOB" in
  collect) ARGS=(collect --source "${SOURCE:?source required}") ;;
  index) ARGS=(index --limit 100) ;;
  status) ARGS=(status --hours 26) ;;
  *) echo "unknown job $JOB" >&2; exit 2 ;;
esac
exec /usr/bin/flock -n "$LOCK" "$KIT/.venv/bin/python" -m opsi_ingest "${ARGS[@]}" >> "$LOG" 2>&1
