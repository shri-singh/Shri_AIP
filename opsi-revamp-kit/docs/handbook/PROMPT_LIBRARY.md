# Prompt library (for a corporate-approved assistant, e.g. via Portkey -> Bedrock)

Rules: no secrets, no client data, no unredacted logs in prompts. Paste kit files or excerpts; ask for diffs and tests.

## Grafting the API modules into the real Opsi app
```
You are helping integrate a FastAPI module package into an existing FastAPI app.
Existing app facts (from my Phase 0 inventory): <paste: app factory file path, router prefixes, auth dependency names, DB library>.
Module entry point: app/modules/install.py (install_revamp, build_services). Auth options: OPSI_AUTH_MODE=existing with
set_existing_auth_adapter(fn) returning Principal(user_id, tenant_id, roles, service_scope).
Task: write the adapter using the existing auth dependency <name>, and the lifespan code that calls install_revamp
behind env flag OPSI_REVAMP_ENABLED. Do not change existing routes. Output a unified diff and a pytest that proves an
unauthenticated request to /api/v2/chat/threads returns 401.
```

## Writing a source adapter
```
Implement a collector source for <vendor API> following this contract: <paste services/ingestion/opsi_ingest/sources/base.py
and dynatrace_problems.py>. API facts (verified from docs, with links): <endpoint, auth, pagination, limits>.
Sample responses (redacted): <paste fixture>. Requirements: fetch(window) yields SourceRecord, raises WindowTooLarge
instead of truncating, uses request_with_retry, FieldMap for time/severity/service/message. Write pytest tests using
ScriptedSession like tests/ingestion/test_sources.py. Don't invent fields not in the samples.
```

## Reviewing a migration
```
Review this PostgreSQL migration for a busy multi-TB production database (PostgreSQL <version>): <paste SQL>.
Check: locks taken, table rewrites, need for CONCURRENTLY, RLS coverage for every tenant table, grants to roles
opsi_app/opsi_ingest_writer/opsi_readonly, idempotency (IF NOT EXISTS), and rollback. List risks and a safer variant.
```

## Debugging a streaming problem
```
Symptom: <describe>. Here are the first 30 SSE events from curl -N (redacted): <paste>. Runtime log lines: <paste>.
FastAPI log lines with the same x-request-id: <paste>. NGINX location config: <paste>.
Explain where the stream breaks and propose a fix; reference AG-UI ordering rules (RUN_STARTED first, TOOL_CALL_RESULT
after TOOL_CALL_END, RUN_FINISHED/RUN_ERROR last).
```

## Threat review of a new tool/action
```
Proposed agent capability: <describe>. Current controls: typed read-only routes, allowlisted UI actions with pydantic
schemas, service scope, budgets, human approvals executed via REST with the user's session, fenced untrusted data.
Do a STRIDE review of the new capability and list concrete tests (positive and negative) to add.
```

## Golden-set evaluation
```
Given these investigation questions and expected sources (JSONL): <paste>, and these agent transcripts with citations:
<paste>, score route recall, citation precision and answer correctness (rubric: grounded, specific, time range stated).
Output a table and the 5 worst cases with likely causes (route description, missing data, scope).
```
