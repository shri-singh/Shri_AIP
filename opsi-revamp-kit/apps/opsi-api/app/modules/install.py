"""One call to graft the revamp onto an existing FastAPI app without touching its routes.

    from app.modules.install import build_services, install_revamp
    install_revamp(app, await build_services(get_settings()))

``build_services`` wires real backends from settings; every backend is optional
and its route is simply not registered when unconfigured (e.g. no Elastic URL ->
no ``exact_logs`` tool). Tests and the lab app pass their own container instead.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from ._shared.audit import LogAuditSink, PgAuditSink
from ._shared.container import OpsiServices
from ._shared.db import Database
from ._shared.settings import ApiSettings
from ._shared.telemetry import instrument_fastapi, setup_tracing
from .agents.agui_endpoint import router as agents_router
from .agents.approvals import MemoryApprovalStore, PgApprovalStore
from .agents.approvals import router as actions_router
from .catalog.openmetadata import OpenMetadataClient
from .catalog.router import router as catalog_router
from .chat.attachments import AttachmentService
from .chat.repository import MemoryChatRepository
from .chat.router import router as chat_router
from .llm.gateway import PortkeyGateway
from .ontology.repository import MemoryOntologyRepository, PgOntologyRepository
from .ontology.router import router as ontology_router
from .search.clients import ElasticReadClient
from .search.router import SearchRouter
from .search.routes.exact_logs import ExactLogsRoute
from .search.routes.historical_incidents import HistoricalIncidentRoute
from .search.routes.metadata_search import MetadataSearchRoute
from .search.routes.service_graph import ServiceGraphRoute
from .search.routes.sql_aggregation import SqlAggregationRoute
from .search.routes.vector_knowledge import PgKnowledgeStore, VectorKnowledgeRoute
from .search.stores import MemoryIncidentStore, PgIncidentStore
from .voice.router import router as voice_router

log = logging.getLogger(__name__)
ROUTERS = (chat_router, agents_router, actions_router, catalog_router, ontology_router, voice_router)


def install_revamp(app: FastAPI, container: OpsiServices, *, tracing: bool = False) -> None:
    container.settings.assert_safe_for_env()
    app.state.opsi = container
    for router in ROUTERS:
        app.include_router(router)
    if tracing:
        setup_tracing("opsi-api")
        instrument_fastapi(app)

    @app.get("/api/v2/healthz", include_in_schema=False)
    async def healthz() -> dict:
        return {"status": "ok", "routes": container.search.names, "llm": container.llm.model_ref}


async def build_services(settings: ApiSettings) -> OpsiServices:
    """Production wiring. Requires OPSI_API_DATABASE_URL; other backends are optional."""
    db = Database(settings.database_url, min_size=settings.db_pool_min, max_size=settings.db_pool_max,
                  statement_timeout_ms=settings.db_statement_timeout_ms, set_role=settings.db_set_role or None)
    await db.open()
    from .chat.repository_pg import PgChatRepository

    chat = PgChatRepository(db)
    incidents = PgIncidentStore(db)
    ontology = PgOntologyRepository(db)
    llm = PortkeyGateway(settings)
    search = SearchRouter()
    search.register(HistoricalIncidentRoute(incidents))
    search.register(SqlAggregationRoute(incidents))
    search.register(ServiceGraphRoute(ontology))
    om = None
    if settings.elastic_url:
        search.register(ExactLogsRoute(settings, ElasticReadClient(settings.elastic_url, settings.elastic_api_key,
                                                                   settings.elastic_ca_certs)))
    if settings.openmetadata_url and settings.openmetadata_token:
        om = OpenMetadataClient(settings.openmetadata_url, settings.openmetadata_token, settings.openmetadata_ca_certs)
        search.register(MetadataSearchRoute(om))
    if settings.vector_enabled:
        search.register(VectorKnowledgeRoute(llm, PgKnowledgeStore(db)))
    extras: dict = {"approvals": PgApprovalStore(db), "db": db}
    if settings.voice_enabled:
        from .voice.service import VoiceService

        extras["voice"] = VoiceService(bucket=settings.attachments_bucket, region=settings.aws_region)
    log.info("revamp services ready: routes=%s", search.names)
    return OpsiServices(settings=settings, chat=chat, attachments=AttachmentService(settings, chat),
                        audit=PgAuditSink(db), search=search, llm=llm, ontology=ontology, openmetadata=om,
                        extras=extras)


def build_memory_services(settings: ApiSettings, llm, *, incidents: MemoryIncidentStore | None = None,
                          ontology: MemoryOntologyRepository | None = None, s3_client=None,
                          extra_routes: list | None = None) -> OpsiServices:
    """In-memory wiring for tests and the lab demo (no database, no AWS)."""
    chat = MemoryChatRepository()
    incidents = incidents or MemoryIncidentStore()
    ontology = ontology or MemoryOntologyRepository()
    search = SearchRouter()
    search.register(HistoricalIncidentRoute(incidents))
    search.register(SqlAggregationRoute(incidents))
    search.register(ServiceGraphRoute(ontology))
    for route in extra_routes or []:
        search.register(route)
    return OpsiServices(settings=settings, chat=chat, attachments=AttachmentService(settings, chat, s3_client),
                        audit=LogAuditSink(), search=search, llm=llm, ontology=ontology,
                        extras={"approvals": MemoryApprovalStore()})
