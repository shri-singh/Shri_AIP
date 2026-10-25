# ADR-0013: Allowlisted, schema-validated UI actions; declarative charts; no generated code
- Status: Accepted
- Date: 2026-10-24

## Context
The assistant should change filters, open incidents, highlight graph nodes and render charts. CopilotKit V2 also
offers "Open Generative UI" (model-generated sandboxed UI) and A2UI. Model output is untrusted (prompt injection
via logs). No production mutation may follow from unverified LLM text.

## Decision
- A fixed catalogue (`agents/ui_actions.py`): `open_incident`, `set_dashboard_filter`, `render_chart`,
  `highlight_graph_nodes`, `draft_incident_update` (approval-gated). Each has a pydantic schema (strict, bounded,
  no markup/template characters in labels) and a permission; services are checked against the caller's scope.
- An action reaches the browser only if (a) it is in the catalogue, (b) the current view registered it (it is in
  `RunAgentInput.tools`), and (c) validation passed. Otherwise the model receives a tool error.
- Charts are `ChartSpec` data mapped to ECharts by our own code (`reports/chartSpec.ts`); no formatter functions,
  HTML or option objects from the model. Open Generative UI / A2UI are **not enabled**.
- Record-changing actions create an `action_approvals` row; a human decides via REST with their own session;
  executors run with that user's authority; everything is audited.

## Consequences
- New capability = new action + schema + frontend handler + test (deliberate friction).

## Verification
`tests/api/test_search_and_actions.py::test_ui_action_validation`, `tests/api/test_agui_contract.py::test_invalid_or_unoffered_frontend_actions_never_reach_the_browser`,
`::test_approval_flow_for_draft_incident_update`, `::test_four_eyes_policy`.
