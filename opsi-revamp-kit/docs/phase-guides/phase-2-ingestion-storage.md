# Phase 2 - ingestion and storage

## 2.1 Python environment
```bash
sudo dnf install -y python3.12 python3.12-pip     # AL2023 package names; adjust to your AMI
cd /opt/opsi-revamp-kit && python3.12 -m venv .venv
.venv/bin/pip install -r requirements/ingestion.txt     # internal mirror: pip config set global.index-url <mirror>
.venv/bin/pip install -r requirements/dev.txt && .venv/bin/python -m pytest tests/ingestion -q   # expect 93 passed
```
Elastic client: if your log cluster is 9.x, `pip install 'elasticsearch>=9,<10'`; if 8.x keep `8.19.x`.

## 2.2 Storage (with Cloud Security)
Apply `infrastructure/aws/` templates (bucket policy, lifecycle, KMS, IAM). Lab shortcut: `OPSI_LOCAL_ARCHIVE_DIR=/var/lib/opsi-ingest/archive`
(writes the same layout to disk; never for shared data).

## 2.3 Configuration
```bash
sudo install -m 0600 -o opsi-ingest -g opsi-ingest /dev/null /etc/opsi/ingest.env
sudo vi /etc/opsi/ingest.env     # copy the collector sections of .env.example
```
Minimum per source:
- Elastic: `ELASTIC_URL`, `ELASTIC_API_KEY`, `ELASTIC_INDEX_PATTERN`, `ELASTIC_TIMESTAMP_FIELD`; filter at source with
  `ELASTIC_QUERY_FILTER_JSON` (e.g. only error/warn) - volume is the main cost driver.
- Problems: `DYNATRACE_ENV_URL`, `DYNATRACE_API_TOKEN` (problems.read), optional `DYNATRACE_PROBLEMS_SELECTOR`.
- Grail: `DYNATRACE_PLATFORM_URL` (`*.apps.dynatrace.com`), OAuth client id/secret (+ resource if required),
  `DYNATRACE_GRAIL_DQL` **without** timeframe/limit (the collector adds them). Test the DQL in a Dynatrace notebook first.

## 2.4 First runs (dry run -> one real window -> timers)
```bash
cd /opt/opsi-revamp-kit/services/ingestion
sudo -u opsi-ingest bash -c 'set -a; . /etc/opsi/ingest.env; set +a; ../../.venv/bin/python -m opsi_ingest check-config --source elastic'
sudo -u opsi-ingest bash -c 'set -a; . /etc/opsi/ingest.env; set +a; ../../.venv/bin/python -m opsi_ingest collect --source elastic --dry-run'
sudo -u opsi-ingest bash -c 'set -a; . /etc/opsi/ingest.env; set +a; WORKER_STATE_DB=/var/lib/opsi-ingest/state.sqlite3 ../../.venv/bin/python -m opsi_ingest collect --source elastic --max-windows 1'
aws s3 ls s3://$OPSI_ARCHIVE_BUCKET/raw/elastic/ --recursive | tail
aws s3 cp s3://$OPSI_ARCHIVE_BUCKET/raw/elastic/dataset=logs/dt=.../window=.../run=.../_manifest.json - | python3 -m json.tool
```
Check: record counts plausible vs Kibana/Discover for the same window; `quarantined_count` ~0; `redaction_hits` sane.
Then install timers ([../../infrastructure/systemd/](../../infrastructure/systemd/)): copy units, `daemon-reload`,
`enable --now opsi-collect@elastic.timer` etc.

## 2.5 Curated PostgreSQL
DBA applies migrations 0000-0002 (rehearse on a snapshot - [../runbooks.md](../runbooks.md#migration-rehearsal-and-apply)),
creates the collector login in `opsi_ingest_writer`, then:
```bash
echo 'DATABASE_URL=postgresql://opsi_collector_svc@<host>:5432/opsi?sslmode=require' | sudo tee -a /etc/opsi/ingest.env
sudo systemctl enable --now opsi-index.timer
psql "$READONLY_URL" -c "select set_config('opsi.tenant_id','<tenant>',false); select service_id, sum(event_count) from opsi_ingest.error_signature_windows where window_start > now()-interval '1 hour' group by 1 order by 2 desc limit 10;"
```
(`opsi_readonly` members need `opsi.tenant_id` set to see rows - RLS.)

## 2.6 Optional OpenSearch operational index
`PUT _index_template/opsi-incidents` with `infrastructure/opensearch/opsi-incidents-template.json`, role with
`indices:data/write/bulk*` on `opsi-incidents*`, then set `OPENSEARCH_URL` etc.

## 2.7 Validate completeness and edge cases on real data
- Compare 24 h of window counts with the source (Elastic `_count` per window; Dynatrace problem list).
- Stop the timer 30 minutes, restart -> catch-up without gaps (`status` shows contiguous windows).
- Induce a DB outage in staging (revoke grant briefly) -> outbox retries, bronze continues.
- Grail: find a busy window -> check `splits` in manifests; no `WindowTooLarge` failures.
- Late data: watch `final_rescan` record deltas for a day.

## Exit criteria
Timers enabled for agreed sources; 24 h with no failed windows/gaps; curated tables fresh (< 15 min); quarantine < 1 %;
evidence logged.
