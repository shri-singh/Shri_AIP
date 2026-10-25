#!/usr/bin/env bash
# Logical backup + restore DRILL for the revamp schemas (small, app-owned data only).
# This is NOT the backup of the multi-TB Opsi database - that is RDS/Aurora snapshots + PITR
# (docs/runbooks.md "Backups"). The drill proves the logical export of opsi_chat/opsi_knowledge/opsi_ingest
# can be restored and is complete (row counts match).
#
#   SOURCE_DATABASE_URL=... DRILL_DATABASE_URL=postgresql://.../opsi_restore_drill scripts/backup_restore_drill.sh
#   optional: ARCHIVE_BUCKET=... to also upload the dump (SSE-KMS) under db-logical/
set -euo pipefail
: "${SOURCE_DATABASE_URL:?}" "${DRILL_DATABASE_URL:?must be a scratch database whose name contains 'drill'}"
[[ "$DRILL_DATABASE_URL" == *drill* ]] || { echo "refusing: DRILL_DATABASE_URL must point at a database named *drill*" >&2; exit 2; }
[[ "$DRILL_DATABASE_URL" != "$SOURCE_DATABASE_URL" ]] || { echo "refusing: drill target equals source" >&2; exit 2; }
SCHEMAS=(opsi_meta opsi_chat opsi_knowledge opsi_ingest opsi_audit)
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
umask 077
DUMP="$(mktemp --suffix=.dump)"; trap 'rm -f "$DUMP"' EXIT
ARGS=(); for s in "${SCHEMAS[@]}"; do ARGS+=(--schema="$s"); done
echo "[$STAMP] dumping ${SCHEMAS[*]}"
pg_dump --format=custom --no-owner --no-privileges "${ARGS[@]}" --file="$DUMP" "$SOURCE_DATABASE_URL"
echo "restoring into drill database"
pg_restore --no-owner --no-privileges --clean --if-exists --exit-on-error -d "$DRILL_DATABASE_URL" "$DUMP"
count_sql="SELECT n.nspname||'.'||c.relname, c.reltuples::bigint FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind='r' AND n.nspname = ANY('{${SCHEMAS[*]// /,}}') ORDER BY 1"
exact() { # url -> "table count" lines using exact counts (fine for these small schemas)
  psql "$1" -X -q -t -A -F' ' -c "$count_sql" | while read -r t _; do
    echo "$t $(psql "$1" -X -q -t -A -c "SET row_security = off; SELECT count(*) FROM $t" 2>/dev/null || echo ERR)"
  done
}
diff <(exact "$SOURCE_DATABASE_URL") <(exact "$DRILL_DATABASE_URL") && echo "DRILL PASSED: row counts match" || { echo "DRILL FAILED: counts differ (writes during the dump are expected to cause small drift - rerun in a quiet window)"; exit 1; }
if [[ -n "${ARCHIVE_BUCKET:-}" ]]; then
  aws s3 cp "$DUMP" "s3://$ARCHIVE_BUCKET/db-logical/revamp-schemas/$STAMP.dump" --sse aws:kms ${KMS_KEY_ID:+--sse-kms-key-id "$KMS_KEY_ID"}
fi
echo "Record the drill (date, source snapshot, duration, result) in docs/runbooks.md evidence table."
