# Infrastructure

| Folder | Content | Docs |
|---|---|---|
| `compose/` | OpenMetadata lab override + env example, OpenMetadata prod-reviewed template, revamp side-car stack | [compose/README.md](compose/README.md) |
| `nginx/` | `opsi-revamp.locations.conf` (SSE-safe runtime proxy, API, agent endpoint denied) | cheatsheets/nginx.md |
| `systemd/` | collector/index/status timers, notify hook, runtime unit | cheatsheets/systemd-cron.md |
| `cron/` | lab wrapper with flock, crontab example, logrotate | runbooks |
| `aws/` | IAM policies, S3 bucket policy + lifecycle, KMS key policy | [aws/README.md](aws/README.md) |
| `opensearch/` | `opsi-incidents` index template (strict mapping) | ADR-0012 |
| `openmetadata/` | metadata-only ingestion template + runner | [openmetadata/README.md](openmetadata/README.md) |

Validation performed while building the kit: `docker compose config` + `scripts/check_port_exposure.py` for all compose
stacks, `otelcol-contrib validate` for collector configs, `nginx -t` for the NGINX snippet, JSON validity for AWS policies.
Not validated here (needs the host): `systemd-analyze verify`, IAM Access Analyzer, real AWS application of policies.
