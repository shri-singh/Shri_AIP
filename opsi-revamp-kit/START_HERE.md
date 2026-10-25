# START HERE

You are on the corporate EC2 box without an assistant. This page routes every common need to the
right file. When in doubt, search the kit offline:

```bash
python3 tools/kb/ask.py "your question in plain words"        # offline BM25 search, file:line results
python3 tools/kb/ask.py --llm "..."                            # + answer via the corporate Portkey->Bedrock gateway (if approved)
```

## 1. First day on the box (in this order)

| Step | Do | Read |
|---|---|---|
| 1 | `scripts/preflight.sh` - tools, versions, time sync, disk, env-file permissions | [docs/phase-guides/phase-0-inventory.md](docs/phase-guides/phase-0-inventory.md) |
| 2 | `scripts/phase0/inventory_host.sh --check-egress` - what the host has and can reach | same |
| 3 | `scripts/clone_repos.sh` - baseline + revamp clones, legacy push disabled; then `scripts/repo/workspace.py init/verify` | [docs/phase-guides/phase-1-repos-and-containers.md](docs/phase-guides/phase-1-repos-and-containers.md), [docs/repository-strategy.md](docs/repository-strategy.md) |
| 4 | `python3 scripts/phase0/inventory_opsi.py ~/workspaces/opsi-baseline-snapshot` - the real Opsi stack | [docs/gap-analysis.md](docs/gap-analysis.md) |
| 5 | `make venv && make smoke` - prove the kit works on this host | [docs/testing-strategy.md](docs/testing-strategy.md) |
| 6 | Fill the decisions table in [docs/phase-guides/phase-0-inventory.md](docs/phase-guides/phase-0-inventory.md) | [docs/architecture.md](docs/architecture.md), [docs/adr/](docs/adr/README.md) |

## 2. "I want to..." index

| I want to... | Go to |
|---|---|
| understand the whole design in 20 minutes | [docs/architecture.md](docs/architecture.md) |
| know WHY a decision was made | [docs/adr/README.md](docs/adr/README.md) |
| get deep advice on a topic (as if asking the architect) | [docs/consultations/README.md](docs/consultations/README.md) |
| run the collectors for the first time | [services/ingestion/README.md](services/ingestion/README.md), [docs/phase-guides/phase-2-ingestion-storage.md](docs/phase-guides/phase-2-ingestion-storage.md) |
| fix a failing window / dead letter / watermark | [docs/runbooks.md](docs/runbooks.md) |
| add a new data source (e.g. Broadcom OI) | [docs/handbook/FAQ.md#ingestion](docs/handbook/FAQ.md#ingestion) |
| apply the database migrations safely | [database/README.md](database/README.md) |
| start OpenMetadata in a lab safely | [infrastructure/compose/README.md](infrastructure/compose/README.md), [docs/consultations/02-openmetadata-deployment-and-integration.md](docs/consultations/02-openmetadata-deployment-and-integration.md) |
| graft the API modules into the existing FastAPI app | [apps/opsi-api/README.md](apps/opsi-api/README.md) |
| wire CopilotKit V2 into the existing React app | [apps/opsi-web/README.md](apps/opsi-web/README.md), [docs/consultations/01-copilotkit-v2-to-fastapi-bridge.md](docs/consultations/01-copilotkit-v2-to-fastapi-bridge.md) |
| run/deploy the CopilotKit runtime bridge | [apps/copilot-runtime/README.md](apps/copilot-runtime/README.md) |
| configure Portkey -> Bedrock | [docs/consultations/08-llm-gateway-portkey-bedrock.md](docs/consultations/08-llm-gateway-portkey-bedrock.md), [docs/cheatsheets/portkey-bedrock.md](docs/cheatsheets/portkey-bedrock.md) |
| configure SSO / roles / tenant isolation | [docs/consultations/07-identity-sso-rbac-tenancy.md](docs/consultations/07-identity-sso-rbac-tenancy.md) |
| set up NGINX for SSE | [infrastructure/nginx/opsi-revamp.locations.conf](infrastructure/nginx/opsi-revamp.locations.conf), [docs/cheatsheets/nginx.md](docs/cheatsheets/nginx.md) |
| set up tracing without leaking prompts | [docs/consultations/09-observability-otel-genai.md](docs/consultations/09-observability-otel-genai.md) |
| size EC2/RDS/OpenSearch | [docs/consultations/13-capacity-sizing-cost.md](docs/consultations/13-capacity-sizing-cost.md) |
| fix an error message I am seeing | [docs/handbook/TROUBLESHOOTING.md](docs/handbook/TROUBLESHOOTING.md) |
| look up a command | [docs/cheatsheets/](docs/cheatsheets/README.md) |
| know what a term means | [docs/handbook/GLOSSARY.md](docs/handbook/GLOSSARY.md) |
| check licences before copying code | [docs/license-inventory.md](docs/license-inventory.md) |
| see what is verified vs assumed | [docs/verified-facts.md](docs/verified-facts.md) |
| see which master-prompt requirement is covered where | [docs/requirements-traceability.md](docs/requirements-traceability.md) |
| plan commits and roll back | [docs/commit-plan.md](docs/commit-plan.md) |
| decide fork vs mirror, whole repo vs components, and keep the product repo clean | [docs/repository-strategy.md](docs/repository-strategy.md), [ADR-0020](docs/adr/0020-mirrors-packages-selective-vendoring.md) |
| set up / check my workspace of repos (push protection, pinned upstreams) | `scripts/repo/workspace.py`, [infrastructure/repo/](infrastructure/repo/README.md) |
| bring a few files from OpenMetadata/CopilotKit into the product | `scripts/repo/vendor_component.py` ([strategy section 10](docs/repository-strategy.md#10-maintenance-workflows-and-cadence)) |
| run the repo setup end to end with an assistant or as a runbook | [REPO_SETUP_MASTER_PROMPT.md](REPO_SETUP_MASTER_PROMPT.md) |
| work it out myself when the docs don't cover it | [docs/handbook/SELF_HELP_WITHOUT_AI.md](docs/handbook/SELF_HELP_WITHOUT_AI.md) |

## 3. Golden rules (print these)

1. Never touch the original Opsi remote, production DB, production NGINX or client network policy without a change ticket.
2. Never publish ports beyond `127.0.0.1` - run `scripts/compose_safe.sh <stack> config` before every `up`.
3. Never put secrets in Git, URLs, logs, prompts or chat. `chmod 600` every env file.
4. Never load raw logs into the multi-TB PostgreSQL. Raw goes to S3; PostgreSQL gets the curated subset.
5. Identity comes from the verified token - never from request bodies, AG-UI state or browser context.
6. The LLM proposes; the server validates; a human approves anything that changes a record.
7. Claim nothing works until the command ran and the test passed - write down the evidence.
