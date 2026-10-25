# Troubleshooting (symptom -> cause -> fix)

Find your error text with `grep -n -i "<words>" docs/handbook/TROUBLESHOOTING.md` or `tools/kb/ask.py`.

## Python / install

| Symptom | Cause | Fix |
|---|---|---|
| `ERROR: Could not find a version that satisfies the requirement pyarrow==26.0.0` | Python < 3.11 | `python3.12 -m venv .venv` (AL2023: `sudo dnf install python3.12`) |
| `pip` hangs / SSL errors | proxy / private CA | `pip config set global.index-url <mirror>`; `export PIP_CERT=/etc/pki/ca-trust/...` or `REQUESTS_CA_BUNDLE` |
| `ModuleNotFoundError: opsi_ingest` | wrong cwd | run from `services/ingestion` or `PYTHONPATH=services/ingestion` |
| `ModuleNotFoundError: app.modules` | API path | run from `apps/opsi-api` or set `PYTHONPATH` |
| `RuntimeError: Form data requires "python-multipart"` | missing dep | `pip install python-multipart` (in requirements/api.txt) |
| `psycopg ... cannot use the 'ProactorEventLoop'` | Windows only | irrelevant on Linux; tests set a selector loop on Windows |

## Collectors

| Symptom | Cause | Fix |
|---|---|---|
| `CONFIG ERROR: OPSI_ARCHIVE_BUCKET still holds the placeholder value` | `.env` not filled | set the approved bucket |
| `committed_until is not on the window grid` | window size changed | runbook "Changing the window size" |
| `elastic ... HTTP 400 ... compatible-with` | client 9.x vs cluster 8.x | `pip install 'elasticsearch>=8.15,<9'` |
| `elastic ... HTTP 403` | API key privileges | role with `read`, `view_index_metadata` on the pattern |
| `elastic ... HTTP 404` | pattern matches nothing / PIT expired | check `ELASTIC_INDEX_PATTERN`; keep page processing fast |
| `dynatrace problems: HTTP 401` | wrong token type | classic `Api-Token` with `problems.read`, env URL (not apps URL) |
| `dynatrace oauth token: HTTP 400` `invalid_scope`/`invalid_request` | scope not granted to client / bad resource | grant scopes to the OAuth client; set/unset `DYNATRACE_OAUTH_RESOURCE` (urn:dtaccount:<uuid>) |
| `grail ... HTTP 403` | missing permission on bucket/table | Dynatrace IAM policy: `storage:logs:read`, `storage:buckets:read` + bucket access |
| `grail ... HTTP 404` | wrong base URL | use `https://<env>.apps.dynatrace.com` |
| `grail query ended with state=FAILED` | DQL error, quota | run DQL in a notebook with same timeframe; check scan limit |
| `exceeded DYNATRACE_GRAIL_POLL_BUDGET_SECONDS` | slow/huge query | narrow DQL, smaller windows, higher budget |
| `... still too large at the minimum split size` | > cap records in 30 s | narrow source filter or raise cap |
| `ConfigError: DYNATRACE_GRAIL_DQL must not ...` | DQL contains timeframe/limit | remove them; collector adds both |
| S3 `AccessDenied` on PutObject | bucket policy requires KMS key / IAM lacks KMS | set `OPSI_KMS_KEY_ID`; grant `kms:GenerateDataKey` via S3 |
| `database is locked` (SQLite) | many processes on old DB file | kit uses WAL + busy timeout; ensure one process per source (timers/flock) |
| `prepared statement "_pg3_0" already exists` | PgBouncer/RDS Proxy transaction pooling | kit sets `prepare_threshold=None`; ensure you run current code |
| Outbox items `dead` | DB/OpenSearch down too long | fix, `requeue-dead` |
| Many `timestamp_naive` quarantines | source emits local times without offset | fix at source or add explicit zone handling for that field |

## Database / migrations

| Symptom | Cause | Fix |
|---|---|---|
| `permission denied to create role` | migrator lacks CREATEROLE | run 0001 as RDS master / rds_superuser member |
| `must be member of role "opsi_owner"` | 0001 not applied by this user | apply 0001 (grants membership) or `GRANT opsi_owner TO <migrator>` |
| `permission denied for schema public` creating functions | PG15+ public schema | kit uses `opsi_meta` - make sure you run current 0005 |
| `CHECKSUM MISMATCH` in migrate.sh | an applied file was edited | never edit applied migrations; add a new one |
| queries return 0 rows | RLS context not set | `set_config('opsi.tenant_id', ...)` |
| `new row violates row-level security policy` | inserting for another tenant/owner or context missing | set context; check owner_id = current user |
| `extension "vector" is not available` | pgvector not installed/allowed | skip 0006 or ask DBA (RDS supports `vector`) |
| `Refusing destructive rollback` | safety guard | take snapshot, then `SET opsi.allow_destructive='yes';` |

## API / auth

| Symptom | Cause | Fix |
|---|---|---|
| 401 `invalid token` | wrong audience/issuer, ID token instead of access token | inspect token at the IdP debugger offline (`jwt.decode(..., options={"verify_signature": False})`) - check `iss`, `aud` |
| 401 `token expired` right after login | clock skew | chrony; leeway 60 s |
| 401 `no Opsi role mapped` | group names don't match map | `OPSI_GROUP_ROLE_MAP_JSON` (Entra: object ids vs names) |
| 403 `missing permission` | role lacks permission | adjust group map / `ROLE_PERMISSIONS` |
| `RuntimeError: OPSI_AUTH_MODE=dev is only allowed...` | dev mode in staging/prod | use `existing` or `oidc` |
| 422 on POST with `tenant_id` field | by design (`extra="forbid"`) | remove identity fields from clients |
| 404 for an existing thread | not yours / other tenant / shared but trying to write | expected |
| attachment download 409 `status: uploaded` | malware scan pending | wait; check GuardDuty tags |
| presigned URL `SignatureDoesNotMatch`/KMS errors | SigV2 or wrong region | kit forces `s3v4`; check `AWS_REGION` = bucket region |

## Runtime / streaming / NGINX

| Symptom | Cause | Fix |
|---|---|---|
| runtime 401 before FastAPI sees anything | no `Authorization`/cookie header | provider `headers` builder; cookie auth -> add `cookie` to require/forward lists |
| runtime 404 `unknown_agent` | agent id mismatch | provider `agentId` == `OPSI_COPILOT_AGENT_IDS` |
| runtime 502 `agent_unavailable` | FastAPI down / wrong `OPSI_AGENT_BASE_URL` | `curl -s http://127.0.0.1:8000/api/v2/healthz` |
| stream arrives all at once at the end | NGINX buffering | `proxy_buffering off`, `X-Accel-Buffering: no` (kit sets) |
| stream cut after 60 s | proxy/ALB idle timeout | NGINX `proxy_read_timeout 300s`; ALB idle timeout >= 300 s; runtime keep-alives 15 s |
| TypeScript errors about duplicate `AbstractAgent` | two `@ag-ui/client` versions | pin to runtime's dependency; `npm ls @ag-ui/client` |
| `Cannot find module '@copilotkit/runtime/v2/node'` | old runtime version | `npm ls @copilotkit/runtime`; pin 1.79.1 or verify exports |
| outbound calls to segment/scarf blocked by proxy logs | vendor telemetry | `COPILOTKIT_TELEMETRY_DISABLED=true`, `DO_NOT_TRACK=1`, `SCARF_ANALYTICS=false` |
| `RUN_ERROR` message `agent_error` | FastAPI 5xx (body hidden on purpose) | read FastAPI logs by `x-request-id` |

## LLM / Portkey / Bedrock

| Symptom | Cause | Fix |
|---|---|---|
| `RUN_ERROR llm_unavailable` | any gateway exception | see Portkey logs; run the Phase 4.2 smoke |
| 401 Portkey | key | rotate |
| model not found / validation error | inference profile vs model id; region | `aws bedrock list-inference-profiles`; set `LLM_MODEL` |
| AccessDeniedException | IAM for Portkey's identity / model access not enabled | update `bedrock-invoke-policy.json`; enable model access |
| ThrottlingException | quotas | retries/fallback in Portkey config; request quota |
| 400 about `stream_options` | gateway doesn't accept usage streaming | `LLM_STREAM_USAGE=false` |
| model never calls tools | descriptions unclear / tools not offered | check `llm.requests` in a test; improve descriptions |

## OpenMetadata

| Symptom | Cause | Fix |
|---|---|---|
| containers exit / OOM | not enough RAM | 16 GiB+ for the dev stack; stop other stacks |
| OpenSearch `max virtual memory areas vm.max_map_count [65530] is too low` | kernel setting | `sudo sysctl -w vm.max_map_count=262144` + persist |
| compose `container name already in use` | fixed `container_name` in upstream file | only one OM stack per host; `docker rm` old ones |
| `port exposure check FAILED` | override not applied or old Compose | Compose >= 2.24 for `!reset`; include the override file |
| ingestion: tables missing | REFERENCES not granted on new tables / schema filter | re-run 0007 grants; check `OM_SCHEMA_INCLUDES_JSON` |
| API 401 with bot token | token revoked/expired | regenerate bot token |
| search returns nothing after upgrade | reindex needed | Settings -> Applications -> Search Indexing (2.0 recreates indices) |

## OTel
| Symptom | Cause | Fix |
|---|---|---|
| collector `validate` error unknown processor | contrib vs core image | use `opentelemetry-collector-contrib` |
| Dynatrace rejects metrics | cumulative temporality | `cumulativetodelta` processor (in prod config) |
| no traces | `OTEL_SDK_DISABLED=true` or wrong endpoint | env; `curl -s http://127.0.0.1:13133/` |
