"""Chat API models. Identity fields (tenant/owner) are never accepted from clients."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Role = Literal["user", "assistant", "tool", "system", "developer", "activity", "reasoning"]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown fields (e.g. tenant_id) are rejected, not ignored


class FolderIn(_In):
    name: str = Field(min_length=1, max_length=120)
    parent_id: uuid.UUID | None = None


class Folder(BaseModel):
    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None = None
    created_at: datetime


class ThreadCreate(_In):
    id: uuid.UUID | None = None  # client may pre-generate the AG-UI threadId (must be a UUID)
    title: str | None = Field(default=None, max_length=300)
    folder_id: uuid.UUID | None = None
    linked_incident_id: str | None = Field(default=None, max_length=200)
    linked_service_id: str | None = Field(default=None, max_length=200)


class ThreadUpdate(_In):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    folder_id: uuid.UUID | None = None
    clear_folder: bool = False
    visibility: Literal["private", "tenant"] | None = None
    archived: bool | None = None


class Thread(BaseModel):
    id: uuid.UUID
    owner_id: str
    title: str
    agent_id: str = "opsi-investigator"
    folder_id: uuid.UUID | None = None
    visibility: Literal["private", "tenant"] = "private"
    linked_incident_id: str | None = None
    linked_service_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None = None
    archived_at: datetime | None = None


class ThreadQuery(_In):
    folder_id: uuid.UUID | None = None
    tag: str | None = Field(default=None, max_length=64)
    q: str | None = Field(default=None, max_length=200)
    incident_id: str | None = Field(default=None, max_length=200)
    include_archived: bool = False
    include_shared: bool = False
    limit: int = Field(default=50, ge=1, le=200)
    before: datetime | None = None  # keyset pagination on last_message_at


class StoredMessage(BaseModel):
    """A persisted AG-UI message. ``content_json`` is the wire (camelCase) form."""

    message_id: str = Field(max_length=128)
    role: Role
    content_text: str | None = None
    content_json: dict[str, Any]
    run_id: str | None = None
    author_id: str
    created_at: datetime | None = None


class TagIn(_In):
    name: str = Field(min_length=1, max_length=64)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class Tag(BaseModel):
    id: uuid.UUID
    name: str
    color: str | None = None


class ThreadTagsIn(_In):
    tag_ids: list[uuid.UUID] = Field(max_length=20)


class SearchHit(BaseModel):
    thread_id: uuid.UUID
    thread_title: str
    message_id: str | None = None
    snippet: str
    at: datetime | None = None


class Evidence(BaseModel):
    citation_key: str
    source_type: str
    source_ref: str
    title: str | None = None
    event_time: datetime | None = None
    snippet: str | None = None
    url: str | None = None
    message_id: str | None = None


class FeedbackIn(_In):
    message_id: str = Field(max_length=128)
    rating: Literal[-1, 1]
    reason_code: Literal["wrong", "incomplete", "bad_citation", "unsafe", "slow", "helpful", "other"] | None = None
    comment: str | None = Field(default=None, max_length=2000)


class AttachmentInitIn(_In):
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(max_length=100)
    size_bytes: int = Field(gt=0)

    @field_validator("filename")
    @classmethod
    def _safe_name(cls, value: str) -> str:
        if any(ch in value for ch in "/\\\x00") or value in (".", ".."):
            raise ValueError("filename must not contain path separators")
        return value


class AttachmentInitOut(BaseModel):
    attachment_id: uuid.UUID
    upload_url: str
    fields: dict[str, str]
    expires_in: int


class Attachment(BaseModel):
    id: uuid.UUID
    thread_id: uuid.UUID
    owner_id: str
    s3_key: str
    filename: str
    mime_type: str
    size_bytes: int | None = None
    status: str
    message_id: str | None = None
    created_at: datetime
