# AWS CLI

## Identity and region
```bash
aws sts get-caller-identity
aws configure list
export AWS_REGION=us-west-2
TOKEN=$(curl -s -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/iam/info   # instance profile
```

## S3 (bronze, attachments)
```bash
aws s3 ls s3://$BUCKET/raw/ --recursive | tail -20
aws s3 ls s3://$BUCKET/raw/elastic/dataset=logs/dt=2026-10-24/ | head
aws s3 cp s3://$BUCKET/raw/.../_manifest.json - | jq '{record_count, quarantined_count, parts: (.parts|length)}'
aws s3api head-object --bucket $BUCKET --key <key> --checksum-mode ENABLED     # SSE, KMS key, checksum, metadata
aws s3api get-object-tagging --bucket $ATT_BUCKET --key <attachment-key>        # GuardDuty scan status
aws s3api get-bucket-policy --bucket $BUCKET --query Policy --output text | jq .
aws s3api get-bucket-lifecycle-configuration --bucket $BUCKET
aws s3api get-bucket-encryption --bucket $BUCKET
aws s3api get-public-access-block --bucket $BUCKET
```

## KMS, IAM, Secrets Manager
```bash
aws kms describe-key --key-id alias/opsi-archive --query KeyMetadata.{Arn:Arn,State:KeyState,Rotation:KeyRotationStatus}
aws iam simulate-principal-policy --policy-source-arn <role-arn> --action-names s3:PutObject \
  --resource-arns arn:aws:s3:::$BUCKET/raw/x --query 'EvaluationResults[].EvalDecision'
aws accessanalyzer validate-policy --policy-type IDENTITY_POLICY --policy-document file://infrastructure/aws/iam/collector-instance-policy.json
aws secretsmanager get-secret-value --secret-id opsi/ingest/env --query SecretString --output text > /dev/null && echo readable
```

## RDS
```bash
aws rds describe-db-instances --query 'DBInstances[].{id:DBInstanceIdentifier,engine:EngineVersion,class:DBInstanceClass,pitr:LatestRestorableTime}'
aws rds describe-db-snapshots --db-instance-identifier <id> --snapshot-type automated --query 'DBSnapshots[-3:].DBSnapshotIdentifier'
aws rds create-db-snapshot --db-instance-identifier <id> --db-snapshot-identifier pre-migration-$(date +%Y%m%d%H%M)
# restore drills: docs/runbooks.md "Restore drill"
```

## Bedrock (what can Portkey call?)
```bash
aws bedrock list-inference-profiles --query 'inferenceProfileSummaries[].{id:inferenceProfileId,status:status}'
aws bedrock list-foundation-models --by-output-modality TEXT --query 'modelSummaries[].modelId'
aws bedrock get-inference-profile --inference-profile-identifier <id> --query 'models[].modelArn'   # regions to allow in IAM
```

## Athena over bronze
Create a table on the Parquet layout with partition projection on `dt` (adjust bucket/source):
```sql
CREATE EXTERNAL TABLE opsi_bronze_elastic_logs (
  schema_version string, tenant_id string, source string, dataset string, origin_id string, event_uid string,
  record_version string, event_time timestamp, ingest_time timestamp, window_start timestamp, window_end timestamp,
  run_id string, severity string, severity_raw string, status string, service_id string, host_id string,
  trace_id string, title string, message string, message_fingerprint string, classification string,
  source_ref string, redaction_hits int, payload_json string, payload_truncated boolean, payload_sha256 string)
PARTITIONED BY (dt string)
STORED AS PARQUET
LOCATION 's3://BUCKET/raw/elastic/dataset=logs/'
TBLPROPERTIES ('projection.enabled'='true', 'projection.dt.type'='date', 'projection.dt.format'='yyyy-MM-dd',
               'projection.dt.range'='2026-01-01,NOW', 'storage.location.template'='s3://BUCKET/raw/elastic/dataset=logs/dt=${dt}/');
-- Athena reads all files below dt=..., including runs without a manifest (rare orphans) and multiple runs per window.
-- Dedupe: keep the newest ingest per event_uid
SELECT * FROM (
  SELECT *, row_number() OVER (PARTITION BY event_uid ORDER BY ingest_time DESC) rn
  FROM opsi_bronze_elastic_logs WHERE dt = '2026-10-24' AND severity IN ('ERROR','CRITICAL')) WHERE rn = 1 LIMIT 100;
```
Note: Athena timestamps from Parquet microsecond UTC columns appear without zone - treat as UTC.
