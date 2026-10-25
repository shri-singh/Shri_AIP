# opsi_ingest - bounded collectors

Elastic (PIT + search_after), Dynatrace Problems v2 (page keys), Dynatrace Grail (OAuth, execute/poll/cancel), Broadcom OI
(stub) -> redacted `opsi.event.v1` Parquet in S3 with manifests -> (separately) curated PostgreSQL / OpenSearch.
Design: ADR-0006/0007, consultation 04, data contracts.

```
opsi_ingest/
  cli.py            collect | backfill | index | status | skip-window | requeue-dead | reset-watermark | check-config
  config.py         env -> Settings (secrets masked in repr)
  windows.py        grid windows, final re-scan rule, split
  timeutil.py       strict UTC parsing (ns ISO, epoch ms), never "now" for bad input
  redaction.py      secrets + PII scrubbing (canonical copy; API copy synced by scripts/sync_redaction.py)
  http.py           retries for 429/5xx with Retry-After, scrubbed errors
  normalize.py      vendor record -> row or quarantine; fingerprints; event_uid
  contract.py       fixed Arrow schema opsi.event.v1
  state.py          ledger, watermarks, outbox, runs, operator actions (SQLite or PostgreSQL)
  pipeline.py       BronzeStage (split-on-cap, commit) and IndexStage (outbox, retries, dead letter)
  sources/          base, elastic, dynatrace_problems, dynatrace_grail, dynatrace_auth, broadcom_oi (stub)
  sinks/            objectstore (S3/local/dry-run), bronze (parts+manifest+quarantine), curated, postgres_curated, opensearch
fixtures/           synthetic vendor-shaped responses (see fixtures/README.md)
```

## Commands (from this directory, env loaded)
```bash
python -m opsi_ingest check-config --source dynatrace_grail
python -m opsi_ingest collect --source elastic --dry-run
python -m opsi_ingest collect --source elastic [--max-windows N]
python -m opsi_ingest backfill --source dynatrace_problems --from 2026-10-01T00:00:00Z --to 2026-10-02T00:00:00Z [--dry-run]
python -m opsi_ingest index [--source elastic] [--limit 100]
python -m opsi_ingest status [--hours 24] [--json]          # exit 1 on failed windows / dead letters
python -m opsi_ingest skip-window --source elastic --window-start <ISO> --actor <you> --reason "<why + ticket>"
python -m opsi_ingest requeue-dead --actor <you> --reason "<why>"
python -m opsi_ingest reset-watermark --source elastic --to <ISO> --actor <you> --reason "<why>" --yes
```
Exit codes: 0 ok, 1 something failed (alertable), 2 configuration error.
Scheduling: `infrastructure/systemd/` (preferred) or `infrastructure/cron/`. Operations: `docs/runbooks.md`.
