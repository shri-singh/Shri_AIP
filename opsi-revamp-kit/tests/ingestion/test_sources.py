from dataclasses import replace
from datetime import datetime, timezone

import pytest
from opsi_ingest.errors import (
    ConfigError,
    NotImplementedSource,
    PermanentSourceError,
    SourceContractError,
    TransientSourceError,
    WindowTooLarge,
)
from opsi_ingest.sources.broadcom_oi import BroadcomOISource
from opsi_ingest.sources.dynatrace_auth import DynatraceTokenProvider
from opsi_ingest.sources.dynatrace_grail import DynatraceGrailSource, validate_dql
from opsi_ingest.sources.dynatrace_problems import DynatraceProblemsSource
from opsi_ingest.sources.elastic import ElasticSource
from opsi_ingest.windows import Window

from .fakes import ScriptedSession, fixture_json, make_response

UTC = timezone.utc
W = Window(datetime(2024, 10, 24, 10, 0, tzinfo=UTC), datetime(2024, 10, 24, 10, 5, tzinfo=UTC))


# --------------------------------------------------------------------------- Elastic
class FakeElastic:
    def __init__(self, pages, fail_search=None):
        self.pages = list(pages)
        self.search_calls = []
        self.closed = []
        self.fail_search = fail_search

    def open_point_in_time(self, index, keep_alive):
        self.index = index
        return {"id": "SYNTHETIC-PIT-0"}

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        if self.fail_search:
            raise self.fail_search
        return self.pages.pop(0) if self.pages else {"pit_id": "SYNTHETIC-PIT-END", "hits": {"hits": []}}

    def close_point_in_time(self, id):
        self.closed.append(id)


def test_elastic_pit_search_after_pagination(settings):
    fake = FakeElastic([fixture_json("elastic_hits_page1.json"), fixture_json("elastic_hits_page2.json")])
    source = ElasticSource(replace(settings, elastic_page_size=2), client=fake)
    records = list(source.fetch(W))
    assert [r.origin_id for r in records] == [".ds-logs-checkout-2024.10.24-000001/doc-1",
                                              ".ds-logs-checkout-2024.10.24-000001/doc-2",
                                              ".ds-logs-checkout-2024.10.24-000001/doc-3"]
    first, second = fake.search_calls[0], fake.search_calls[1]
    assert "search_after" not in first and second["search_after"] == ["2024-10-24T10:01:00.000Z", 12]
    assert second["pit"]["id"] == "SYNTHETIC-PIT-1"  # always use the latest pit_id returned
    assert first["sort"][1] == {"_shard_doc": "asc"}
    rng = first["query"]["bool"]["filter"][0]["range"]["@timestamp"]
    assert rng["gte"] == "2024-10-24T10:00:00Z" and rng["lt"] == "2024-10-24T10:05:00Z"  # half-open window
    assert fake.closed == ["SYNTHETIC-PIT-END"]


def test_elastic_cap_raises_window_too_large_and_closes_pit(settings):
    fake = FakeElastic([fixture_json("elastic_hits_page1.json"), fixture_json("elastic_hits_page2.json")])
    source = ElasticSource(replace(settings, elastic_max_docs_per_window=2), client=fake)
    with pytest.raises(WindowTooLarge):
        list(source.fetch(W))
    assert fake.closed  # PIT released even on failure


def test_elastic_auth_error_is_permanent(settings):
    class Denied(Exception):
        status_code = 403

    source = ElasticSource(settings, client=FakeElastic([], fail_search=Denied()))
    with pytest.raises(PermanentSourceError, match="403"):
        list(source.fetch(W))


def test_elastic_rejects_non_object_filter(settings):
    with pytest.raises(ConfigError):
        ElasticSource(replace(settings, elastic_query_filter_json="[1,2]"), client=FakeElastic([]))


# --------------------------------------------------------------------------- Problems v2
def test_problems_pagination_sends_only_next_page_key(settings):
    session = ScriptedSession([make_response(429, headers={"Retry-After": "0"}),
                               make_response(200, fixture_json("dynatrace_problems_page1.json")),
                               make_response(200, fixture_json("dynatrace_problems_page2.json"))])
    source = DynatraceProblemsSource(settings, session=session, sleep=lambda s: None)
    records = list(source.fetch(W))
    assert len(records) == 3
    assert records[0].source_ref == "dynatrace-problem://-1111111111111111111_1729764000000V2"
    first, retry, second = session.calls
    assert first["params"]["from"] == str(int(W.start.timestamp() * 1000)) and first["params"]["pageSize"] == 500
    assert retry["params"] == first["params"]
    assert second["params"] == {"nextPageKey": "SYNTHETIC-PAGE-KEY-2"}
    assert first["headers"]["Authorization"].startswith("Api-Token ")


def test_problems_repeated_page_key_aborts(settings):
    page = fixture_json("dynatrace_problems_page1.json")
    session = ScriptedSession([make_response(200, page), make_response(200, page)])
    with pytest.raises(SourceContractError, match="repeated"):
        list(DynatraceProblemsSource(settings, session=session).fetch(W))


def test_problems_unexpected_shape(settings):
    session = ScriptedSession([make_response(200, {"problems": "nope"})])
    with pytest.raises(SourceContractError):
        list(DynatraceProblemsSource(settings, session=session).fetch(W))


# --------------------------------------------------------------------------- Grail
def _token_response(expires=300):
    return make_response(200, {"access_token": "eyJSYNTHETIC.ACCESS.TOKEN", "expires_in": expires,
                               "token_type": "Bearer"})


def test_grail_execute_202_then_poll_until_succeeded(settings):
    session = ScriptedSession([
        _token_response(),
        make_response(202, fixture_json("grail_execute_202.json")),
        make_response(200, fixture_json("grail_poll_running.json")),
        make_response(200, fixture_json("grail_poll_succeeded.json")),
    ])
    source = DynatraceGrailSource(settings, session=session, sleep=lambda s: None)
    records = list(source.fetch(W))
    assert len(records) == 2 and records[0].origin_id is None
    token_call, execute, poll1, poll2 = session.calls
    assert token_call["data"]["grant_type"] == "client_credentials"
    body = execute["json"]
    assert body["defaultTimeframeStart"] == "2024-10-24T10:00:00Z" and body["defaultTimeframeEnd"] == "2024-10-24T10:05:00Z"
    assert body["maxResultRecords"] == 6 and body["query"].endswith("| sort timestamp asc | limit 6")
    assert "timeframe" not in body["query"]
    assert poll1["params"]["request-token"] == "SYNTHETIC-REQUEST-TOKEN"
    assert execute["headers"]["Authorization"] == "Bearer eyJSYNTHETIC.ACCESS.TOKEN"


def test_grail_truncation_raises_window_too_large(settings):
    big = fixture_json("grail_poll_succeeded.json")
    big["result"]["records"] = big["result"]["records"] * 3  # 6 > cap 5
    session = ScriptedSession([_token_response(), make_response(200, big)])
    with pytest.raises(WindowTooLarge):
        list(DynatraceGrailSource(settings, session=session, sleep=lambda s: None).fetch(W))


@pytest.mark.parametrize("meta", [{"sampled": True},
                                  {"notifications": [{"severity": "WARN", "notificationType": "LIMIT_EXCEEDED",
                                                      "message": "Result has been limited"}]}])
def test_grail_sampled_or_limit_notification_is_incomplete(settings, meta):
    body = fixture_json("grail_poll_succeeded.json")
    body["result"]["metadata"]["grail"].update(meta)
    session = ScriptedSession([_token_response(), make_response(200, body)])
    with pytest.raises(WindowTooLarge):
        list(DynatraceGrailSource(settings, session=session, sleep=lambda s: None).fetch(W))


def test_grail_failed_state(settings):
    session = ScriptedSession([_token_response(), make_response(202, fixture_json("grail_execute_202.json")),
                               make_response(200, {"state": "FAILED"})])
    with pytest.raises(TransientSourceError, match="FAILED"):
        list(DynatraceGrailSource(settings, session=session, sleep=lambda s: None).fetch(W))


def test_grail_poll_budget_cancels_query(settings):
    ticks = iter([0, 1000, 1000])  # deadline computed at t=0, first budget check at t=1000
    session = ScriptedSession([_token_response(), make_response(202, fixture_json("grail_execute_202.json")),
                               make_response(200, {})])  # the query:cancel call
    source = DynatraceGrailSource(settings, session=session, sleep=lambda s: None, clock=lambda: next(ticks),
                                  token_provider=DynatraceTokenProvider(settings, session, clock=lambda: 0))
    with pytest.raises(TransientSourceError, match="POLL_BUDGET"):
        list(source.fetch(W))
    assert session.calls[-1]["url"].endswith("query:cancel")


def test_grail_401_refreshes_token_once(settings):
    session = ScriptedSession([_token_response(), make_response(401), _token_response(),
                               make_response(200, fixture_json("grail_poll_succeeded.json"))])
    records = list(DynatraceGrailSource(settings, session=session, sleep=lambda s: None).fetch(W))
    assert len(records) == 2 and sum(1 for c in session.calls if c["url"].endswith("/token")) == 2


def test_oauth_token_is_cached_until_near_expiry(settings):
    now = [0.0]
    session = ScriptedSession([_token_response(300), _token_response(300)])
    provider = DynatraceTokenProvider(settings, session, clock=lambda: now[0])
    provider.authorization_header()
    now[0] = 200
    provider.authorization_header()
    assert len(session.calls) == 1
    now[0] = 241  # within 60 s of expiry -> refresh
    provider.authorization_header()
    assert len(session.calls) == 2


@pytest.mark.parametrize("dql", ["logs | filter x", 'fetch logs, from:now()-1h | filter a', "fetch logs | limit 10"])
def test_dql_guard_rejects_unsafe_queries(dql):
    with pytest.raises(ConfigError):
        validate_dql(dql)


def test_platform_token_mode(settings):
    provider = DynatraceTokenProvider(replace(settings, dynatrace_auth_mode="platform_token",
                                              dynatrace_platform_token="dt0s16.SYNTHETIC"))
    assert provider.authorization_header() == "Bearer dt0s16.SYNTHETIC"


# --------------------------------------------------------------------------- Broadcom stub
def test_broadcom_stub_fails_loudly(settings):
    with pytest.raises(NotImplementedSource):
        list(BroadcomOISource(settings).fetch(W))
