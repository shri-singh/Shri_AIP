# Deployments - topology, sizing, isolation, AWS plans

Audience: whoever provisions and operates the revamp on EC2/AWS. Pair with [runbooks.md](runbooks.md).

## 1. Environments

| Env | Purpose | Data | Auth | Allowed shortcuts |
|---|---|---|---|---|
| **lab** (one EC2, isolated SG) | Prove components; OpenMetadata dev stack | synthetic + approved samples | `OPSI_AUTH_MODE=dev` allowed | local archive dir, SSE-S3, lab compose override |
| **staging** | Integration with real IdP, Portkey, Dynatrace sandbox, RDS clone | masked or approved subset | OIDC / existing | none of the lab shortcuts |
| **prod** | Users | real | OIDC / existing + RLS | none; change tickets for every step |

## 2. Host layout (single Opsi EC2 to start)

| Process | How it runs | Listens | Notes |
|---|---|---|---|
| NGINX (existing) | systemd | 443 (internal) | add `opsi-revamp.locations.conf` in the revamp server block only |
| Opsi FastAPI (existing) + revamp modules | existing service manager | 127.0.0.1:8000 | `install_revamp()` grafted into the app factory |
| copilot-runtime | `opsi-copilot-runtime.service` or compose `opsi-revamp` | 127.0.0.1:4000 | Node >= 20.18, telemetry off |
| OTel Collector | compose `opsi-revamp` | 127.0.0.1:4317/4318/13133 | prod config, credentials in env file |
| Collectors | `opsi-collect@<source>.timer`, `opsi-index.timer`, `opsi-ingest-status.timer` | none | user `opsi-ingest`, state in `/var/lib/opsi-ingest` |
| OpenMetadata | separate host or compose project `opsi-openmetadata` | 127.0.0.1:8585/8586 | reverse proxy + SSO in front |

Create service users once:
```bash
sudo useradd --system --home /var/lib/opsi-ingest --shell /sbin/nologin opsi-ingest
sudo useradd --system --home /nonexistent --shell /sbin/nologin opsi-runtime
sudo install -d -o opsi-ingest -g opsi-ingest -m 0750 /var/lib/opsi-ingest /var/log/opsi-ingest
sudo install -d -m 0750 /etc/opsi && sudo chown root:opsi-ingest /etc/opsi
```

## 3. Compose projects (isolated by project name, network and env file)

| Project | File(s) | Env file | Exposure |
|---|---|---|---|
| `opsi-om-lab` | upstream `docker/development/docker-compose-postgres.yml` + `infrastructure/compose/openmetadata.lab-override.yml` | `.openmetadata-lab.env` | 127.0.0.1:8585/8586 only (5432, 9200, 9300, 5005, 8080 reset) |
| `opsi-openmetadata` | `openmetadata.prod-reviewed.example.yml` | `/etc/opsi/openmetadata.env` | 127.0.0.1:8585/8586; external RDS + OpenSearch |
| `opsi-revamp` | `opsi-revamp.compose.yml` | `/etc/opsi/revamp.env` | runtime host network on loopback; collector 127.0.0.1 |

Always use `scripts/compose_safe.sh <stack> config|up|ps|logs|down` - it renders the merged config and refuses to
continue if anything binds beyond loopback. Note the upstream OM dev compose uses fixed `container_name`s, so only
one copy can run per Docker host regardless of `-p`.

## 4. Sizing (starting points - measure, then adjust)

| Component | Minimum | Comfortable | Driver |
|---|---|---|---|
| Opsi EC2 incl. runtime + collectors + collector agent | 4 vCPU / 16 GiB, 100 GiB gp3 | 8 vCPU / 32 GiB | API concurrency, Parquet batches (pyarrow memory ~3-5x batch size) |
| OpenMetadata **lab** (dev compose, everything in Docker) | 4 vCPU / 16 GiB, 100 GiB | 8 vCPU / 32 GiB | builds from source; OpenSearch 1 GiB heap; server JVM |
| OpenMetadata server (prod, external stores) | 2-4 vCPU / 8 GiB | 4 vCPU / 16 GiB | API + reindex jobs |
| OpenMetadata PostgreSQL (RDS) | db.m6g.large (2 vCPU / 8 GiB), PG >= 15 | db.m6g.xlarge | OM docs recommend 4 vCPU / 16 GiB for the DB at scale |
| OpenMetadata OpenSearch | 2 data nodes, 2 vCPU / 8 GiB, 100 GiB each | 3 nodes | OM docs: 2 vCPU / 8 GiB / 100 GiB per node |
| Opsi curated tables | +5-20 GiB/year | | signatures per window, not log volume |
| S3 bronze | (error/warn log bytes per day) x 0.15 (Parquet+snappy) x retention | | filter at source (DQL / Elastic filter) |

Set `vm.max_map_count=262144` (`/etc/sysctl.d/99-opensearch.conf`) on any host running OpenSearch/Elasticsearch containers.

## 5. AWS plan

### 5.1 IAM (least privilege; templates in `infrastructure/aws/iam/`)
- **Collector role** (instance profile of the collector host): `s3:PutObject/GetObject` on `raw/*`, `quarantine/*`;
  optional `s3:DeleteObject` on `raw/*/run=*` for orphan cleanup; `kms:GenerateDataKey/Decrypt` via S3 only;
  `secretsmanager:GetSecretValue` on `opsi/ingest/*`.
- **API role**: presign + read scan tags on `chat-attachments/*`; `voice-tmp/*`; KMS via S3; Transcribe/Polly if voice
  is enabled; `secretsmanager:GetSecretValue` on `opsi/api/*`.
- **Portkey's Bedrock identity**: `bedrock:InvokeModel*` on the approved inference profile + model ARNs only.
- Use IMDSv2 only (`HttpTokens=required`, hop limit 1 unless containers need IMDS - prefer 2 for Docker-in-host).

### 5.2 KMS
One customer-managed key per data class (e.g. `alias/opsi-archive`, `alias/opsi-attachments`), key policy from
`infrastructure/aws/kms/key-policy.json` (admins administer; Opsi roles use the key only via S3). Rotation enabled.

### 5.3 S3
Block Public Access on; versioning on; default SSE-KMS with bucket key; bucket policy (deny non-TLS, deny puts without
the approved key, optional VPC-endpoint-only); lifecycle from `infrastructure/aws/s3/lifecycle.json`; S3 gateway
endpoint in the VPC. Consider Object Lock (governance mode) for `raw/` if records management requires WORM.

### 5.4 RDS / Aurora PostgreSQL
- Revamp schemas live in the **existing Opsi application database** (small, app-owned) - DBA approval required.
  Collector state can live there too (`OPSI_STATE_BACKEND=postgres`) or in SQLite on the host.
- OpenMetadata gets a **separate** RDS instance (PG >= 15) - never the Opsi DB or the log DB.
- Backups: automated snapshots + PITR (retention per policy), AWS Backup plan with cross-account/cross-region copy
  if required, quarterly restore drill (runbook). Logical dumps of revamp schemas are a *supplement*
  (`scripts/backup_restore_drill.sh`), and RDS "export snapshot to S3" Parquet is **not** a restorable backup.
- Connection security: `sslmode=require` (or `verify-full` with the RDS CA bundle); app login member of `opsi_app`;
  consider RDS Proxy (then keep `prepare_threshold=None`, already set).

### 5.5 Network / security groups
| SG | Inbound | From |
|---|---|---|
| `sg-opsi-alb` | 443 | corporate CIDRs / VPN |
| `sg-opsi-app` | 443 | `sg-opsi-alb` only (or the existing NGINX path) |
| `sg-opsi-rds` | 5432 | `sg-opsi-app`, `sg-om-app` (OM ingestion read-only role) |
| `sg-om-app` | 443 (proxy) | `sg-opsi-alb` |
| `sg-om-rds` | 5432 | `sg-om-app` |
| `sg-om-search` | 443 | `sg-om-app` |
Egress: allowlist FQDNs via proxy/NAT (Dynatrace env + `sso.dynatrace.com`, Portkey endpoint, package mirrors).

## 6. Secrets
Preferred: AWS Secrets Manager -> rendered to `/etc/opsi/*.env` (mode 0600, owner = service user) at boot by a
small systemd `ExecStartPre` or your config management; never in Git, AMIs, user-data or Docker images.
```bash
aws secretsmanager get-secret-value --secret-id opsi/ingest/env --query SecretString --output text \
  | sudo install -m 0600 -o opsi-ingest -g opsi-ingest /dev/stdin /etc/opsi/ingest.env
```
Rotation: Dynatrace OAuth client secret, Elastic API keys, OpenMetadata bot token, Portkey key - quarterly or per
policy; see runbook "Rotate a credential".

## 7. Ports reference

| Port | Bound to | Service |
|---|---|---|
| 443 | internal interface | NGINX |
| 8000 | 127.0.0.1 | FastAPI (existing + revamp) |
| 4000 | 127.0.0.1 | copilot-runtime |
| 4317/4318/13133 | 127.0.0.1 | OTel collector (gRPC/HTTP/health) |
| 8585/8586 | 127.0.0.1 | OpenMetadata API+UI / admin health |
| 55432 | 127.0.0.1 | PGlite test server (tests only) |
Never published: 5432, 9200, 9300, 5005 (JDWP), 8080 (Airflow), 6379.

## 8. Deployment order (first time)
1. Phase 0 inventory and decisions -> 2. RDS migrations 0000-0005 (staging first) -> 3. S3/KMS/IAM ->
4. collectors (dry-run, then timers) -> 5. API modules behind a feature flag -> 6. copilot-runtime + NGINX location ->
7. React provider behind a feature flag -> 8. OpenMetadata (separate) + metadata ingestion -> 9. OTel collector ->
10. E2E acceptance (testing-strategy.md) -> 11. production change with rollback plan (commit-plan.md).
