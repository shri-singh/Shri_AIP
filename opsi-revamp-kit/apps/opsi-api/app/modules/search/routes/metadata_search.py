"""metadata_search: ownership, tags, domains and schema from OpenMetadata (catalog)."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ...catalog.openmetadata import OpenMetadataClient
from ..contracts import Citation, RouteArgs, RouteContext, RouteResult


class MetadataSearchArgs(RouteArgs):
    query: str | None = Field(default=None, max_length=200, description="Free text, e.g. 'orders table payments'")
    fqn: str | None = Field(default=None, max_length=500,
                            description="Exact fully qualified table name when known (service.database.schema.table)")
    entity_type: Literal["table", "dashboard", "pipeline", "topic", "glossaryTerm"] = "table"
    include_lineage: bool = False
    limit: int = Field(default=5, ge=1, le=10)

    @model_validator(mode="after")
    def _one_of(self) -> MetadataSearchArgs:
        if not (self.query or self.fqn):
            raise ValueError("provide query or fqn")
        return self


class MetadataSearchRoute:
    name = "metadata_search"
    description = ("Look up data assets in the OpenMetadata catalog: owners/teams, domains, tags (e.g. PII), "
                   "description, columns and optionally data lineage. Not for incident causality.")
    args_model = MetadataSearchArgs
    permission = "catalog:read"
    cost_units = 1.0
    timeout_seconds = 10.0
    max_items = 10

    def __init__(self, client: OpenMetadataClient) -> None:
        self.client = client

    async def run(self, args: MetadataSearchArgs, ctx: RouteContext) -> RouteResult:
        if args.fqn and args.entity_type == "table":
            found = await self.client.get_table(args.fqn)
            entities = [found] if found else []
        else:
            entities = await self.client.search(args.query or args.fqn or "", args.entity_type, args.limit)
        items, citations = [], []
        for ent in entities:
            fqn = ent.get("fqn") or ent.get("name") or "unknown"
            citations.append(Citation(source_type="om_entity", source_ref=f"om://{args.entity_type}/{fqn}",
                                      title=f"{args.entity_type} {fqn}", snippet=(ent.get("description") or "")[:300],
                                      url=self.client.ui_url(args.entity_type, fqn)))
            item = {**ent, "citation": len(citations) - 1}
            if args.include_lineage and args.entity_type == "table" and ent.get("fqn"):
                item["lineage"] = await self.client.lineage("table", ent["fqn"])
            items.append(item)
        notes = [] if items else ["no catalog entity matched"]
        return RouteResult(route=self.name, items=items, citations=citations, notes=notes)
