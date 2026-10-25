"""PgChatRepository / ontology / incident store against the real schema WITH row-level security.

    (cd database/validate && npm ci && node serve_pglite.mjs --port 55432 --seed)
    TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:55432/postgres?sslmode=disable' pytest -m integration

The repository runs ``SET LOCAL ROLE opsi_app`` (OPSI_DB_SET_ROLE) so RLS applies even
though the test login is a superuser. Covers thread persistence, restore after
re-login, tags/folders, search, evidence, cross-user/tenant isolation.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
URL = os.environ.get("TEST_DATABASE_URL", "")
if not URL:
    pytest.skip("TEST_DATABASE_URL not set", allow_module_level=True)
pytest.importorskip("psycopg_pool")

from app.modules._shared.db import Database  # noqa: E402
from app.modules.chat.models import Evidence, StoredMessage, ThreadQuery  # noqa: E402
from app.modules.chat.repository_pg import PgChatRepository  # noqa: E402
from app.modules.identity.principal import Principal  # noqa: E402
from app.modules.ontology.repository import EdgeIn, PgOntologyRepository  # noqa: E402
from app.modules.search.stores import PgIncidentStore  # noqa: E402

UTC = timezone.utc


@pytest.fixture
def anyio_backend():
    import asyncio
    import sys

    # psycopg async cannot run on Windows' default Proactor loop (EC2/Linux is unaffected)
    if sys.platform == "win32":
        return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}
    return "asyncio"


@pytest.fixture
async def db():
    database = Database(URL, min_size=1, max_size=2, set_role="opsi_app")
    await database.open()
    yield database
    await database.close()


def who(user: str, tenant: str = "tenant-it") -> Principal:
    return Principal(user_id=user, tenant_id=tenant, roles=frozenset({"investigator"}))


async def test_thread_lifecycle_restore_and_isolation(db):
    repo = PgChatRepository(db)
    alice, bob, other = who(f"alice-{uuid.uuid4().hex[:4]}"), who("bob"), who("alice", tenant="tenant-zz")
    folder = await repo.create_folder(alice, "Payments", None)
    tid = uuid.uuid4()
    await repo.create_thread(alice, tid, title="Why payments fail", folder_id=folder.id, linked_incident_id="P1",
                             linked_service_id="payments", agent_id="opsi-investigator")
    msgs = [StoredMessage(message_id="u1", role="user", content_text="why gateway timeout",
                          content_json={"id": "u1", "role": "user", "content": "why gateway timeout"}, author_id="a"),
            StoredMessage(message_id="a1", role="assistant", content_text="Gateway timeouts [c1]",
                          content_json={"id": "a1", "role": "assistant", "content": "Gateway timeouts [c1]"},
                          author_id="agent:x")]
    assert await repo.append_messages(alice, tid, msgs) == 2
    assert await repo.append_messages(alice, tid, msgs) == 0  # idempotent by message id
    await repo.start_run(alice, tid, f"run-{tid.hex[:6]}", "model", None)
    await repo.add_evidence(alice, tid, [Evidence(citation_key="c1", source_type="elastic_log",
                                                  source_ref="elastic://i/_doc/1", message_id="a1")])
    tag = await repo.create_tag(alice, "sev1", "#ff0000")
    assert await repo.set_thread_tags(alice, tid, [tag.id])
    await repo.save_agent_state(alice, tid, {"phase": "done"}, {"page": "incident"})

    # "log out / log in": brand new transactions, same principal
    restored = await repo.list_messages(alice, tid)
    assert [m.message_id for m in restored] == ["u1", "a1"]
    assert (await repo.list_evidence(alice, tid))[0].citation_key == "c1"
    assert (await repo.get_agent_state(alice, tid))["phase"] == "done"
    listed = await repo.list_threads(alice, ThreadQuery(tag="SEV1", folder_id=folder.id))
    assert [t.id for t in listed] == [tid] and listed[0].tags == ["sev1"]
    assert [t.id for t in await repo.list_threads(alice, ThreadQuery(q="gateway"))] == [tid]
    assert (await repo.search(alice, "gateway timeout"))[0].thread_id == tid

    for intruder in (bob, other):
        assert await repo.get_thread(intruder, tid) is None
        assert await repo.list_messages(intruder, tid) == []
        assert await repo.list_evidence(intruder, tid) == []
        assert await repo.update_thread(intruder, tid, {"title": "pwned"}) is None
        with pytest.raises(LookupError):
            await repo.append_messages(intruder, tid, [StoredMessage(message_id="x", role="user", content_json={},
                                                                     author_id="x")])
    # sharing makes it readable (not writable) for tenant colleagues only
    await repo.update_thread(alice, tid, {"visibility": "tenant"})
    assert (await repo.get_thread(bob, tid)) is not None
    assert await repo.get_thread(other, tid) is None
    assert await repo.update_thread(bob, tid, {"title": "x"}) is None


async def test_ontology_and_incident_store_on_seed_data(db):
    p = who("demo-user", tenant="tenant-demo")
    onto = PgOntologyRepository(db)
    root = await onto.find_entity(p, "payments")
    assert root is not None and root.kind == "service"
    hood = await onto.neighborhood(p, root.id, datetime(2026, 10, 25, tzinfo=UTC), 2, 50)
    relations = {e.relation for e in hood.edges}
    assert {"calls", "writes_to", "owned_by", "affects"} <= relations
    assert await onto.find_entity(who("x", tenant="tenant-zz"), "payments") is None
    with pytest.raises(ValueError):  # relation kinds are enforced
        await onto.add_edge(p, EdgeIn(src_id=root.id, dst_id=root.id.__class__("00000000-0000-4000-8000-000000000003"),
                                      relation="owned_by"))
    store = PgIncidentStore(db)
    rows = await store.search_problems(p, "failure", None, datetime(2026, 10, 24, tzinfo=UTC),
                                       datetime(2026, 10, 25, tzinfo=UTC), 10)
    assert rows and rows[0]["display_id"] == "P-24102"
    agg = await store.aggregate(p, "error_counts_by_service", ["payments"], datetime(2026, 10, 24, tzinfo=UTC),
                                datetime(2026, 10, 24, tzinfo=UTC) + timedelta(days=1), 10)
    assert agg[0]["service_id"] == "payments" and agg[0]["events"] == 42
    assert await store.search_problems(who("x", tenant="tenant-zz"), "failure", None,
                                       datetime(2026, 10, 24, tzinfo=UTC), datetime(2026, 10, 25, tzinfo=UTC), 10) == []
