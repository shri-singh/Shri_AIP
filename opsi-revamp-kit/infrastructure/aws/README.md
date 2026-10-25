# AWS artefacts (templates - every `REPLACE_*` must be filled in, then reviewed by Cloud Security)

| File | Attach to | Purpose |
|---|---|---|
| `iam/collector-instance-policy.json` | EC2 instance role of the collector host | write `raw/` + `quarantine/` only, use the archive KMS key via S3 only, read `opsi/ingest/*` secrets |
| `iam/api-instance-policy.json` | EC2 instance role of the Opsi API host | presign chat attachments, read GuardDuty scan tags, optional Transcribe/Polly, read `opsi/api/*` secrets |
| `iam/bedrock-invoke-policy.json` | the role **Portkey** uses for Bedrock (Portkey integration / its own instance role) | invoke only the approved model / inference profile |
| `s3/bucket-policy.json` | archive / attachments bucket | deny non-TLS, deny puts without the approved KMS key, optional VPC-endpoint-only access |
| `s3/lifecycle.json` | archive / attachments bucket | tiering + retention (numbers are placeholders - retention is a records-management decision) |
| `kms/key-policy.json` | customer-managed KMS key | admins administer; Opsi roles use the key only through S3 |

## Apply (only with approval, as an admin of the bucket - never on a bucket you do not own)

```bash
export AWS_REGION=us-west-2 BUCKET=REPLACE_BUCKET
aws sts get-caller-identity                     # confirm WHO you are first
aws s3api get-bucket-policy --bucket "$BUCKET" 2>/dev/null > /tmp/old-policy.json || true   # keep a copy for rollback
aws s3api put-bucket-policy --bucket "$BUCKET" --policy file://infrastructure/aws/s3/bucket-policy.json
aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" --lifecycle-configuration file://infrastructure/aws/s3/lifecycle.json
aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"aws:kms","KMSMasterKeyID":"REPLACE_KMS_KEY_ARN"},"BucketKeyEnabled":true}]}'
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
```

Rollback: `aws s3api put-bucket-policy --bucket "$BUCKET" --policy file:///tmp/old-policy.json`
(or `delete-bucket-policy` if there was none).

## Notes that bite

- **SSE-S3 vs SSE-KMS**: the bucket policy denies uploads that are not `aws:kms` with the approved key.
  If you deliberately use SSE-S3 (`OPSI_KMS_KEY_ID` empty), remove `DenyPutsWithoutKms` and
  `DenyPutsWithOtherKmsKeys`, or the collectors will get `AccessDenied` (that is the intended fail-loud).
- **Presigned URLs need SigV4** for KMS-encrypted objects (the API forces `signature_version="s3v4"`).
- **Deleting objects with versioning on** only adds a delete marker; `NoncurrentVersionExpiration`
  does the real cleanup. Object Lock (WORM) would block the collector's orphan cleanup - then drop the
  `OptionalCleanupOfUncommittedParts` statement; orphans are harmless (no manifest = ignored).
- **GuardDuty Malware Protection for S3** must be enabled on the attachments bucket/prefix for scan tags
  (`GuardDutyMalwareScanStatus`) to appear. Confirm the tag key and values in your account.
- **Inference profiles**: cross-region profiles need the foundation-model ARN allowed in every region the
  profile routes to (hence `arn:aws:bedrock:*::foundation-model/...`). Check with
  `aws bedrock get-inference-profile --inference-profile-identifier <id>`.
- **Validate policies** before applying: `aws accessanalyzer validate-policy --policy-type IDENTITY_POLICY --policy-document file://...`
  (use `RESOURCE_POLICY` + `--validate-policy-resource-type AWS::S3::Bucket` for the bucket policy).
