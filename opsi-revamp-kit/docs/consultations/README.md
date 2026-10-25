# Architectural consultations

Long-form answers to the questions you would ask the architect. Each one: the question, the short answer,
the reasoning, options compared, the recommended design, pitfalls, and how to verify. They complement the ADRs
(which record *what* was decided) with *how to think about it* when reality differs from the plan.

| # | Topic | Read when |
|---|---|---|
| [01](01-copilotkit-v2-to-fastapi-bridge.md) | CopilotKit V2 <-> FastAPI bridge, auth propagation, SSE, threads | wiring chat, debugging streaming/auth |
| [02](02-openmetadata-deployment-and-integration.md) | OpenMetadata deployment, ingestion, API use, UI reuse matrix | catalogue work, admin UI planning |
| [03](03-postgres-at-multi-tb-scale.md) | Working safely next to a multi-TB PostgreSQL | migrations, indexes, RLS, performance |
| [04](04-ingestion-correctness-and-backfills.md) | Ingestion correctness, completeness, backfills, scaling | collectors, data gaps, volume growth |
| [05](05-search-rag-routing-and-citations.md) | Retrieval routing, reranking, citations, evaluation | answer quality |
| [06](06-operational-ontology-modeling.md) | Modelling the operational ontology | graph design, bootstrapping from Dynatrace |
| [07](07-identity-sso-rbac-tenancy.md) | SSO, RBAC, service scope, tenant isolation | auth integration |
| [08](08-llm-gateway-portkey-bedrock.md) | Portkey -> Bedrock configuration and operations | model setup, costs, failures |
| [09](09-observability-otel-genai.md) | OpenTelemetry for the platform itself | tracing, dashboards |
| [10](10-security-privacy-prompt-injection.md) | Security, privacy, prompt injection | reviews, red-teaming |
| [11](11-frontend-integration-react.md) | Integrating into the existing React app | build tooling, state, charts, canvas |
| [12](12-release-rollout-rollback.md) | Release strategy, flags, rollout, rollback | going live |
| [13](13-capacity-sizing-cost.md) | Capacity, sizing, cost | budgets, instance choices |
| [14](14-voice-architecture.md) | Voice architecture options | voice phase |
| [15](../repository-strategy.md) | Repository strategy: forks vs mirrors, whole repos vs components, workspace layout, clean product repo, master prompts | setting up Git, adding third-party code, upgrades |
