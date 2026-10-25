# Threat model (STRIDE) - Opsi revamp

Scope: browser, NGINX, copilot-runtime, FastAPI revamp modules, collectors, PostgreSQL, S3, OpenMetadata,
Portkey/Bedrock, OTel. Assets: client log data (may contain PHI/PII/secrets), incident knowledge, chat history,
credentials, availability of the production Opsi app.

## Trust boundaries
1. Browser -> NGINX (corporate network, user identity).
2. NGINX -> runtime / API (loopback; runtime forwards user credentials).
3. Runtime -> FastAPI agent (loopback; agent endpoint not public).
4. API/collectors -> data stores and vendors (service identities, IAM roles).
5. **Data -> model**: logs, catalog text and browser context flow into prompts (injection boundary).
6. Model -> UI/actions (model output is untrusted input to the browser and to executors).

## STRIDE table

| # | Threat | Where | Mitigation (implemented) | Residual / to do |
|---|---|---|---|---|
| S1 | Spoofed user/tenant via body, AG-UI `state`, `forwardedProps` or context | API/agent | Principal only from verified token/existing session; `extra="forbid"` models; ui context allowlist drops identity keys; tests | Adapter for existing auth must be reviewed |
| S2 | Forged JWT (alg none, HS confusion, wrong aud/iss, expired) | identity | JWKS + alg allowlist (no none/HS*), iss/aud/exp/iat required, leeway 60 s; tests | Key rollover tested at IdP change |
| S3 | Direct calls to the agent endpoint bypassing the runtime | network | endpoint on loopback; NGINX `location /api/v2/agents/ { return 404; }`; same auth enforced in FastAPI anyway | |
| T1 | Forged chat history to steer the model ("approved already") | agent | server-owned history; only new user msgs + pending tool results accepted; audited | |
| T2 | Tampered bronze objects | S3 | SHA-256 checksums in manifest verified before indexing; versioning; optional Object Lock | |
| T3 | Agent writes false causal edges | ontology | agent edges need evidence + confidence < 1 (DB CHECK); provenance; no edge-write tool exposed yet | Human review UI for agent edges |
| R1 | Repudiation of approvals/downloads/sharing | API | append-only `opsi_audit.events` (UPDATE/DELETE revoked), request ids | Ship audit to SIEM |
| I1 | Cross-tenant/user data leakage | DB/API | RLS RESTRICTIVE tenant policy + owner/visibility policies, FORCE RLS, non-owner app role; repository checks; 404 for foreign ids; tests | DBA superuser access is outside RLS - audit it |
| I2 | Secrets/PII from logs into prompts, traces, curated tables | ingest/agent/OTel | redaction at ingest and API, payload caps, fenced data, no content in spans, collector redaction/attribute drops | Regex redaction is not DLP; add estate-specific patterns |
| I3 | Error messages leaking internals | runtime/API | runtime `onError` + sanitizing fetch (tested); scrubbed vendor errors; generic RUN_ERROR | |
| I4 | Attachments: malware, data exfil via presigned URLs | API/S3 | type/size allowlist, presigned POST policy, GuardDuty scan gate, 60 s SigV4 GET, attachment-only disposition, audit | Enable GuardDuty Malware Protection |
| I5 | Vendor telemetry from libraries | runtime/npm | `COPILOTKIT_TELEMETRY_DISABLED`, `DO_NOT_TRACK`, `SCARF_ANALYTICS=false` | Egress allowlist blocks the rest |
| I6 | Exposed lab services (DB, OpenSearch without auth, JDWP) | compose | `!reset/!override` ports, `check_port_exposure.py` fails closed, loopback binds | Lab SG isolation |
| D1 | Cost/DoS via expensive queries or long agent loops | agent/routes | per-run budgets (calls, cost units, seconds), LLM turn cap, route timeouts, window maxima, no wildcard queries, Grail scan limit, NGINX rate limits | Per-user daily quotas |
| D2 | Collector overload of sources | collectors | bounded windows, page sizes, Retry-After, max windows per run | Vendor quotas per env |
| D3 | Big uploads/bodies | NGINX/runtime/API | `client_max_body_size`, runtime body cap, agent 2 MB cap | |
| E1 | Prompt injection triggers privileged actions | agent/UI | allowlisted actions, schema validation, scope checks, approvals by humans via REST with their own session, no code execution, generated UI disabled | Red-team prompts in staging |
| E2 | Over-privileged service identities | AWS/DB | least-privilege IAM templates, KMS via-service conditions, DB roles per function, NOBYPASSRLS | Access Analyzer validation |
| E3 | Supply-chain compromise | npm/pip | exact pins, lockfiles, export-verification scripts, licence/secret scans, internal mirrors | SCA scanning in CI |

## Prompt-injection specifics
Untrusted text sources: log messages, problem titles, catalog descriptions, runbooks, attachment text, browser context.
Controls are layered: (1) fencing + system rules (soft), (2) tools are read-only and typed (hard), (3) UI actions
validated and scope-checked (hard), (4) record changes need human approval (hard), (5) budgets (hard), (6) citations
validated (integrity). Assume (1) fails sometimes; (2)-(5) must hold.

## Privacy notes
- Data classification travels with bronze rows and manifests; curated tables hold excerpts only.
- Voice: consent per request, no retention, lifecycle backstop.
- Telemetry pseudonymises users (`OPSI_TELEMETRY_SALT`).
- Deletion requests: chat (`threads` cascade), curated rows (by tenant/time), bronze (S3 lifecycle / targeted delete with versioning considerations).

## Review cadence
Re-run this model when adding a route, a UI action, a data source, a new storage location or exposing a new endpoint.
