#!/usr/bin/env bash
# Application DB logical export, not snapshot backup of multi-TB cluster.
set -euo pipefail
: "${OPSI_ARCHIVE_BUCKET:?bucket required}"
: "${PG_DUMP_DATABASE:?set PG_DUMP_DATABASE (name/URI/pg_service compatible)}"
: "${PG_DUMP_SCHEMA:=opsi_chat}"
TMP="$(mktemp --suffix=.dump)"; trap 'rm -f "$TMP"' EXIT
chmod 600 "$TMP"
pg_dump --format=custom --no-owner --schema="$PG_DUMP_SCHEMA" --file="$TMP" "$PG_DUMP_DATABASE"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
aws s3 cp "$TMP" "s3://$OPSI_ARCHIVE_BUCKET/db-logical/$PG_DUMP_SCHEMA/$STAMP.dump" --sse AES256
printf 'Dump uploaded. Validate restore to an ISOLATED DB; this is not RDS PITR.\n'
