# ADR-0014: Chat persistence in Opsi PostgreSQL, not CopilotKit Intelligence
- Status: Accepted
- Date: 2026-10-24

## Context
Users must find threads after re-login, organise them in folders/tags, search full text, see attachments and
citations, and share with colleagues - with tenant isolation and retention control. CopilotKit V2's `useThreads` /
`CopilotThreadsDrawer` are backed by **CopilotKit Intelligence** (hosted service / license), which would place
client data outside approved stores.

## Decision
- Schema `opsi_chat` (0003): folders, threads (AG-UI threadId = UUID), messages (AG-UI wire JSON + extracted text with
  `tsvector`), tags, attachments (S3 keys, scan status), agent_runs, tool_runs, evidence_refs, action_approvals, feedback.
- REST API `/api/v2/chat/*` for lists, search, tags, folders, restore (AG-UI messages + evidence + state), attachments.
- React restores with `agent.setMessages()` / `agent.setState()` and renders history in our own `ThreadSidebar`.
- Runtime routes `threads/*` and `memories/*` are blocked at the runtime.

## Consequences
- We maintain thread UI ourselves (small). Retention/export/deletion policies are ours to implement (runbook).

## Verification
`tests/api/test_agui_contract.py::test_full_run_with_server_tool_citations_state_and_persistence` (restore),
`tests/integration/test_pg_chat.py`, runtime test "unused runtime routes are 404".
