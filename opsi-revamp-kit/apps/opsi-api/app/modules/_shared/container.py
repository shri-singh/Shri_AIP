"""Service container stored on ``app.state.opsi`` and fetched by routers via ``Depends(services)``.

Build it once at startup (see app/main_example.py). Tests build it with in-memory
fakes, which is why nothing in the routers instantiates clients directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fastapi import Request

if TYPE_CHECKING:  # pragma: no cover
    from ..catalog.openmetadata import OpenMetadataClient
    from ..chat.attachments import AttachmentService
    from ..chat.repository import ChatRepository
    from ..llm.gateway import LLMGateway
    from ..ontology.repository import OntologyRepository
    from ..search.router import SearchRouter
    from .audit import AuditSink
    from .settings import ApiSettings


@dataclass
class OpsiServices:
    settings: ApiSettings
    chat: ChatRepository
    attachments: AttachmentService
    audit: AuditSink
    search: SearchRouter
    llm: LLMGateway
    ontology: OntologyRepository | None = None
    openmetadata: OpenMetadataClient | None = None
    extras: dict[str, Any] | None = None


def services(request: Request) -> OpsiServices:
    container = getattr(request.app.state, "opsi", None)
    if container is None:
        raise RuntimeError("app.state.opsi is not initialised; call install_revamp(app, services) at startup")
    return container
