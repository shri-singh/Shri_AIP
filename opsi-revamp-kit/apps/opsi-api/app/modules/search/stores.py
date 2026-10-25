"""Read models over the curated PostgreSQL tables (opsi_ingest.*), with memory fakes.

Aggregations are *named templates* with fixed SQL. The LLM picks a template and
parameters; it never writes SQL. Add a template = add SQL here + a test.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from ..identity.principal import Principal

AGG_TEMPLATES: dict[str, str] = {
    "error_counts_by_service": """
        SELECT service_id, sum(event_count)::bigint AS events, count(DISTINCT fingerprint) AS signatures
        FROM opsi_ingest.error_signature_windows
        WHERE window_start >= %(time_from)s AND window_start < %(time_to)s
          AND (%(services)s::text[] IS NULL OR service_id = ANY(%(services)s::text[]))
        GROUP BY service_id ORDER BY events DESC LIMIT %(limit)s""",
    "top_error_signatures": """
        SELECT service_id, fingerprint, max(sample_message) AS sample_message, min(sample_ref) AS sample_ref,
               sum(event_count)::bigint AS events, min(first_seen) AS first_seen, max(last_seen) AS last_seen
        FROM opsi_ingest.error_signature_windows
        WHERE window_start >= %(time_from)s AND window_start < %(time_to)s
          AND (%(services)s::text[] IS NULL OR service_id = ANY(%(services)s::text[]))
        GROUP BY service_id, fingerprint ORDER BY events DESC LIMIT %(limit)s""",
    "error_trend_hourly": """
        SELECT date_trunc('hour', window_start) AS hour, sum(event_count)::bigint AS events
        FROM opsi_ingest.error_signature_windows
        WHERE window_start >= %(time_from)s AND window_start < %(time_to)s
          AND (%(services)s::text[] IS NULL OR service_id = ANY(%(services)s::text[]))
        GROUP BY 1 ORDER BY 1 LIMIT %(limit)s""",
    "problems_by_status": """
        SELECT status, severity_level, count(*) AS problems
        FROM opsi_ingest.problems
        WHERE start_time >= %(time_from)s AND start_time < %(time_to)s
          AND (%(services)s::text[] IS NULL OR root_cause_entity_id = ANY(%(services)s::text[])
               OR affected_entity_ids ?| %(services)s::text[])
        GROUP BY status, severity_level ORDER BY problems DESC LIMIT %(limit)s""",
}


class IncidentStore(Protocol):
    async def search_problems(self, p: Principal, q: str | None, services: list[str] | None,
                              time_from: datetime, time_to: datetime, limit: int) -> list[dict[str, Any]]: ...

    async def aggregate(self, p: Principal, template: str, services: list[str] | None,
                        time_from: datetime, time_to: datetime, limit: int) -> list[dict[str, Any]]: ...


class PgIncidentStore:
    def __init__(self, db) -> None:
        self.db = db

    async def search_problems(self, p, q, services, time_from, time_to, limit):
        sql = """
            SELECT problem_id, display_id, title, status, severity_level, start_time, end_time,
                   root_cause_entity_id, affected_entity_ids, evidence_ref,
                   CASE WHEN %(q)s::text IS NULL THEN 0
                        ELSE ts_rank(search_tsv, websearch_to_tsquery('simple', %(q)s)) END AS rank
            FROM opsi_ingest.problems
            WHERE start_time >= %(time_from)s AND start_time < %(time_to)s
              AND (%(q)s::text IS NULL OR search_tsv @@ websearch_to_tsquery('simple', %(q)s))
              AND (%(services)s::text[] IS NULL OR root_cause_entity_id = ANY(%(services)s::text[])
                   OR affected_entity_ids ?| %(services)s::text[])
            ORDER BY rank DESC, start_time DESC LIMIT %(limit)s"""
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute(sql, {"q": q, "services": services, "time_from": time_from,
                                           "time_to": time_to, "limit": limit})
            return list(await cur.fetchall())

    async def aggregate(self, p, template, services, time_from, time_to, limit):
        sql = AGG_TEMPLATES[template]  # KeyError impossible: template is validated by the route's Literal type
        async with self.db.tenant_tx(p) as conn:
            cur = await conn.execute(sql, {"services": services, "time_from": time_from, "time_to": time_to,
                                           "limit": limit})
            return list(await cur.fetchall())


class MemoryIncidentStore:
    """Fake for tests/lab: rows are dicts that include tenant_id."""

    def __init__(self, problems: list[dict[str, Any]] | None = None, aggregates: dict[str, list[dict]] | None = None):
        self.problems = problems or []
        self.aggregates = aggregates or {}
        self.calls: list[tuple] = []

    async def search_problems(self, p, q, services, time_from, time_to, limit):
        self.calls.append(("search_problems", q, services, time_from, time_to, limit))
        out = []
        for row in self.problems:
            if row["tenant_id"] != p.tenant_id or not (time_from <= row["start_time"] < time_to):
                continue
            if q and not all(w in row["title"].lower() for w in q.lower().split()):
                continue
            if services and row.get("root_cause_entity_id") not in services and \
                    not set(row.get("affected_entity_ids", [])) & set(services):
                continue
            out.append({k: v for k, v in row.items() if k != "tenant_id"})
        return out[:limit]

    async def aggregate(self, p, template, services, time_from, time_to, limit):
        self.calls.append(("aggregate", template, services, time_from, time_to, limit))
        return [r for r in self.aggregates.get(template, []) if r.get("tenant_id", p.tenant_id) == p.tenant_id][:limit]
