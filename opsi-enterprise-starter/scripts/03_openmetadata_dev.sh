#!/usr/bin/env bash
# Lab-only. Uses OpenMetadata's OWN dev compose with PostgreSQL + OpenSearch.
set -euo pipefail
F='vendor/OpenMetadata/docker/development/docker-compose-postgres.yml'
[[ -f "$F" ]] || { echo "Missing $F; run scripts/02_fetch_upstreams.sh"; exit 1; }
[[ "${1:-}" =~ ^(config|up|ps|logs|down)$ ]] || { echo 'Usage: script config|up|ps|logs|down'; exit 2; }
echo 'WARNING: upstream DEV compose may expose database/OpenSearch and disable security. Only approved isolated lab.'
if [[ "${1}" == up && "${I_ACCEPT_INSECURE_LAB_COMPOSE:-}" != YES ]]; then
 echo 'Set I_ACCEPT_INSECURE_LAB_COMPOSE=YES after inspecting compose/security groups.' >&2; exit 3
fi
if [[ "${1}" == up ]]; then
 docker compose -p opsi-om-dev -f "$F" up -d --build
elif [[ "${1}" == logs ]]; then
 docker compose -p opsi-om-dev -f "$F" logs --tail 100
else
 docker compose -p opsi-om-dev -f "$F" "$1"
fi
