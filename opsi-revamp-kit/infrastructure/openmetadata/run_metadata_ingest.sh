#!/usr/bin/env bash
# Render the ingestion template with secrets from an env file and run `metadata ingest` once.
# Schedule with a systemd timer/cron (daily is plenty for schema metadata).
#
#   python3.12 -m venv /opt/om-ingest-venv && /opt/om-ingest-venv/bin/pip install "openmetadata-ingestion[postgres]==2.0.6.*"
#   (LICENSE: the openmetadata-ingestion package is distributed under the Collate Community License,
#    NOT Apache-2.0 - get legal sign-off first; see docs/license-inventory.md)
#   OM_INGEST_ENV=/etc/opsi/om-ingest.env infrastructure/openmetadata/run_metadata_ingest.sh
#
# Env file keys: OM_SERVICE_NAME OM_PG_USER OM_PG_PASSWORD OM_PG_HOSTPORT OM_PG_DATABASE OM_PG_SSLMODE
#                OM_SCHEMA_INCLUDES_JSON (e.g. ["public","opsi_chat"]) OM_API_URL OM_INGESTION_BOT_JWT OM_VERIFY_SSL
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${OM_INGEST_ENV:-/etc/opsi/om-ingest.env}"
METADATA_BIN="${METADATA_BIN:-/opt/om-ingest-venv/bin/metadata}"
[[ -r "$ENV_FILE" ]] || { echo "missing $ENV_FILE" >&2; exit 2; }
[[ -x "$METADATA_BIN" ]] || { echo "metadata CLI not found at $METADATA_BIN" >&2; exit 2; }
set -a; . "$ENV_FILE"; set +a
: "${OM_PG_SSLMODE:=require}" "${OM_VERIFY_SSL:=validate}" "${OM_SCHEMA_INCLUDES_JSON:=[\"public\"]}"
export OM_PG_SSLMODE OM_VERIFY_SSL OM_SCHEMA_INCLUDES_JSON
umask 077
RENDERED="$(mktemp --suffix=.yaml)"
trap 'rm -f "$RENDERED"' EXIT
python3 - "$HERE/opsi-postgres-metadata.template.yaml" "$RENDERED" <<'PY'
import os, string, sys
text = open(sys.argv[1], encoding="utf-8").read()
try:
    rendered = string.Template(text).substitute(os.environ)
except KeyError as exc:
    sys.exit(f"missing variable {exc} in env file")
open(sys.argv[2], "w", encoding="utf-8").write(rendered)
PY
echo "$(date -u +%FT%TZ) running metadata ingestion for ${OM_SERVICE_NAME}"
"$METADATA_BIN" ingest -c "$RENDERED"
