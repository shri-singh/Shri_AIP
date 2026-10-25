# ADR-0016: Cron for first lab runs; systemd timers for anything shared
- Status: Accepted
- Date: 2026-10-24

## Context
Collectors run every 5 minutes per source plus an index stage. Cron has a minimal environment, no overlap
protection (needs `flock`), no resource limits, weak logging. systemd gives journald logging, `OnFailure=`
hooks, sandboxing, memory/CPU limits and non-overlapping oneshot units.

## Decision
- Lab: `infrastructure/cron/opsi-ingest-run.sh` (flock, env file, logrotate).
- Shared/prod: `infrastructure/systemd/opsi-collect@.service/.timer`, `opsi-index.*`, `opsi-ingest-status.*`
  (daily completeness), `opsi-notify@.service` (journal tag `opsi-alert`, optional SNS), hardening directives.
- Later: an orchestrator (Step Functions / Airflow / MWAA) only when cross-job dependencies justify it.

## Verification
`systemctl list-timers | grep opsi`; `journalctl -t opsi-alert`; units pass `systemd-analyze verify` on the host.
