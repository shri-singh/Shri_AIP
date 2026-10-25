"""S3 request parameters, verified with botocore's Stubber (no AWS account, no network).

The Stubber asserts the *exact* parameters we send, which is what matters for
security: SSE must always be requested and a SHA-256 checksum always attached.
"""
import base64
import hashlib

import pytest

boto3 = pytest.importorskip("boto3")
from botocore.stub import ANY, Stubber  # noqa: E402
from opsi_ingest.sinks.objectstore import S3ObjectStore  # noqa: E402

DATA = b"parquet-bytes"
CHECKSUM = base64.b64encode(hashlib.sha256(DATA).digest()).decode()


def _client():
    return boto3.client("s3", region_name="us-west-2", aws_access_key_id="testing", aws_secret_access_key="testing")


def test_sse_s3_and_checksum_are_always_sent():
    client = _client()
    store = S3ObjectStore("opsi-unit", "us-west-2", client=client)
    with Stubber(client) as stub:
        stub.add_response("put_object", {}, {
            "Bucket": "opsi-unit", "Key": "raw/x/part-00000.parquet", "Body": DATA,
            "ContentType": "application/vnd.apache.parquet", "ServerSideEncryption": "AES256",
            "ChecksumSHA256": CHECKSUM, "Metadata": {"schema-version": "opsi.event.v1", "run-id": "r1"},
        })
        uri = store.put("raw/x/part-00000.parquet", DATA, content_type="application/vnd.apache.parquet",
                        metadata={"schema-version": "opsi.event.v1", "run-id": "r1"})
        stub.assert_no_pending_responses()
    assert uri == "s3://opsi-unit/raw/x/part-00000.parquet"


def test_kms_mode_requests_sse_kms_with_bucket_key():
    client = _client()
    store = S3ObjectStore("opsi-unit", "us-west-2", kms_key_id="alias/opsi-archive", client=client)
    with Stubber(client) as stub:
        stub.add_response("put_object", {}, {
            "Bucket": "opsi-unit", "Key": "raw/k.json", "Body": b"{}", "ContentType": "application/json",
            "ServerSideEncryption": "aws:kms", "SSEKMSKeyId": "alias/opsi-archive", "BucketKeyEnabled": True,
            "ChecksumSHA256": ANY, "Metadata": {},
        })
        store.put("raw/k.json", b"{}", content_type="application/json", metadata={})
        stub.assert_no_pending_responses()


def test_metadata_is_ascii_safe():
    client = _client()
    store = S3ObjectStore("opsi-unit", "us-west-2", client=client)
    with Stubber(client) as stub:
        stub.add_response("put_object", {}, {
            "Bucket": "opsi-unit", "Key": "k", "Body": b"x", "ContentType": "t", "ServerSideEncryption": "AES256",
            "ChecksumSHA256": ANY, "Metadata": {"source": "caf?"},
        })
        store.put("k", b"x", content_type="t", metadata={"Source": "café"})
