"""Object storage abstraction: S3 in production, a local folder for labs and tests.

S3 writes always set server-side encryption (SSE-KMS when ``OPSI_KMS_KEY_ID`` is
set, else SSE-S3) and a SHA-256 checksum that S3 verifies on receipt. The
bucket policy in infrastructure/aws/s3/bucket-policy.json additionally *denies*
unencrypted or non-TLS uploads, so a misconfigured client fails loudly.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Protocol


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ObjectStore(Protocol):
    def uri(self, key: str) -> str: ...

    def put(self, key: str, data: bytes, *, content_type: str, metadata: dict[str, str]) -> str: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def list(self, prefix: str) -> list[str]: ...


def _ascii_metadata(metadata: dict[str, str]) -> dict[str, str]:
    clean = {}
    for key, value in metadata.items():
        k = "".join(ch for ch in key.lower() if ch.isalnum() or ch == "-")
        v = str(value).encode("ascii", "replace").decode("ascii")[:256]
        clean[k] = v
    return clean


class S3ObjectStore:
    def __init__(self, bucket: str, region: str, kms_key_id: str = "", client=None) -> None:
        if not bucket:
            raise ValueError("OPSI_ARCHIVE_BUCKET is required for S3 storage")
        self.bucket = bucket
        self.kms_key_id = kms_key_id
        if client is None:
            import boto3  # lazily imported so tests without AWS libs still import this module
            from botocore.config import Config

            client = boto3.client("s3", region_name=region,
                                  config=Config(retries={"max_attempts": 8, "mode": "adaptive"}))
        self.client = client

    def uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    def put(self, key: str, data: bytes, *, content_type: str, metadata: dict[str, str]) -> str:
        args = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": data,
            "ContentType": content_type,
            "Metadata": _ascii_metadata(metadata),
            "ChecksumSHA256": base64.b64encode(hashlib.sha256(data).digest()).decode(),
        }
        if self.kms_key_id:
            args.update(ServerSideEncryption="aws:kms", SSEKMSKeyId=self.kms_key_id, BucketKeyEnabled=True)
        else:
            args.update(ServerSideEncryption="AES256")
        self.client.put_object(**args)
        return self.uri(key)

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def list(self, prefix: str) -> list[str]:
        keys: list[str] = []
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return keys


class LocalObjectStore:
    """Writes objects under a directory with atomic renames. For labs, dry-runs and tests only."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("object key escapes the local archive root")
        return path

    def uri(self, key: str) -> str:
        return f"file://{self._path(key).as_posix()}"

    def put(self, key: str, data: bytes, *, content_type: str, metadata: dict[str, str]) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        meta = {"content_type": content_type, "sha256": sha256_hex(data), **_ascii_metadata(metadata)}
        path.with_name(path.name + ".meta.json").write_text(json.dumps(meta, indent=1))
        return self.uri(key)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        for candidate in (self._path(key), self._path(key + ".meta.json")):
            if candidate.exists():
                candidate.unlink()

    def list(self, prefix: str) -> list[str]:
        base = self.root.resolve()
        return sorted(
            p.relative_to(base).as_posix()
            for p in base.rglob("*")
            if p.is_file() and not p.name.endswith((".meta.json", ".tmp"))
            and p.relative_to(base).as_posix().startswith(prefix)
        )


class DiscardObjectStore:
    """Dry-run sink: measures what would be written, writes nothing."""

    def __init__(self) -> None:
        self.objects: dict[str, int] = {}

    def uri(self, key: str) -> str:
        return f"dryrun://{key}"

    def put(self, key: str, data: bytes, *, content_type: str, metadata: dict[str, str]) -> str:
        self.objects[key] = len(data)
        return self.uri(key)

    def get(self, key: str) -> bytes:
        raise FileNotFoundError("dry-run store holds no data")

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def list(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))


def open_store(settings) -> ObjectStore:
    if settings.local_archive_dir:
        return LocalObjectStore(settings.local_archive_dir)
    return S3ObjectStore(settings.archive_bucket, settings.aws_region, settings.kms_key_id)
