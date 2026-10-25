"""exact_logs: lexical search over the EXISTING Elasticsearch log cluster (read-only).

The model chooses words, service and time window; it never chooses the index.
Indices come from SEARCH_ELASTIC_TENANT_INDEX_MAP_JSON (per tenant) and must
match SEARCH_ELASTIC_INDEX_ALLOWLIST. ``simple_query_string`` is used with
prefix/fuzzy/regexp/wildcard operators disabled, so a query cannot trigger
expensive leading-wildcard scans; results are capped and sorted by time.
"""
from __future__ import annotations

import fnmatch
from datetime import timedelta
from typing import ClassVar, Literal

from pydantic import Field

from ..._shared.redaction import Redactor
from ..._shared.settings import ApiSettings
from ..clients import ElasticReadClient
from ..contracts import Citation, RouteContext, RouteResult, TimeWindowArgs, scoped_services


class ExactLogsArgs(TimeWindowArgs):
    query: str | None = Field(default=None, max_length=200,
                              description="Words/phrases to match in the log message, e.g. \"timeout\" payment")
    service_id: str | None = Field(default=None, max_length=200, description="Service name to filter on")
    levels: list[Literal["error", "warn", "info", "debug", "fatal", "critical"]] | None = Field(default=None, max_length=6)
    limit: int = Field(default=20, ge=1, le=50)

    MAX_SPAN: ClassVar[timedelta] = timedelta(hours=24)


class ExactLogsRoute:
    name = "exact_logs"
    description = ("Search raw application logs (Elasticsearch) for exact messages in a time window (max 24h). "
                   "Use for error messages, stack traces, request ids. Returns newest first.")
    args_model = ExactLogsArgs
    permission = "search:use"
    cost_units = 3.0
    timeout_seconds = 15.0
    max_items = 50

    def __init__(self, settings: ApiSettings, client: ElasticReadClient) -> None:
        self.s = settings
        self.client = client
        self.redactor = Redactor("strict")

    def _indices(self, tenant_id: str) -> list[str]:
        indices = self.s.elastic_tenant_index_map.get(tenant_id) or list(self.s.elastic_index_allowlist)
        allowed = [i for i in indices if any(fnmatch.fnmatch(i, pat) for pat in self.s.elastic_index_allowlist)]
        if not allowed:
            raise PermissionError("no log indices are configured for your tenant")
        return allowed

    def build_body(self, args: ExactLogsArgs, services: list[str] | None) -> dict:
        ts, svc, msg = self.s.elastic_timestamp_field, self.s.elastic_service_field, self.s.elastic_message_field
        filters: list[dict] = [{"range": {ts: {"gte": args.time_from.isoformat(), "lt": args.time_to.isoformat()}}}]
        if services:
            filters.append({"terms": {svc: services}})
        if args.levels:
            filters.append({"terms": {"log.level": [lv for lv in args.levels] + [lv.upper() for lv in args.levels]}})
        must = []
        if args.query:
            must.append({"simple_query_string": {"query": args.query, "fields": [msg], "default_operator": "and",
                                                 "flags": "AND|OR|NOT|PHRASE|PRECEDENCE|WHITESPACE|ESCAPE"}})
        return {"size": args.limit, "timeout": "10s", "track_total_hits": 10_000,
                "_source": list(self.s.elastic_source_fields), "sort": [{ts: {"order": "desc"}}],
                "query": {"bool": {"filter": filters, "must": must}}}

    async def run(self, args: ExactLogsArgs, ctx: RouteContext) -> RouteResult:
        services = scoped_services(ctx.principal, args.service_id)
        body = await self.client.search(self._indices(ctx.principal.tenant_id), self.build_body(args, services))
        hits = (body.get("hits") or {}).get("hits") or []
        total = ((body.get("hits") or {}).get("total") or {}).get("value")
        items, citations = [], []
        for hit in hits:
            src = hit.get("_source") or {}
            message = self.redactor.redact_text(str(_get(src, self.s.elastic_message_field) or "")).text[:500]
            when = _get(src, self.s.elastic_timestamp_field)
            citations.append(Citation(source_type="elastic_log",
                                      source_ref=f"elastic://{hit.get('_index')}/_doc/{hit.get('_id')}",
                                      title=f"{_get(src, self.s.elastic_service_field) or 'log'} @ {when}",
                                      event_time=when, snippet=message[:300]))
            items.append({"time": when, "service": _get(src, self.s.elastic_service_field),
                          "level": _get(src, "log.level"), "host": _get(src, "host.name"),
                          "trace_id": _get(src, "trace.id"), "message": message, "citation": len(citations) - 1})
        notes = [] if not body.get("timed_out") else ["search timed out on some shards; results may be partial"]
        return RouteResult(route=self.name, items=items, citations=citations, total_hint=total,
                           truncated=bool(total and total > len(items)), notes=notes)


def _get(src: dict, path: str):
    if path in src:
        return src[path]
    node = src
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node
