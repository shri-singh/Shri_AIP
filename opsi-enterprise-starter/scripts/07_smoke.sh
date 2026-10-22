#!/usr/bin/env bash
set -euo pipefail
python3 -m compileall -q ingestion backend || true
for f in scripts/*.sh; do bash -n "$f"; done
if [[ -n "${OPSI_ARCHIVE_BUCKET:-}" ]]; then aws s3 ls "s3://$OPSI_ARCHIVE_BUCKET/" | head; fi
if command -v docker >/dev/null; then docker compose -f compose/otel-lab.yml config >/dev/null; fi
printf 'Static smoke passed. Live source/API validation remains mandatory.\n'
