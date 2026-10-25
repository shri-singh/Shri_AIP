#!/usr/bin/env bash
# Safe wrapper for the kit's Compose projects: always renders + checks the merged config first,
# and refuses `up` if anything would be published beyond 127.0.0.1.
#
# Usage: scripts/compose_safe.sh <stack> <config|up|ps|logs|down|pull>
#   stacks:
#     openmetadata-lab   upstream dev compose + infrastructure/compose/openmetadata.lab-override.yml
#                        needs OM_DEV_COMPOSE (path to vendor/OpenMetadata/docker/development/docker-compose-postgres.yml)
#                        and env file .openmetadata-lab.env
#     openmetadata       infrastructure/compose/openmetadata.prod-reviewed.example.yml (+ /etc/opsi/openmetadata.env)
#     opsi-revamp        infrastructure/compose/opsi-revamp.compose.yml (+ /etc/opsi/revamp.env)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STACK="${1:-}"; ACTION="${2:-}"
[[ "$ACTION" =~ ^(config|up|ps|logs|down|pull)$ ]] || { echo "usage: $0 <stack> config|up|ps|logs|down|pull" >&2; exit 2; }
command -v docker >/dev/null || { echo "docker CLI not found" >&2; exit 2; }
docker compose version >/dev/null 2>&1 || { echo "docker compose v2 plugin required (not legacy docker-compose)" >&2; exit 2; }

ALLOW_HOST=()
case "$STACK" in
  openmetadata-lab)
    : "${OM_DEV_COMPOSE:?set OM_DEV_COMPOSE to vendor/OpenMetadata/docker/development/docker-compose-postgres.yml}"
    ENV_FILE="${OM_LAB_ENV_FILE:-$ROOT/.openmetadata-lab.env}"
    FILES=(-f "$OM_DEV_COMPOSE" -f "$ROOT/infrastructure/compose/openmetadata.lab-override.yml")
    PROJECT=opsi-om-lab ;;
  openmetadata)
    ENV_FILE="${OM_ENV_FILE:-/etc/opsi/openmetadata.env}"
    FILES=(-f "$ROOT/infrastructure/compose/openmetadata.prod-reviewed.example.yml")
    PROJECT=opsi-openmetadata ;;
  opsi-revamp)
    ENV_FILE="${REVAMP_ENV_FILE:-/etc/opsi/revamp.env}"
    FILES=(-f "$ROOT/infrastructure/compose/opsi-revamp.compose.yml")
    PROJECT=opsi-revamp
    ALLOW_HOST=(--allow-host-network copilot-runtime) ;;
  *) echo "unknown stack '$STACK'" >&2; exit 2 ;;
esac
[[ -f "$ENV_FILE" ]] || { echo "env file $ENV_FILE missing (copy the matching *.env.example, chmod 600)" >&2; exit 2; }
perm=$(stat -c '%a' "$ENV_FILE" 2>/dev/null || echo 600)
[[ "$perm" =~ ^[0-7]00$ ]] || echo "WARNING: $ENV_FILE is mode $perm; run chmod 600" >&2

DC=(docker compose -p "$PROJECT" --env-file "$ENV_FILE" "${FILES[@]}")
MERGED="$(mktemp)"; trap 'rm -f "$MERGED"' EXIT
"${DC[@]}" config --format json > "$MERGED"
python3 "$ROOT/scripts/check_port_exposure.py" "$MERGED" "${ALLOW_HOST[@]}"

case "$ACTION" in
  config) "${DC[@]}" config --services; echo "config OK for $PROJECT" ;;
  up)
    if [[ "$STACK" == openmetadata-lab && "${I_ACCEPT_LAB_ONLY:-}" != YES ]]; then
      echo "Lab stack: OpenSearch security is disabled inside the docker network and images build from source." >&2
      echo "Confirm the host is an isolated lab, then re-run with I_ACCEPT_LAB_ONLY=YES" >&2; exit 3
    fi
    "${DC[@]}" up -d ;;
  ps) "${DC[@]}" ps ;;
  logs) "${DC[@]}" logs --tail "${TAIL:-200}" ;;
  pull) "${DC[@]}" pull ;;
  down) "${DC[@]}" down ;;   # volumes are kept; add -v manually only if you mean to delete data
esac
