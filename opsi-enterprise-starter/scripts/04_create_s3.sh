#!/usr/bin/env bash
set -euo pipefail
: "${AWS_REGION:?Set AWS_REGION}"
: "${OPSI_ARCHIVE_BUCKET:?Set OPSI_ARCHIVE_BUCKET}"
aws sts get-caller-identity >/dev/null
if aws s3api head-bucket --bucket "$OPSI_ARCHIVE_BUCKET" 2>/dev/null; then
 echo "Bucket exists/access granted: $OPSI_ARCHIVE_BUCKET. No settings changed."; exit 0
fi
if [[ "$AWS_REGION" == us-east-1 ]]; then
 aws s3api create-bucket --bucket "$OPSI_ARCHIVE_BUCKET" --region "$AWS_REGION"
else
 aws s3api create-bucket --bucket "$OPSI_ARCHIVE_BUCKET" --region "$AWS_REGION" \
   --create-bucket-configuration "LocationConstraint=$AWS_REGION"
fi
aws s3api put-public-access-block --bucket "$OPSI_ARCHIVE_BUCKET" --public-access-block-configuration \
 'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'
aws s3api put-bucket-encryption --bucket "$OPSI_ARCHIVE_BUCKET" --server-side-encryption-configuration \
 '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-bucket-versioning --bucket "$OPSI_ARCHIVE_BUCKET" --versioning-configuration Status=Enabled
echo "Created $OPSI_ARCHIVE_BUCKET. Review SSE-KMS, bucket IAM and lifecycle policy with security before real ingestion."
