"""Chat attachments: browser -> S3 directly via short-lived presigned POST, never through the API.

Flow:
1. ``init``     - API validates name/type/size, creates a row (status pending_upload) and returns
                  a presigned POST whose *policy* pins the key, the exact Content-Type, a
                  content-length range and server-side encryption. Expires in 5 minutes.
2. browser POSTs the file to S3.
3. ``finalize`` - API HEADs the object (size/type must match), marks it ``uploaded``.
4. Malware scan - GuardDuty Malware Protection for S3 scans the object and tags it
                  ``GuardDutyMalwareScanStatus`` (NO_THREATS_FOUND / THREATS_FOUND / ...).
                  Verify the tag key/values in your account; adjust ``SCAN_TAG`` if needed.
5. ``download`` - only ``clean`` objects get a 60-second presigned GET with
                  ``Content-Disposition: attachment`` (never rendered inline by S3).

Object keys contain ids only (no filenames, no user text): filenames can carry PII.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import anyio

from .._shared.errors import BadRequest, Conflict, NotFound
from .._shared.settings import ApiSettings
from ..identity.principal import Principal
from .models import Attachment, AttachmentInitIn, AttachmentInitOut
from .repository import ChatRepository

SCAN_TAG = "GuardDutyMalwareScanStatus"
SCAN_RESULTS = {"NO_THREATS_FOUND": "clean", "THREATS_FOUND": "infected"}


class AttachmentService:
    def __init__(self, settings: ApiSettings, repo: ChatRepository, s3_client: Any | None = None) -> None:
        self.settings = settings
        self.repo = repo
        self._s3 = s3_client

    @property
    def s3(self) -> Any:
        if self._s3 is None:
            import boto3
            from botocore.config import Config

            # SigV4 is mandatory: SigV2 presigned URLs are deprecated and fail for SSE-KMS objects.
            self._s3 = boto3.client("s3", region_name=self.settings.aws_region,
                                    config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}))
        return self._s3

    def _sse_fields(self) -> dict[str, str]:
        if self.settings.attachments_kms_key_id:
            return {"x-amz-server-side-encryption": "aws:kms",
                    "x-amz-server-side-encryption-aws-kms-key-id": self.settings.attachments_kms_key_id}
        return {"x-amz-server-side-encryption": "AES256"}

    async def init(self, p: Principal, thread_id: uuid.UUID, body: AttachmentInitIn) -> AttachmentInitOut:
        s = self.settings
        if not s.attachments_bucket:
            raise BadRequest("attachments are not configured")
        if body.mime_type not in s.attachments_allowed_mime:
            raise BadRequest(f"file type {body.mime_type} is not allowed")
        if body.size_bytes > s.attachments_max_bytes:
            raise BadRequest(f"file exceeds {s.attachments_max_bytes} bytes")
        attachment_id = uuid.uuid4()
        key = f"{s.attachments_prefix}/tenant={p.tenant_id}/thread={thread_id}/{attachment_id}"
        att = Attachment(id=attachment_id, thread_id=thread_id, owner_id=p.user_id, s3_key=key,
                         filename=body.filename, mime_type=body.mime_type, size_bytes=body.size_bytes,
                         status="pending_upload", created_at=datetime.now(timezone.utc))
        try:
            await self.repo.create_attachment(p, att)
        except LookupError:
            raise NotFound("thread") from None
        fields = {"Content-Type": body.mime_type, **self._sse_fields()}
        conditions: list[Any] = [{"Content-Type": body.mime_type},
                                 ["content-length-range", 1, min(body.size_bytes, s.attachments_max_bytes)]]
        conditions += [{k: v} for k, v in self._sse_fields().items()]
        post = self.s3.generate_presigned_post(Bucket=s.attachments_bucket, Key=key, Fields=fields,
                                               Conditions=conditions, ExpiresIn=s.attachments_upload_ttl_s)
        return AttachmentInitOut(attachment_id=attachment_id, upload_url=post["url"], fields=post["fields"],
                                 expires_in=s.attachments_upload_ttl_s)

    async def finalize(self, p: Principal, attachment_id: uuid.UUID) -> Attachment:
        att = await self._owned(p, attachment_id)
        if att.status != "pending_upload":
            raise Conflict(f"attachment is already {att.status}")
        try:
            head = await anyio.to_thread.run_sync(
                lambda: self.s3.head_object(Bucket=self.settings.attachments_bucket, Key=att.s3_key))
        except Exception:  # noqa: BLE001 - ClientError 404 etc.
            raise Conflict("upload not found in storage; retry the upload") from None
        size, ctype = head.get("ContentLength"), head.get("ContentType")
        if ctype != att.mime_type or not size or size > self.settings.attachments_max_bytes:
            await self.repo.update_attachment(p, attachment_id, status="rejected", scan_detail="type/size mismatch")
            raise BadRequest("uploaded object does not match the declared type/size")
        status = "uploaded" if self.settings.attachments_scan_mode == "guardduty" else "clean"
        await self.repo.update_attachment(p, attachment_id, status=status, size_bytes=size,
                                          finalized_at=datetime.now(timezone.utc))
        return att.model_copy(update={"status": status, "size_bytes": size})

    async def refresh_scan_status(self, p: Principal, att: Attachment) -> str:
        if att.status != "uploaded" or self.settings.attachments_scan_mode != "guardduty":
            return att.status
        response = await anyio.to_thread.run_sync(
            lambda: self.s3.get_object_tagging(Bucket=self.settings.attachments_bucket, Key=att.s3_key))
        tags = response.get("TagSet", [])
        value = next((t["Value"] for t in tags if t.get("Key") == SCAN_TAG), None)
        if value is None:
            return "uploaded"  # scan still pending
        status = SCAN_RESULTS.get(value, "scan_error")
        await self.repo.update_attachment(p, att.id, status=status, scan_detail=value)
        return status

    async def download_url(self, p: Principal, attachment_id: uuid.UUID) -> dict[str, Any]:
        att = await self.repo.get_attachment(p, attachment_id)
        if not att:
            raise NotFound("attachment")
        status = await self.refresh_scan_status(p, att) if att.owner_id == p.user_id else att.status
        if status != "clean":
            raise Conflict(f"attachment not available (status: {status})")
        safe_name = "".join(ch for ch in att.filename if ch.isalnum() or ch in "._- ")[:100] or "attachment"
        url = self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.settings.attachments_bucket, "Key": att.s3_key,
                    "ResponseContentDisposition": f'attachment; filename="{safe_name}"',
                    "ResponseContentType": att.mime_type},
            ExpiresIn=self.settings.attachments_download_ttl_s,
        )
        return {"url": url, "expires_in": self.settings.attachments_download_ttl_s, "filename": att.filename}

    async def _owned(self, p: Principal, attachment_id: uuid.UUID) -> Attachment:
        att = await self.repo.get_attachment(p, attachment_id)
        if not att or att.owner_id != p.user_id:
            raise NotFound("attachment")
        return att
