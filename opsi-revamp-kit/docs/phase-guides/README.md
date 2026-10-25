# Phase guides

Follow in order; each guide ends with exit criteria. Don't start a phase until the previous one's criteria are met.

| Phase | Guide | Outcome |
|---|---|---|
| 0 | [phase-0-inventory.md](phase-0-inventory.md) | facts about the real Opsi + host, filled decisions table, blockers list |
| 1 | [phase-1-repos-and-containers.md](phase-1-repos-and-containers.md) | two clones, pinned upstreams, OpenMetadata lab running safely |
| 2 | [phase-2-ingestion-storage.md](phase-2-ingestion-storage.md) | collectors writing verified bronze + curated tables |
| 3 | [phase-3-metadata-ontology-search.md](phase-3-metadata-ontology-search.md) | catalogue ingested, ontology seeded, retrieval routes live |
| 4 | [phase-4-copilotkit-chat-agent.md](phase-4-copilotkit-chat-agent.md) | chat in the Opsi UI with persistence, citations, actions |
| 5 | [phase-5-observability-voice.md](phase-5-observability-voice.md) | traces without content; voice prototype in lab |

## Manual setup checklist (things only humans with access can do)

| # | Item | Owner | Needed by phase |
|---|---|---|---|
| 1 | Create private repo `opsi-enterprise-revamp` on the corporate Git host; grant team | Git admins | 1 |
| 2 | EC2 lab instance (AL2023, 8 vCPU/32 GiB, 150 GiB gp3), isolated SG, IMDSv2, SSM access | Cloud ops | 1 |
| 3 | Egress allowlist: package mirrors (pypi/npm/docker), Dynatrace env + `sso.dynatrace.com`, Portkey | Network | 1-2 |
| 4 | S3 bucket(s) + KMS keys + bucket policy + lifecycle | Cloud security | 2 |
| 5 | IAM instance profiles (collector, API) from templates | Cloud security | 2 |
| 6 | Dynatrace: classic token `problems.read`; OAuth client with `storage:logs:read`, `storage:buckets:read` (+ bucket/table permissions); note account UUID | Dynatrace admins | 2 |
| 7 | Elastic: API key with `read`, `view_index_metadata` on the log patterns (collector); separate read key for the API | Elastic admins | 2-3 |
| 8 | RDS: migrator login, app login in `opsi_app`, collector login in `opsi_ingest_writer`; change window for migrations | DBA | 2 |
| 9 | OpenMetadata: target release, dedicated RDS (PG >= 15) + OpenSearch 3.x domain, SSO app registration, bot | Platform + IdP | 3 |
| 10 | Legal decision on openmetadata-ingestion licence | Legal | 3 |
| 11 | IdP: OIDC app/audience for Opsi API, group names -> roles mapping, test users | IAM team | 4 |
| 12 | Portkey: provider/config for Bedrock, model access in Bedrock (model access page / inference profiles), API key | AI platform | 4 |
| 13 | NGINX change for the revamp server block; TLS cert | Web ops | 4 |
| 14 | OTLP backend endpoint + ingest token (Dynatrace `openTelemetryTrace.ingest`, ...) | Observability | 5 |
| 15 | GuardDuty Malware Protection for S3 on the attachments bucket | Security | 4 |
| 16 | Transcribe/Polly approval (voice) | Security/Privacy | 5 |
