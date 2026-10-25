#!/usr/bin/env bash
# Apply database/migrations/*.sql in order, each file in ONE transaction, recording a sha256 ledger
# in opsi_meta.schema_migrations. Refuses edited history (checksum mismatch).
#
#   MIGRATE_DATABASE_URL=postgresql://migrator@host/opsi scripts/migrate.sh status
#   MIGRATE_DATABASE_URL=...  scripts/migrate.sh apply --yes [--only 0001_roles_and_schemas.sql] [--approval CHG-1234]
#
# Safety:
#   - `apply` needs --yes; URLs that look like production also need --approval <change id>
#   - never point this at OpenMetadata's database
#   - run against a restored snapshot first (docs/runbooks.md "Migration rehearsal")
#   - optional files (0006 pgvector, 0007 OpenMetadata reader) are skipped unless --include-optional
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$ROOT/database/migrations"
URL="${MIGRATE_DATABASE_URL:?set MIGRATE_DATABASE_URL (a migrator login, member of opsi_owner after 0001)}"
CMD="${1:-status}"; shift || true
YES=0; ONLY=""; APPROVAL=""; OPTIONAL=0
while [[ $# -gt 0 ]]; do case "$1" in
  --yes) YES=1 ;; --only) ONLY="$2"; shift ;; --approval) APPROVAL="$2"; shift ;; --include-optional) OPTIONAL=1 ;;
  *) echo "unknown arg $1" >&2; exit 2 ;; esac; shift; done
PSQL=(psql "$URL" -X -v ON_ERROR_STOP=1 -q -t -A)
[[ "$URL" == *openmetadata* ]] && { echo "refusing: URL looks like the OpenMetadata database" >&2; exit 2; }

"${PSQL[@]}" -c "SELECT 1" >/dev/null
"${PSQL[@]}" -f "$DIR/0000_migration_ledger.sql" >/dev/null
sha() { sha256sum "$1" | awk '{print $1}'; }
applied_sum() { "${PSQL[@]}" -c "SELECT checksum FROM opsi_meta.schema_migrations WHERE version='$1'"; }

PENDING=()
for f in "$DIR"/[0-9][0-9][0-9][0-9]_*.sql; do
  v="$(basename "$f")"
  [[ -n "$ONLY" && "$v" != "$ONLY" ]] && continue
  [[ $OPTIONAL == 0 && "$v" == *_optional.sql && -z "$ONLY" ]] && continue
  have="$(applied_sum "$v")"
  if [[ -n "$have" ]]; then
    [[ "$have" == "$(sha "$f")" ]] && echo "applied   $v" || { echo "CHECKSUM MISMATCH $v - file changed after it was applied; stop and investigate" >&2; exit 3; }
  else
    echo "pending   $v"; PENDING+=("$f")
  fi
done
[[ "$CMD" == status ]] && exit 0
[[ "$CMD" == apply ]] || { echo "usage: $0 status|apply --yes" >&2; exit 2; }
[[ $YES == 1 ]] || { echo "add --yes to apply ${#PENDING[@]} migration(s)" >&2; exit 2; }
if [[ "$URL" =~ (prod|prd) && -z "$APPROVAL" ]]; then echo "production-looking URL: add --approval <change id>" >&2; exit 2; fi
for f in "${PENDING[@]}"; do
  v="$(basename "$f")"; s="$(sha "$f")"
  echo "applying  $v"
  "${PSQL[@]}" --single-transaction -f "$f" \
    -c "INSERT INTO opsi_meta.schema_migrations (version, checksum, notes) VALUES ('$v', '$s', '${APPROVAL//\'/}')" >/dev/null
done
echo "done"
