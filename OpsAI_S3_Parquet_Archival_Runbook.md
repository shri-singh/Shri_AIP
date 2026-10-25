# Ops AI — Elasticsearch & Dynatrace → S3 Parquet → PostgreSQL

**Operational implementation runbook | 25 October 2026**  
**Target:** Existing Amazon Linux 2023 EC2 with approved access to Elasticsearch/Dynatrace, S3 archival, 2-minute scheduling, Athena historical queries, and optional AWS Glue-to-PostgreSQL recent-data loads.

> **Important:** This is a deployable pilot pattern, not an authorization to purge production records. Do not delete PostgreSQL data until the archive, replay, row counts, access controls, recovery procedures and application queries have been validated. Obtain corporate approvals for IAM, networking, encryption and retention.

## 1. Architecture and decisions

```text
Elasticsearch REST API -----\
                            +--> existing EC2 Python collectors (cron every 2 min)
Dynatrace Problems API -----/         |
                                     v
                          S3 raw/source/dataset/yyyy/mm/dd/*.parquet
                                     |
                  +------------------+--------------------+
                  |                                       |
        Glue Data Catalog + Athena                  AWS Glue ETL (optional)
        historical analytics                        read S3, write to PostgreSQL
                  |                                       |
                  +----------- FastAPI query router ------+
                              PostgreSQL hot tier (30 or 90 days)
```

- Use **one bucket** if the same security owner, account, encryption and retention controls apply. Separate `raw/elasticsearch/` and `raw/dynatrace/` prefixes. Use separate buckets when security/account boundaries demand it.
- The **raw archive** stores immutable, source-preserving records as Snappy Parquet with `record_id`, `event_time`, `payload_json`, `ingested_at`. It is *not* a fully typed analytics model; curate separately for efficient analytics.
- The collector performs **at-least-once** ingestion. Overlap windows and retries can create duplicates; use stable record IDs and deduplication in downstream processing. Dynatrace problems are mutable: poll/reconcile open problems and updated states separately.
- The existing EC2 is not inherently slower than Lambda. Elasticsearch throughput, network, API rate limits and Parquet file sizes are the key constraints.
- S3 does **not** automatically populate PostgreSQL. A separate Glue ETL job or parallel ingestion path is needed. For near-real-time hot data, a parallel Python-to-PostgreSQL batch upsert is often simpler than a Glue load every two minutes. Glue is better suited to scheduled/batched loading.
- Keep backups/PITR separate from S3 archival. Decide whether the hot window is **30 days** or **90 days**; do not mix the two.

## 2. Preflight and prerequisites

On the existing EC2 (Amazon Linux 2023 assumed):

```bash
whoami
cat /etc/os-release
python3 --version
aws --version
aws sts get-caller-identity
curl -I --max-time 15 https://s3.amazonaws.com || true
```

Verify the **existing Elasticsearch and Dynatrace endpoints** work from this EC2. Reuse approved API endpoints/tokens; no new firewall exception is needed if this same EC2 and egress route already have access. S3 access still requires AWS network connectivity (NAT/internet or S3 VPC gateway endpoint) and IAM permissions. Do not paste secrets into tickets or AI prompts.

**Required permissions for setup operator:** S3 bucket administration, IAM policy/role attachment (or help from IAM administrator), and optionally Glue/Athena/Secrets Manager. **Required permissions for runtime EC2 role:** `s3:PutObject` for raw prefixes; optionally `s3:GetObject`/`s3:ListBucket` for verification; CloudWatch permissions if shipping logs. Use instance profile credentials, not long-lived AWS keys.

## 3. Install packages and directories

```bash
sudo dnf install -y python3.11 python3.11-pip cronie util-linux jq
sudo systemctl enable --now crond
sudo mkdir -p /opt/opsai-ingestion/{scripts,logs,state}
sudo chown -R "$(id -un):$(id -gn)" /opt/opsai-ingestion
cd /opt/opsai-ingestion
python3.11 -m venv venv
./venv/bin/python -m pip install --upgrade pip
./venv/bin/pip install boto3 pyarrow requests elasticsearch python-dotenv tenacity psycopg[binary]
```

Run the cron job under this same OS user. Ensure only that user can read state, logs and credentials.

## 4. Create and secure S3 bucket

Set values; replace placeholders with approved names/region. Bucket names are globally unique.

```bash
export AWS_REGION='us-east-1'
export BUCKET='opsai-observability-REPLACE-ACCOUNT-2026'
export AWS_DEFAULT_REGION="$AWS_REGION"
# Run ONE branch, depending on region:
if [ "$AWS_REGION" = 'us-east-1' ]; then
  aws s3api create-bucket --bucket "$BUCKET" --region "$AWS_REGION"
else
  aws s3api create-bucket --bucket "$BUCKET" --region "$AWS_REGION" \
    --create-bucket-configuration "LocationConstraint=$AWS_REGION"
fi
aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration 'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'
aws s3api put-bucket-encryption --bucket "$BUCKET" \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-bucket-versioning --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled
aws s3api get-bucket-encryption --bucket "$BUCKET"
```

Corporate policy may require **SSE-KMS**, a customer-managed key, specific bucket policies, S3 access logging, object lock or lifecycle rules. Use approved controls rather than overriding them. Versioning increases storage cost; apply lifecycle policies after retention approval.

### Runtime EC2 IAM policy (administrator attaches to EC2 instance role)

Create a file on an admin workstation, replace `REPLACE_BUCKET` and attach to the EC2 **instance role**, not to a human user:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "WriteRawParquet",
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": "arn:aws:s3:::REPLACE_BUCKET/raw/*"
    },
    {
      "Sid": "InspectArchive",
      "Effect": "Allow",
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::REPLACE_BUCKET/raw/*"
    },
    {
      "Sid": "ListArchive",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::REPLACE_BUCKET"
    }
  ]
}
```

For SSE-KMS, add the appropriate KMS key permissions. An IAM administrator can create the policy and attach it to the existing role. **Do not replace an existing EC2 role without checking its other application permissions.**

Verify after attachment:

```bash
aws sts get-caller-identity
printf 'test\n' >/tmp/opsai-s3-test.txt
aws s3 cp /tmp/opsai-s3-test.txt "s3://$BUCKET/raw/elasticsearch/test.txt"
aws s3 ls "s3://$BUCKET/raw/elasticsearch/"
```

## 5. Configure collectors without exposing secrets

For the pilot, use a local `.env` file with mode 600. **Production preference:** Secrets Manager or SSM Parameter Store with EC2 role permissions and secret rotation.

```bash
cd /opt/opsai-ingestion
umask 077
cat > .env.example <<'ENV'
AWS_REGION=us-east-1
S3_BUCKET=REPLACE_BUCKET
ELASTIC_URL=https://REPLACE_ELASTIC_ENDPOINT
ELASTIC_API_KEY=REPLACE_ELASTIC_API_KEY
ELASTIC_INDEX=REPLACE_INDEX_PATTERN
ELASTIC_TIME_FIELD=@timestamp
DYNATRACE_URL=https://REPLACE_DYNATRACE_ENVIRONMENT
DYNATRACE_API_TOKEN=REPLACE_DYNATRACE_TOKEN
LOOKBACK_SECONDS=300
ENV
cp .env.example .env
chmod 600 .env
nano .env
```

The example assumes an Elasticsearch API key and Dynatrace `Api-Token` with `problems.read`. Adapt the authentication mechanism to your existing working code. Dynatrace Managed endpoints may differ from SaaS.

## 6. Create common Parquet writer

```bash
cat > /opt/opsai-ingestion/scripts/parquet_writer.py <<'PY'
import io, json, os, uuid
from datetime import datetime, timezone
import boto3
import pyarrow as pa
import pyarrow.parquet as pq


def upload_records(source, dataset, records, batch_time):
    if not records:
        return None
    rows = [{
        'record_id': str(r['id']),
        'event_time': str(r.get('event_time', '')),
        'payload_json': json.dumps(r['payload'], ensure_ascii=False, default=str),
        'ingested_at': datetime.now(timezone.utc).isoformat()
    } for r in records]
    table = pa.Table.from_pylist(rows)
    out = io.BytesIO()
    pq.write_table(table, out, compression='snappy')
    out.seek(0)
    key = (f'raw/{source}/{dataset}/'
           f'year={batch_time:%Y}/month={batch_time:%m}/day={batch_time:%d}/'
           f'part-{uuid.uuid4().hex}.parquet')
    boto3.client('s3', region_name=os.environ['AWS_REGION']).upload_fileobj(
        out, os.environ['S3_BUCKET'], key)
    print(f'uploaded rows={len(rows)} s3://{os.environ["S3_BUCKET"]}/{key}', flush=True)
    return key
PY
```

**File sizing:** every two minutes can create many small files. This pilot uses one file per nonempty batch; add daily/hourly compaction (target ~128–512 MB files where practical) before heavy Athena use. Date partitions here represent **ingestion date**, not event date; build event-date curated tables for event-time filtering.

## 7. Elasticsearch collector with checkpoint and bounded pages

This uses the official Elasticsearch `helpers.scan` API (scroll) for a simple pilot. For high-volume production, prefer point-in-time + `search_after` when supported by your Elasticsearch version. The timestamp field must be mapped correctly.

```bash
cat > /opt/opsai-ingestion/scripts/elastic_collector.py <<'PY'
import json, os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from elasticsearch import Elasticsearch, helpers
from parquet_writer import upload_records

STATE = Path('/opt/opsai-ingestion/state/elastic.json')
TIME_FIELD = os.getenv('ELASTIC_TIME_FIELD', '@timestamp')
OVERLAP = int(os.getenv('LOOKBACK_SECONDS', '300'))

def fmt(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')

def checkpoint():
    if STATE.exists():
        return datetime.fromisoformat(json.loads(STATE.read_text())['end_time'].replace('Z','+00:00'))
    return datetime.now(timezone.utc) - timedelta(minutes=10)

def commit(dt):
    tmp = STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps({'end_time': fmt(dt)}))
    os.replace(tmp, STATE)

def run():
    es = Elasticsearch(os.environ['ELASTIC_URL'],
                       api_key=os.environ['ELASTIC_API_KEY'],
                       request_timeout=60, max_retries=3, retry_on_timeout=True)
    if not es.ping():
        raise RuntimeError('Elasticsearch ping failed')
    start = checkpoint() - timedelta(seconds=OVERLAP)
    end = datetime.now(timezone.utc) - timedelta(seconds=30)
    if end <= start:
        return
    query = {'query': {'range': {TIME_FIELD: {'gte': fmt(start), 'lt': fmt(end)}}}}
    batch, count = [], 0
    for hit in helpers.scan(es, index=os.environ['ELASTIC_INDEX'], query=query,
                            size=1000, scroll='5m', request_timeout=120):
        src = hit.get('_source', {})
        batch.append({'id': f"{hit['_index']}:{hit['_id']}",
                      'event_time': src.get(TIME_FIELD, ''), 'payload': src})
        if len(batch) >= 5000:
            upload_records('elasticsearch', 'logs', batch, end)
            count += len(batch)
            batch.clear()
    if batch:
        upload_records('elasticsearch', 'logs', batch, end)
        count += len(batch)
    commit(end)  # Advance only when all S3 uploads succeed
    print(f'elastic count={count} checkpoint={fmt(end)}', flush=True)

if __name__ == '__main__':
    run()
PY
```

**Caveats:** overlapping windows generate duplicates. A time-range query can miss documents indexed much later than their event timestamps or updates to older documents. Use ingest/update timestamps, reconciliation and source-specific deduplication for production-grade completeness. A crash after some uploads but before checkpoint commit can also repeat entire batches.

## 8. Dynatrace Problems collector

The following example uses Dynatrace Environment API v2 Problems with a start/end window and pagination. Confirm your specific Dynatrace Managed/SaaS version, endpoint and query parameter semantics before deployment. For mutable problems, use wider reconciliation of open problems; this example is a **pilot**, not guaranteed complete history of problem state changes.

```bash
cat > /opt/opsai-ingestion/scripts/dynatrace_collector.py <<'PY'
import json, os, time
from pathlib import Path
from datetime import datetime, timedelta, timezone
import requests
from parquet_writer import upload_records

STATE = Path('/opt/opsai-ingestion/state/dynatrace.json')

def ms(dt): return int(dt.timestamp() * 1000)

def checkpoint():
    if STATE.exists():
        return datetime.fromisoformat(json.loads(STATE.read_text())['end_time'])
    return datetime.now(timezone.utc) - timedelta(minutes=10)

def commit(dt):
    tmp = STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps({'end_time': dt.isoformat()}))
    os.replace(tmp, STATE)

def run():
    end = datetime.now(timezone.utc) - timedelta(seconds=30)
    start = checkpoint() - timedelta(seconds=int(os.getenv('LOOKBACK_SECONDS','300')))
    if end <= start:
        return
    base = os.environ['DYNATRACE_URL'].rstrip('/')
    session = requests.Session()
    session.headers.update({'Authorization': 'Api-Token ' + os.environ['DYNATRACE_API_TOKEN'],
                            'Accept': 'application/json'})
    url = base + '/api/v2/problems'
    params = {'from': str(ms(start)), 'to': str(ms(end)), 'pageSize': 500}
    records = []
    while True:
        for attempt in range(5):
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code in (429,500,502,503,504) and attempt < 4:
                time.sleep(min(2 ** attempt, 16))
                continue
            resp.raise_for_status()
            break
        data = resp.json()
        for p in data.get('problems', []):
            records.append({'id': p['problemId'],
                            'event_time': p.get('startTime', ''), 'payload': p})
        next_key = data.get('nextPageKey')
        if not next_key:
            break
        params = {'nextPageKey': next_key}
    if records:
        upload_records('dynatrace', 'problems', records, end)
    commit(end)
    print(f'dynatrace count={len(records)} checkpoint={end.isoformat()}', flush=True)

if __name__ == '__main__':
    run()
PY
```

To ingest Dynatrace **metrics, entities or logs**, build separate collectors using their distinct APIs and scopes. Do not assume the Problems endpoint provides all telemetry.

## 9. Wrapper and cron scheduler (every two minutes)

```bash
cat > /opt/opsai-ingestion/run_ingestion.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cd /opt/opsai-ingestion
set -a
source /opt/opsai-ingestion/.env
set +a
/opt/opsai-ingestion/venv/bin/python /opt/opsai-ingestion/scripts/elastic_collector.py
/opt/opsai-ingestion/venv/bin/python /opt/opsai-ingestion/scripts/dynatrace_collector.py
SH
chmod 700 /opt/opsai-ingestion/run_ingestion.sh
/opt/opsai-ingestion/run_ingestion.sh
```

When both manual tests succeed, configure cron **as the same Linux user**:

```bash
sudo systemctl enable --now crond
crontab -e
```

Add exactly this line (adjust user paths if necessary):

```cron
*/2 * * * * /usr/bin/flock -n /tmp/opsai-ingest.lock /opt/opsai-ingestion/run_ingestion.sh >> /opt/opsai-ingestion/logs/ingestion.log 2>&1
```

Verify:

```bash
crontab -l
sudo systemctl status crond --no-pager
tail -100 /opt/opsai-ingestion/logs/ingestion.log
sudo journalctl -u crond --since '30 minutes ago' --no-pager
cat /opt/opsai-ingestion/state/elastic.json
cat /opt/opsai-ingestion/state/dynatrace.json
```

`flock` skips overlapping runs. If extraction routinely exceeds two minutes, increase capacity or split collectors into independent schedules and locks. Ensure log rotation:

```bash
sudo tee /etc/logrotate.d/opsai-ingestion >/dev/null <<'LOG'
/opt/opsai-ingestion/logs/*.log {
  daily
  rotate 14
  compress
  missingok
  notifempty
  copytruncate
}
LOG
sudo logrotate -d /etc/logrotate.d/opsai-ingestion
```

## 10. Verify archived objects and Parquet contents

```bash
aws s3 ls "s3://$BUCKET/raw/elasticsearch/logs/" --recursive --human-readable --summarize
aws s3 ls "s3://$BUCKET/raw/dynatrace/problems/" --recursive --human-readable --summarize
# Replace ACTUAL_KEY with an object key returned above
aws s3 cp "s3://$BUCKET/ACTUAL_KEY" /tmp/sample.parquet
/opt/opsai-ingestion/venv/bin/python - <<'PY'
import pyarrow.parquet as pq
p = pq.ParquetFile('/tmp/sample.parquet')
print(p.schema)
print('rows:', p.metadata.num_rows)
PY
```

Validate record counts and unique IDs against source queries for matching fixed windows. Test interrupted uploads, duplicate delivery, bad credentials, API rate limits, and replay from checkpoint backups. **Do not delete or overwrite checkpoints casually.**

## 11. Glue Data Catalog + Athena (query historical S3 directly)

In AWS Console: **Glue → Data Catalog → Databases → Add database**, e.g. `opsai_archive`. Create a crawler scoped to `s3://BUCKET/raw/elasticsearch/logs/` and a second to `.../dynatrace/problems/`; select the Glue database and run. Review inferred tables and partition columns; crawlers are convenient for a pilot but explicit schemas and partition projection are often more stable in production. Set up an Athena workgroup and S3 query-result location with appropriate IAM/KMS.

Example Athena SQL after verifying the actual generated table names:

```sql
SHOW TABLES IN opsai_archive;
SELECT record_id, event_time, payload_json
FROM opsai_archive.elasticsearch_logs
WHERE year = '2026' AND month = '10' AND day = '25'
LIMIT 20;
```

**Important:** the table name and partition types above are illustrative. Inspect the Glue Catalog and adjust. These raw partitions are ingestion-date based; build curated event-date tables for efficient historical event-time queries. Athena is not PostgreSQL and does not automatically populate it.

## 12. Glue → PostgreSQL: optional managed batch loading of recent data

### A. Design choices

**Preferred for 2-minute freshness:** In the EC2 collector, batch-upsert the same records into PostgreSQL directly, with a unique key and a transaction. Keep S3 as the durable archive and store separate delivery/checkpoint status per destination. This avoids starting a Glue Spark job every two minutes.

**Preferred for scheduled/batch hot-tier rebuilding:** Glue reads S3 Parquet and writes to PostgreSQL over JDBC. Use a **staging table** and an idempotent merge/upsert procedure; naive Glue JDBC `append` may create duplicates and cannot implement PostgreSQL `ON CONFLICT` automatically. This is a distinct job with its own watermark and error recovery.

### B. Prepare PostgreSQL table (example; adjust schema/permissions)

Use DBeaver or `psql` with an approved write account:

```sql
CREATE SCHEMA IF NOT EXISTS opsai_ingest;
CREATE TABLE IF NOT EXISTS opsai_ingest.raw_events (
    source text NOT NULL,
    record_id text NOT NULL,
    event_time timestamptz,
    payload_json jsonb NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, record_id)
);
CREATE INDEX IF NOT EXISTS raw_events_event_time_idx
    ON opsai_ingest.raw_events (event_time);
```

This simple key treats `record_id` as the current/latest representation. For full version history use a version key. JSON parsing must be valid. If your table is huge, plan date partitioning and indexes separately. No deletion commands are included here.

### C. AWS Console: Glue connection and job

1. **Secrets Manager:** store PostgreSQL credentials; avoid plaintext job arguments.
2. **VPC:** ensure Glue can reach the RDS/Aurora endpoint on port 5432 using approved subnets/security groups. Glue's network connection requires suitable routing and security group rules; an S3 gateway endpoint or NAT may be needed for S3 access. Test DNS and connectivity.
3. **Glue → Connections:** create a PostgreSQL JDBC connection using `jdbc:postgresql://DB_HOST:5432/DB_NAME`, credentials via Secrets Manager where supported, and VPC network settings. Test the connection.
4. **Glue → ETL jobs:** create a Spark job that reads S3 Parquet from the relevant prefix, filters the **event timestamp** to the desired 30-day/90-day hot window, transforms JSON fields and writes a JDBC staging table.
5. **Post-load SQL:** upsert staging rows into `opsai_ingest.raw_events`, validate counts, and clear only the successfully processed staging batch. Maintain a durable Glue watermark / processed-object manifest. Glue bookmarks alone may not solve duplicate/version semantics.
6. **Glue triggers/EventBridge:** schedule a batch cadence that matches operational latency needs (for example hourly). Monitor failures in CloudWatch and configure alerts.

### D. Example Glue Spark job skeleton

The following is a **template**, not a complete production upsert pipeline. Set Glue job arguments `--S3_PATH`, `--JDBC_URL`, `--SECRET_ID`, `--REGION`, and `--STAGING_TABLE`. Grant the Glue role S3 read, Secrets Manager read, networking, CloudWatch, and KMS as applicable. The source path should be scoped to an incremental set of objects, not all history every run.

```python
import sys, json, boto3
from datetime import datetime, timedelta, timezone
from awsglue.utils import getResolvedOptions
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, to_timestamp, lit

args = getResolvedOptions(sys.argv, [
    'S3_PATH', 'JDBC_URL', 'SECRET_ID', 'REGION', 'STAGING_TABLE'
])
secret = json.loads(boto3.client('secretsmanager', region_name=args['REGION'])
                    .get_secret_value(SecretId=args['SECRET_ID'])['SecretString'])
spark = SparkSession.builder.getOrCreate()
df = spark.read.parquet(args['S3_PATH'])
# Timestamp formats should be normalized explicitly for each source.
df = df.withColumn('event_ts', to_timestamp(col('event_time')))
cutoff = datetime.now(timezone.utc) - timedelta(days=30)
df = df.filter(col('event_ts') >= lit(cutoff))
# Source is inferred from the input dataset; run per source/prefix.
df = df.select(col('record_id'), col('event_ts').alias('event_time'),
               col('payload_json'), col('ingested_at'))
(df.write.format('jdbc')
   .option('url', args['JDBC_URL'])
   .option('dbtable', args['STAGING_TABLE'])
   .option('user', secret['username'])
   .option('password', secret['password'])
   .option('driver', 'org.postgresql.Driver')
   .mode('append').save())
```

**Do not schedule this skeleton unattended as-is.** It lacks incremental file selection, source labeling, transactional batch IDs, retries, conflict handling, cleanup and reconciliation. `to_timestamp` may not parse Dynatrace epoch-millisecond timestamps: normalize those with a source-specific transformation. Implement and test the staging/upsert design before enabling recurring Glue runs.

### E. Example PostgreSQL upsert from staging

If your staging table is `opsai_ingest.raw_events_stage` with `source,record_id,event_time,payload_json,ingested_at` and records have been deduplicated within the batch:

```sql
INSERT INTO opsai_ingest.raw_events
    (source, record_id, event_time, payload_json, ingested_at)
SELECT source, record_id, event_time, payload_json::jsonb, ingested_at
FROM opsai_ingest.raw_events_stage
ON CONFLICT (source, record_id) DO UPDATE SET
    event_time = EXCLUDED.event_time,
    payload_json = EXCLUDED.payload_json,
    ingested_at = EXCLUDED.ingested_at
WHERE opsai_ingest.raw_events.ingested_at <= EXCLUDED.ingested_at;
```

Use an explicit batch identifier and transaction in production. If a source record is immutable, `DO NOTHING` may be preferable. A unique conflict key is essential.

## 13. Retention and safe PostgreSQL archival

- Establish an explicit UTC cutoff (30 or 90 days), which may differ from **three calendar months**.
- Inventory all large tables, foreign keys, mutable entities, event timestamps, indexes and late-arriving data behavior.
- Backfill existing PostgreSQL history into S3 **separately**; this EC2 API collector does not migrate 6 TB already in PostgreSQL.
- Reconcile counts, checksums/samples, IDs and temporal coverage; verify Athena queries and recovery from S3.
- Only after approval, remove old rows using **date partitions** (preferred) or carefully bounded batch deletes with vacuum/space-reclamation planning. Do not run a single 6 TB-scale `DELETE`.
- A 6 TB PostgreSQL database size includes indexes, bloat and TOAST; Parquet size is not equal to 6 TB. Benchmark compression and query scans before budgeting.
- For historical mutable records, consider curated Apache Iceberg tables or a change/reconciliation process; raw immutable Parquet does not automatically update old objects.

## 14. Operational checks and troubleshooting

| Symptom | Check / action |
|---|---|
| `AccessDenied` on S3 | EC2 instance role, bucket policy, KMS permissions, organization SCP, object ownership |
| Elastic 401/403 | API key scope, endpoint, certificate, corporate proxy; do not disable TLS verification |
| Elastic timeout | VPN/network route, proxy, pagination, API load, request timeout |
| Dynatrace 401/403 | Correct environment URL and `problems.read` token scope |
| No cron executions | `systemctl status crond`, `crontab -l`, file permissions, wrapper executable |
| Duplicate Parquet records | Expected under overlap/retry; deduplicate downstream using IDs and version/time |
| Many tiny Parquet files | Add scheduled compaction and curated partitioning |
| Glue JDBC fails | VPC routing, SG ingress 5432, DNS, secrets, JDBC URL, RDS availability |
| Glue duplicates | Use batch staging + unique key + upsert + processed-object manifest |
| Athena scans too much | Partition pruning, file compaction, typed curated datasets |

Recommended alerts: no successful checkpoint advancement for >10 minutes, failed uploads, API 429/5xx spikes, unexpected zero records, S3 storage growth, and failed Glue jobs. Add CloudWatch metrics/log shipping for production.

## 15. Estimated effort and rollout

| Scope | Planning estimate |
|---|---:|
| Existing EC2 → Elasticsearch Parquet S3 pilot | 6–10 engineering hours |
| Add Dynatrace Problems collector and validation | 8–16 additional hours |
| Production hardening: secrets, monitoring, dedupe, replay, compaction | 20–40 hours (depending on controls) |
| Glue Catalog + Athena initial integration | 4–10 hours |
| Glue → PostgreSQL batch staging/upsert integration | 16–32 hours |
| Existing 6 TB historical backfill, safe purge and application query routing | Separate project; requires sizing and load testing |

These are estimates, not guarantees. API volume, enterprise approvals, source schemas, VPN and RDS configuration can materially change effort.

## 16. Deployment acceptance checklist

- [ ] EC2 reaches Elasticsearch and Dynatrace with existing approved credentials and TLS validation.
- [ ] EC2 role can write to the approved encrypted, private S3 bucket.
- [ ] Both collectors complete manual tests and create readable Snappy Parquet objects.
- [ ] Checkpoints advance only after successful S3 uploads; failed-run replay tested.
- [ ] Cron runs every two minutes; `flock` prevents overlap; logs rotate.
- [ ] Data counts and IDs reconcile against fixed source windows.
- [ ] Duplicate handling and mutable Dynatrace problem updates are documented.
- [ ] Athena can query archived files with approved access controls.
- [ ] Glue PostgreSQL network connectivity, staging and idempotent upsert tested before scheduling.
- [ ] Retention policy, backfill, purge and restore plans approved separately.

## 17. Useful official references

- [Amazon S3 CLI reference](https://docs.aws.amazon.com/cli/latest/reference/s3api/)
- [IAM roles for EC2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/iam-roles-for-amazon-ec2.html)
- [AWS Glue JDBC connections](https://docs.aws.amazon.com/glue/latest/dg/add-job.html)
- [AWS Glue Data Catalog](https://docs.aws.amazon.com/glue/latest/dg/catalog-and-crawler.html)
- [Amazon Athena documentation](https://docs.aws.amazon.com/athena/latest/ug/what-is.html)
- [Elasticsearch Python client](https://www.elastic.co/docs/reference/elasticsearch/clients/python)
- [Dynatrace API documentation](https://docs.dynatrace.com/docs/dynatrace-api)
- [PyArrow Parquet API](https://arrow.apache.org/docs/python/parquet.html)

---

**Rollout sequence:** (1) S3 + IAM → (2) Elastic collector → (3) manual Parquet verification → (4) cron → (5) Dynatrace collector → (6) Athena catalog → (7) optional Glue staging/upsert → (8) historical PostgreSQL backfill and controlled retention. Keep the existing production PostgreSQL ingestion running throughout the pilot.
