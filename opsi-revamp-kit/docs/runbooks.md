# Operator runbook

Every procedure: **when**, **check**, **do**, **verify**, **roll back**. Commands assume the kit at
`/opt/opsi-revamp-kit`, venv at `.venv`, collectors managed by systemd. For cron setups replace
`systemctl` with the cron wrapper. Record every manual intervention (who/when/why) in your ticket.

Contents: [Daily checks](#daily-checks) · [Start/stop](#startstop) · [Collectors](#collectors) ·
[Failed window](#a-window-failed) · [Dead letters](#dead-lettered-index-items) · [Skip a window](#skip-a-window) ·
[Reset a watermark](#reset-watermark) · [Backfill](#backfill-a-time-range) · [Changing the window size](#changing-the-window-size) ·
[Agent/chat issues](#agent-and-chat) · [Rotate a credential](#rotate-a-credential) · [Backups](#backups) ·
[Restore drill](#restore-drill) · [Migrations](#migration-rehearsal-and-apply) · [OpenMetadata](#openmetadata-operations) ·
[Dependency upgrades](#dependency-upgrades) · [Rollback](#rollback) · [Platform incident response](#platform-incident-response) ·
[Monitoring & alerts](#monitoring-and-alerts) · [Evidence log](#evidence-log)

## Daily checks
```bash
scripts/health.sh                                   # API, runtime, collector, OpenMetadata, ingestion status
journalctl -t opsi-alert --since yesterday          # any OnFailure alerts
cd services/ingestion && ../../.venv/bin/python -m opsi_ingest status --hours 26
```
Healthy = all OK, no FAILED windows, no GAP lines, outbox has no `dead`.

## Start/stop
| Component | Start | Stop | Logs |
|---|---|---|---|
| collectors | `sudo systemctl start opsi-collect@elastic.timer` (and `dynatrace_problems`, `dynatrace_grail`, `opsi-index.timer`) | `sudo systemctl stop 'opsi-collect@*.timer' opsi-index.timer` | `journalctl -u opsi-collect@elastic -n 100` |
| runtime | `sudo systemctl start opsi-copilot-runtime` | `... stop ...` | `journalctl -u opsi-copilot-runtime -f` |
| compose stack | `scripts/compose_safe.sh opsi-revamp up` | `... down` | `scripts/compose_safe.sh opsi-revamp logs` |
| OpenMetadata | `scripts/compose_safe.sh openmetadata up` | `... down` (volumes kept) | `... logs` |
Stopping collectors is always safe: on restart they resume from the watermark (no data loss within source retention).

## Collectors

### First run of a source (or after changing its config)
```bash
cd /opt/opsi-revamp-kit/services/ingestion
set -a; . /etc/opsi/ingest.env; set +a
../../.venv/bin/python -m opsi_ingest check-config --source dynatrace_grail      # no network
../../.venv/bin/python -m opsi_ingest collect --source dynatrace_grail --dry-run # 1 window, writes nothing
```
Check in the dry-run JSON: `ok: true`, plausible `records`, `quarantined` small, `dry_run_objects` keys look right.
Then enable the timer: `sudo systemctl enable --now opsi-collect@dynatrace_grail.timer`.

### A window failed
**Check**: `python -m opsi_ingest status --hours 6` shows `FAILED <window> attempts=N: <error>`.
**Interpret** the error prefix:
| Error | Meaning | Do |
|---|---|---|
| `PermanentSourceError: HTTP 401` | token expired/wrong type | Grail: check OAuth client id/secret; Problems: classic `Api-Token`; rotate (below) |
| `HTTP 403` | missing scope/permission | Grail: `storage:logs:read` + bucket permissions; Elastic: `read` + `view_index_metadata` |
| `HTTP 400 ... compatible-with` | Elastic client major != cluster major | pin `elasticsearch` to the cluster major |
| `TransientSourceError` | network/429/5xx after retries | usually self-heals next run; if persistent check egress/proxy |
| `WindowTooLarge ... minimum split` | even 30 s holds more than the cap | narrow the source filter (DQL / `ELASTIC_QUERY_FILTER_JSON`) or raise the cap |
| `ConnectionError` / S3 `AccessDenied` | archive write failed | IAM/KMS/bucket policy (`DenyPutsWithoutKms`?) |
| `grail query ended with state=FAILED` | DQL error or quota | run the DQL in a Dynatrace notebook with the same timeframe |
**Do**: fix the cause; the next scheduled run retries the same window automatically (watermark is held).
**Verify**: `status` shows the window `bronze_committed`, `committed_until` advancing.

### Dead-lettered index items
**Check**: `status` -> `outbox: {'dead': N}`. Cause is in `last_error` (`sqlite3 /var/lib/opsi-ingest/state.sqlite3
"select window_start, last_error from outbox where status='dead'"`).
**Do**: fix the DB/OpenSearch issue, then
```bash
python -m opsi_ingest requeue-dead --actor "$USER" --reason "PG restored after maintenance, CHG-123"
```
**Verify**: next `opsi-index` run processes them (`outbox: {'done': ...}`). Bronze is untouched throughout.

### Skip a window
Only when the data is irrecoverable (source retention expired, index deleted) and the owner accepts the gap.
```bash
python -m opsi_ingest skip-window --source elastic --window-start 2026-10-24T10:05:00Z \
  --actor "$USER" --reason "Source index deleted by ILM before collection; approved by <owner> CHG-456"
```
The action is written to `operator_actions`. Document the gap in the incident/ticket.

### Reset watermark
Dangerous: moving it backwards re-collects (duplicates are absorbed downstream by `event_uid`, but costs time
and quota); moving it forwards **creates a gap**. Must be on the grid.
```bash
python -m opsi_ingest reset-watermark --source elastic --to 2026-10-24T00:00:00Z --actor "$USER" \
  --reason "re-collect after field-map fix, CHG-789" --yes
```

### Backfill a time range
```bash
python -m opsi_ingest backfill --source dynatrace_problems --from 2026-10-01T00:00:00Z --to 2026-10-02T00:00:00Z --dry-run
python -m opsi_ingest backfill --source dynatrace_problems --from 2026-10-01T00:00:00Z --to 2026-10-02T00:00:00Z
```
Backfills write ledger rows but do not move the watermark unless contiguous with it. Mind vendor rate limits;
run large backfills in day-sized chunks outside business hours; Grail scans cost money (`DYNATRACE_GRAIL_SCAN_LIMIT_GBYTES`).

### Changing the window size
Watermarks must sit on the grid. Changing `INGEST_WINDOW_MINUTES` from 5 to 10 works only if the current
`committed_until` is a multiple of 10 minutes; otherwise the planner refuses ("not on the window grid").
Procedure: stop the timer, wait until `committed_until` is on the new grid (or reset it to the nearest earlier
grid point - re-collects a few minutes), change the setting, start the timer.

## Agent and chat

| Symptom | Check | Fix |
|---|---|---|
| Chat spinner never ends | browser dev tools: `/api/copilotkit/...run` response streaming? | NGINX `proxy_buffering off`, `X-Accel-Buffering: no`, timeouts >= 300 s |
| 401 from runtime | request has `Authorization`/cookie? | provider `headers` builder must return the token; cookie auth -> add `cookie` to `RUNTIME_FORWARD_HEADERS` and `RUNTIME_REQUIRE_AUTH_HEADERS` |
| 401/403 from FastAPI agent | `journalctl` API logs | token audience/issuer; group->role mapping (`OPSI_GROUP_ROLE_MAP_JSON`) |
| `RUN_ERROR llm_unavailable` | Portkey dashboard / logs | key, provider slug, model id, Bedrock access, quotas |
| Answers without citations | tool results empty? | check route config (Elastic URL, tenant index map, OM token) |
| "client-supplied message(s) ignored" warnings | normal after UI bugs or old transcripts | investigate only if frequent (possible tampering) - see audit `agent.client_messages_ignored` |
| Thread missing after login | `GET /api/v2/chat/threads` as the user | same `sub`/tenant claim as before? (claim change = new identity) |

## Rotate a credential
| Credential | Where used | Rotate |
|---|---|---|
| Dynatrace OAuth client secret | collectors (Grail) | create new secret in Dynatrace Account Mgmt -> update Secrets Manager -> re-render `/etc/opsi/ingest.env` -> next run uses it -> revoke old |
| Dynatrace API token (Problems) | collectors | same pattern; scope `problems.read` only |
| Elastic API keys (collector, API search) | collectors, API | create new key with same role, swap, `invalidate` old key |
| OpenMetadata bot token | API, metadata CLI | revoke/regenerate in OM Settings -> Bots; update secrets |
| Portkey API key | API, kb tool | rotate in Portkey; update; restart API |
| OTLP export token | collector | rotate in backend; update env; `docker compose restart otel-collector` |
| DB passwords | all | prefer IAM auth or Secrets Manager rotation; restart pools |
Verify each rotation with the component's health check and one real request; record in the evidence log.

## Backups
- **Opsi PostgreSQL (incl. revamp schemas)**: RDS/Aurora automated backups + PITR (retention per policy),
  AWS Backup plan with vault lock / cross-account copy as required. *This is the backup.*
- **Logical export of revamp schemas** (supplement, e.g. before risky migrations):
  `scripts/backup_restore_drill.sh` (dump + restore into a `*drill*` DB + row-count comparison).
- **S3 bronze**: versioning + lifecycle; optional replication/Object Lock. Bronze is an archive, not a DB backup.
- **Collector state (SQLite)**: `sqlite3 state.sqlite3 ".backup /var/backups/opsi-state-$(date +%F).sqlite3"` daily;
  if lost, rebuild by resetting watermarks to the last known committed point (duplicates absorbed by `event_uid`).
- **OpenMetadata DB**: RDS snapshots before every upgrade (2.0 migrations are not reversible).
- RDS "export snapshot to S3" produces Parquet for analytics - **not restorable** as a database.

## Restore drill
Quarterly, per environment; record results in the evidence log.
```bash
# 1) RDS: restore snapshot to a NEW instance (never overwrite prod)
aws rds restore-db-instance-from-db-snapshot --db-instance-identifier opsi-restore-drill-$(date +%Y%m%d) \
  --db-snapshot-identifier <snapshot-id> --db-subnet-group-name <subnet-group> --vpc-security-group-ids <sg> --no-publicly-accessible
# 2) or PITR:
aws rds restore-db-instance-to-point-in-time --source-db-instance-identifier <prod-id> \
  --target-db-instance-identifier opsi-pitr-drill-$(date +%Y%m%d) --restore-time 2026-10-24T09:00:00Z --no-publicly-accessible
# 3) verify: migrations ledger, row counts, RLS still enforced
MIGRATE_DATABASE_URL=<drill-url> scripts/migrate.sh status
# 4) delete the drill instance when done (it costs money)
```

## Migration rehearsal and apply
1. Restore a recent snapshot (above) -> `MIGRATE_DATABASE_URL=<drill> scripts/migrate.sh status` -> `apply --yes`.
2. Measure duration and locks (`pg_stat_activity`, `pg_locks`); all revamp DDL creates new objects (low lock risk).
3. Staging -> production in a change window: `scripts/migrate.sh apply --yes --approval CHG-xxxx`.
4. Rollback: `database/migrations/rollback/000N_down.sql` in reverse order **after a snapshot**, with
   `SET opsi.allow_destructive = 'yes';` (scripts refuse otherwise). 0003_down deletes chat history - export first.

## OpenMetadata operations
- Health: `curl -s http://127.0.0.1:8586/healthcheck`; version: `curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8585/api/v1/system/version`.
- Upgrade: read release notes + breaking changes -> snapshot OM DB -> pull new image tags -> `run --rm migrate` ->
  `up -d` -> reindex from Settings if required -> re-run `infrastructure/openmetadata/run_metadata_ingest.sh`.
  No automated downgrade in 2.x: rollback = restore snapshot + previous image tag.
- Metadata ingestion failures: run the script manually; read the CLI summary (failed entities, permission errors on schemas).

## Dependency upgrades
1. Read changelogs (CopilotKit, AG-UI, OpenMetadata, Portkey SDK, FastAPI, pyarrow, elasticsearch-py).
2. Bump one family per branch; for CopilotKit bump `@copilotkit/*` together and set `@ag-ui/client` to the runtime's
   dependency (`npm view @copilotkit/runtime@<v> dependencies`).
3. `make test runtime web e2e validate-sql`, `npm run check:exports`, `node scripts/verify-copilotkit-v2.mjs src`.
4. Update `docs/verified-facts.md` and pins; commit with the evidence.

## Rollback
| Change | Roll back by |
|---|---|
| React provider / chat UI | feature flag off (or revert the provider commit); NGINX location can stay |
| copilot-runtime | `systemctl stop opsi-copilot-runtime`; remove NGINX location include; reload NGINX |
| API modules | feature flag in `install_revamp` call; revert commit; restart API |
| Collectors | stop timers; bronze data stays; no impact on Opsi |
| Migrations | see "Migration rehearsal and apply" (snapshot first; down scripts are guarded) |
| OpenMetadata | separate stack: `compose_safe.sh openmetadata down`; restore DB snapshot if migrated |
| Bucket policy | `put-bucket-policy` with the saved previous policy (infrastructure/aws/README.md) |

## Platform incident response
If you suspect data exposure (wrong tenant data shown, secrets in logs/traces/prompts):
1. Contain: disable the chat feature flag / stop the runtime; stop collectors if bronze is affected.
2. Preserve: export relevant `opsi_audit.events`, API/runtime journal logs, S3 access logs; do not delete data.
3. Notify security per corporate procedure; rotate any exposed credential (table above).
4. Fix + add a regression test (e.g. new redaction pattern in `redaction.py` + test) before re-enabling.

## Monitoring and alerts
| Signal | Source | Alert |
|---|---|---|
| unit failures | `journalctl -t opsi-alert` -> CloudWatch/SIEM | any |
| ingestion completeness | `opsi-ingest-status.timer` (exit 1 on failed windows/gaps/dead letters) | any failure |
| curated freshness | SQL `select now() - max(window_end) from opsi_ingest.error_signature_windows` | > 30 min |
| runtime errors | runtime JSON logs `runtime_error`, `agent_http_error` | rate > baseline |
| agent errors | `opsi_chat.agent_runs` status=error / `RUN_ERROR` codes | rate > 5 % |
| LLM latency/tokens | spans `chat <model>` (`gen_ai.usage.*`) | p95 > budget |
| attachment scans | `attachments.status in ('infected','scan_error')` | any infected |
| certificate/credential expiry | calendar + secret metadata | 14 days before |

## Evidence log
Keep a table in your ticket system or `docs/evidence/` (not in this public kit):

| Date | Environment | Procedure | Result | Operator | Link |
|---|---|---|---|---|---|
| | | restore drill / rotation / migration / upgrade | pass/fail + numbers | | |
