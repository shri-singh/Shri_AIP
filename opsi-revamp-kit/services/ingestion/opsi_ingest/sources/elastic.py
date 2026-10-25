"""Elasticsearch adapter: point-in-time (PIT) + ``search_after`` with a deterministic sort.

Why not ``helpers.scan``/scroll (as in the starter)? Scroll gives no stable
ordering guarantee you can resume from and holds heavier search contexts. PIT
+ ``search_after`` sorted by ``[timestamp, _shard_doc]`` gives a consistent
snapshot and a total order inside the window.

CLIENT VERSION: the Python client major must match the *cluster* major.
``elasticsearch`` 9.x clients do NOT work against 8.x clusters (they send
``compatible-with=9``). Pin ``elasticsearch>=8.15,<9`` for an 8.x cluster.
Check with ``curl -s $ELASTIC_URL`` -> ``version.number`` (needs auth).

Required privileges (least privilege): ``read`` and ``view_index_metadata`` on
the index pattern. PIT needs ``read``. No write/manage privileges.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

from ..config import Settings
from ..errors import ConfigError, PermanentSourceError, TransientSourceError, WindowTooLarge
from ..timeutil import iso_z
from ..windows import Window
from .base import FieldMap, SourceRecord

log = logging.getLogger(__name__)

PIT_KEEP_ALIVE = "2m"


class ElasticSource:
    name = "elastic"
    dataset = "logs"
    window_semantics = "event_time"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        self.index = settings.elastic_index_pattern
        self.ts_field = settings.elastic_timestamp_field
        self.page_size = settings.elastic_page_size
        self.cap = settings.elastic_max_docs_per_window
        self.extra_filter = _parse_filter(settings.elastic_query_filter_json)
        self.field_map = FieldMap(
            time=(self.ts_field, "@timestamp", "timestamp"),
            severity=("log.level", "level", "severity", "loglevel"),
            status=("event.outcome", "http.response.status_code"),
            service=("service.name", "kubernetes.labels.app", "service", "app"),
            host=("host.name", "host.hostname", "kubernetes.pod.name"),
            trace=("trace.id", "trace_id", "traceId"),
            title=("error.type", "event.action"),
            message=("message", "error.message", "log.original"),
        )
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            self.settings.require("elastic_url")
            try:
                from elasticsearch import Elasticsearch
            except ImportError as exc:  # pragma: no cover - dependency guard
                raise ConfigError("pip install 'elasticsearch>=8.15,<9' (match your cluster major)") from exc
            kwargs: dict[str, Any] = {"hosts": [self.settings.elastic_url], "request_timeout": 120,
                                      "retry_on_timeout": True, "max_retries": 3}
            if self.settings.elastic_ca_certs:
                kwargs["ca_certs"] = self.settings.elastic_ca_certs
            if self.settings.elastic_api_key:
                kwargs["api_key"] = self.settings.elastic_api_key
            elif self.settings.elastic_username:
                kwargs["basic_auth"] = (self.settings.elastic_username, self.settings.elastic_password)
            else:
                raise ConfigError("set ELASTIC_API_KEY (preferred) or ELASTIC_USERNAME/ELASTIC_PASSWORD")
            self._client = Elasticsearch(**kwargs)
        return self._client

    def _query(self, window: Window) -> dict[str, Any]:
        filters: list[dict[str, Any]] = [
            {"range": {self.ts_field: {"gte": iso_z(window.start), "lt": iso_z(window.end),
                                       "format": "strict_date_optional_time_nanos"}}}
        ]
        if self.extra_filter:
            filters.append(self.extra_filter)
        return {"bool": {"filter": filters}}

    def fetch(self, window: Window) -> Iterator[SourceRecord]:
        client = self.client
        try:
            pit_id = client.open_point_in_time(index=self.index, keep_alive=PIT_KEEP_ALIVE)["id"]
        except Exception as exc:  # noqa: BLE001 - classify vendor errors without leaking details
            raise _classify(exc, "open_point_in_time") from None
        fetched = 0
        search_after: list[Any] | None = None
        try:
            while True:
                kwargs: dict[str, Any] = {
                    "pit": {"id": pit_id, "keep_alive": PIT_KEEP_ALIVE},
                    "size": self.page_size,
                    "query": self._query(window),
                    "sort": [
                        {self.ts_field: {"order": "asc", "format": "strict_date_optional_time_nanos"}},
                        {"_shard_doc": "asc"},
                    ],
                    "track_total_hits": False,
                }
                if self.settings.elastic_source_includes:
                    kwargs["source"] = {"includes": list(self.settings.elastic_source_includes)}
                if search_after is not None:
                    kwargs["search_after"] = search_after
                try:
                    response = client.search(**kwargs)
                except Exception as exc:  # noqa: BLE001
                    raise _classify(exc, "search") from None
                body = response.body if hasattr(response, "body") else response
                pit_id = body.get("pit_id", pit_id)
                hits = body.get("hits", {}).get("hits", [])
                if not hits:
                    return
                for hit in hits:
                    fetched += 1
                    if fetched > self.cap:
                        raise WindowTooLarge(
                            f"elastic window {window} exceeded ELASTIC_MAX_DOCS_PER_WINDOW={self.cap}"
                        )
                    index_name, doc_id = hit.get("_index", ""), hit.get("_id", "")
                    yield SourceRecord(
                        origin_id=f"{index_name}/{doc_id}" if doc_id else None,
                        payload=hit.get("_source") or {},
                        source_ref=f"elastic://{index_name}/_doc/{doc_id}",
                    )
                search_after = hits[-1].get("sort")
                if search_after is None:
                    raise PermanentSourceError("elastic hits lack 'sort' values; cannot paginate with search_after")
        finally:
            try:
                client.close_point_in_time(id=pit_id)
            except Exception:  # noqa: BLE001 - PIT expires on its own after keep_alive
                log.warning("could not close elastic PIT; it will expire after %s", PIT_KEEP_ALIVE)

    def close(self) -> None:
        if self._client is not None and hasattr(self._client, "close"):
            self._client.close()


def _parse_filter(raw: str) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError("ELASTIC_QUERY_FILTER_JSON is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ConfigError("ELASTIC_QUERY_FILTER_JSON must be a single query object, e.g. {\"terms\": {...}}")
    return value


def _classify(exc: Exception, operation: str) -> Exception:
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "meta", None), "status", None)
    name = type(exc).__name__
    if status in (401, 403):
        return PermanentSourceError(f"elastic {operation}: HTTP {status} - check API key privileges (read, view_index_metadata)")
    if status == 400:
        return PermanentSourceError(
            f"elastic {operation}: HTTP 400 - query rejected; if the message mentions 'compatible-with', "
            "your client major does not match the cluster major"
        )
    if status == 404:
        return PermanentSourceError(f"elastic {operation}: HTTP 404 - index pattern matched nothing or PIT expired")
    return TransientSourceError(f"elastic {operation} failed: {name}{f' HTTP {status}' if status else ''}")
