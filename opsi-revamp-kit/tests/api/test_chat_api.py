"""Chat REST API: folders, tags, search, archive, sharing, isolation, feedback, attachments."""
import uuid

from app.modules.llm.gateway import ScriptedLLM, ScriptedTurn
from botocore.stub import ANY, Stubber

from .helpers import make_app, parse_sse, run_input, user

CHAT = "/api/v2/chat"


def _client(**kw):
    return make_app(ScriptedLLM([ScriptedTurn(text="Payments timeout details")] * 5), **kw)


def _thread(client, headers=None, **body):
    resp = client.post(f"{CHAT}/threads", json=body, headers=headers or user())
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_threads_folders_tags_and_filters():
    app, svc, client = _client()
    folder = client.post(f"{CHAT}/folders", json={"name": "Payments"}, headers=user()).json()
    assert client.post(f"{CHAT}/folders", json={"name": "payments"}, headers=user()).status_code == 409
    t1 = _thread(client, title="Checkout latency", folder_id=folder["id"], linked_incident_id="P1")
    t2 = _thread(client, title="Disk alerts")
    tag = client.post(f"{CHAT}/tags", json={"name": "sev1", "color": "#ff0000"}, headers=user()).json()
    assert client.put(f"{CHAT}/threads/{t1['id']}/tags", json={"tag_ids": [tag["id"]]}, headers=user()).json()["tags"] == ["sev1"]
    ids = lambda r: [t["id"] for t in r.json()]  # noqa: E731
    assert ids(client.get(f"{CHAT}/threads", params={"folder_id": folder["id"]}, headers=user())) == [t1["id"]]
    assert ids(client.get(f"{CHAT}/threads", params={"tag": "SEV1"}, headers=user())) == [t1["id"]]
    assert ids(client.get(f"{CHAT}/threads", params={"incident_id": "P1"}, headers=user())) == [t1["id"]]
    assert set(ids(client.get(f"{CHAT}/threads", headers=user()))) == {t1["id"], t2["id"]}
    # archive hides by default
    client.patch(f"{CHAT}/threads/{t2['id']}", json={"archived": True}, headers=user())
    assert ids(client.get(f"{CHAT}/threads", headers=user())) == [t1["id"]]
    assert len(client.get(f"{CHAT}/threads", params={"include_archived": True}, headers=user()).json()) == 2


def test_isolation_between_users_and_tenants():
    app, svc, client = _client()
    t = _thread(client, title="Private investigation")
    for headers in (user("bob"), user("alice", tenant="tenant-b")):
        assert client.get(f"{CHAT}/threads/{t['id']}", headers=headers).status_code == 404
        assert client.patch(f"{CHAT}/threads/{t['id']}", json={"title": "x"}, headers=headers).status_code == 404
        assert client.get(f"{CHAT}/threads", headers=headers).json() == []
    # someone else's tag/folder ids cannot be attached
    bob_tag = client.post(f"{CHAT}/tags", json={"name": "mine"}, headers=user("bob")).json()
    assert client.put(f"{CHAT}/threads/{t['id']}/tags", json={"tag_ids": [bob_tag["id"]]},
                      headers=user()).status_code == 404


def test_identity_fields_in_body_are_rejected():
    app, svc, client = _client()
    resp = client.post(f"{CHAT}/threads", json={"title": "x", "tenant_id": "tenant-b"}, headers=user())
    assert resp.status_code == 422


def test_sharing_requires_permission_and_is_audited():
    app, svc, client = _client()
    t = _thread(client, title="Shared one")
    assert client.patch(f"{CHAT}/threads/{t['id']}", json={"visibility": "tenant"},
                        headers=user(roles="viewer")).status_code in (403, 404)
    assert client.patch(f"{CHAT}/threads/{t['id']}", json={"visibility": "tenant"}, headers=user()).status_code == 200
    assert client.get(f"{CHAT}/threads", params={"include_shared": True}, headers=user("bob")).json()[0]["id"] == t["id"]
    assert any(e["action"] == "thread.visibility" for e in svc.audit.events)


def test_full_text_search_over_messages():
    app, svc, client = _client()
    body = run_input()
    parse_sse(client.post("/api/v2/agents/opsi-investigator", json=body, headers=user()).text)
    hits = client.get(f"{CHAT}/search", params={"q": "timeout payments"}, headers=user()).json()
    assert hits and hits[0]["thread_id"] == body["threadId"]
    assert client.get(f"{CHAT}/search", params={"q": "timeout"}, headers=user("bob")).json() == []


def test_feedback_is_redacted_and_scoped():
    app, svc, client = _client()
    t = _thread(client)
    ok = client.post(f"{CHAT}/threads/{t['id']}/feedback", headers=user(),
                     json={"message_id": "m1", "rating": -1, "reason_code": "bad_citation",
                           "comment": "contact me at jane@example.com"})
    assert ok.status_code == 204
    stored = next(iter(svc.chat.feedback.values()))
    assert "jane@example.com" not in stored.comment
    assert client.post(f"{CHAT}/threads/{t['id']}/feedback", headers=user("bob"),
                       json={"message_id": "m1", "rating": 1}).status_code == 404


# ---------------------------------------------------------------- attachments
def _s3():
    import boto3
    from botocore.config import Config
    return boto3.client("s3", region_name="us-west-2", aws_access_key_id="testing", aws_secret_access_key="testing",
                        config=Config(signature_version="s3v4"))


def test_attachment_lifecycle_presign_finalize_scan_download():
    s3 = _s3()
    app, svc, client = _client(s3_client=s3)
    t = _thread(client)
    init = client.post(f"{CHAT}/threads/{t['id']}/attachments", headers=user(),
                       json={"filename": "error-dump.txt", "mime_type": "text/plain", "size_bytes": 1200})
    assert init.status_code == 201, init.text
    data = init.json()
    fields = data["fields"]
    assert data["expires_in"] == 300 and fields["Content-Type"] == "text/plain"
    assert fields["x-amz-server-side-encryption"] == "AES256" and "policy" in fields
    key = fields["key"]
    assert "error-dump" not in key and key.startswith("chat-attachments/tenant=tenant-a/")
    att_id = data["attachment_id"]
    # download before upload/scan is refused
    assert client.get(f"{CHAT}/attachments/{att_id}/download", headers=user()).status_code == 409
    with Stubber(s3) as stub:
        stub.add_response("head_object", {"ContentLength": 1200, "ContentType": "text/plain"},
                          {"Bucket": "opsi-unit-attach", "Key": key})
        assert client.post(f"{CHAT}/attachments/{att_id}/finalize", headers=user()).json()["status"] == "uploaded"
        stub.add_response("get_object_tagging", {"TagSet": []}, {"Bucket": "opsi-unit-attach", "Key": key})
        assert client.get(f"{CHAT}/attachments/{att_id}/download", headers=user()).status_code == 409  # scan pending
        stub.add_response("get_object_tagging",
                          {"TagSet": [{"Key": "GuardDutyMalwareScanStatus", "Value": "NO_THREATS_FOUND"}]},
                          {"Bucket": "opsi-unit-attach", "Key": key})
        dl = client.get(f"{CHAT}/attachments/{att_id}/download", headers=user())
    assert dl.status_code == 200
    url = dl.json()["url"]
    assert "X-Amz-Algorithm=AWS4-HMAC-SHA256" in url and "X-Amz-Expires=60" in url
    assert "response-content-disposition=attachment" in url
    assert client.get(f"{CHAT}/attachments/{att_id}/download", headers=user("bob")).status_code == 404
    assert [e["outcome"] for e in svc.audit.events if e["action"] == "attachment.download"][-2:] == ["allowed", "denied"]


def test_attachment_rejections():
    app, svc, client = _client(s3_client=_s3())
    t = _thread(client)
    post = lambda body: client.post(f"{CHAT}/threads/{t['id']}/attachments", headers=user(), json=body)  # noqa: E731
    assert post({"filename": "x.exe", "mime_type": "application/x-msdownload", "size_bytes": 10}).status_code == 400
    assert post({"filename": "big.txt", "mime_type": "text/plain", "size_bytes": 50 * 1024 * 1024}).status_code == 400
    assert post({"filename": "../etc/passwd", "mime_type": "text/plain", "size_bytes": 10}).status_code == 422
    assert client.post(f"{CHAT}/threads/{uuid.uuid4()}/attachments", headers=user(),
                       json={"filename": "a.txt", "mime_type": "text/plain", "size_bytes": 10}).status_code == 404


def test_attachment_type_mismatch_on_finalize_is_rejected():
    s3 = _s3()
    app, svc, client = _client(s3_client=s3)
    t = _thread(client)
    data = client.post(f"{CHAT}/threads/{t['id']}/attachments", headers=user(),
                       json={"filename": "a.txt", "mime_type": "text/plain", "size_bytes": 10}).json()
    with Stubber(s3) as stub:
        stub.add_response("head_object", {"ContentLength": 10, "ContentType": "text/html"},
                          {"Bucket": ANY, "Key": ANY})
        assert client.post(f"{CHAT}/attachments/{data['attachment_id']}/finalize", headers=user()).status_code == 400
