# Compose stacks

Always go through `scripts/compose_safe.sh <stack> <config|up|ps|logs|down|pull>` - it renders the merged config and
**fails closed** if any port would bind beyond 127.0.0.1 (Docker-published ports bypass host firewalls).

| Stack | Files | Env file | Notes |
|---|---|---|---|
| `openmetadata-lab` | upstream `docker/development/docker-compose-postgres.yml` (set `OM_DEV_COMPOSE`) + `openmetadata.lab-override.yml` | `.openmetadata-lab.env` (from `openmetadata.lab.env.example`) | lab only; requires `I_ACCEPT_LAB_ONLY=YES` for `up`; source build is heavy |
| `openmetadata` | `openmetadata.prod-reviewed.example.yml` | `/etc/opsi/openmetadata.env` | release images, external RDS + OpenSearch, SSO; run the `migrate` profile before `up` |
| `opsi-revamp` | `opsi-revamp.compose.yml` | `/etc/opsi/revamp.env` | copilot-runtime (host network, loopback) + otel-collector |

Why the override uses `!reset` / `!override`: Compose **appends** `ports:` from override files; without the tags the
upstream `0.0.0.0` bindings (5432, 9200, 9300, 5005 JDWP, 8080, 8585, 8586) would remain. Requires Compose >= 2.24.
Verified 2026-10-24 with Compose v5.3.1: upstream file alone -> 7 exposures flagged; with override -> loopback only.

The upstream dev file also hard-codes `container_name`s: only one OpenMetadata dev stack can run per Docker host.
