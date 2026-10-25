# Gap analysis: `opsi-enterprise-starter` vs the master prompt

The starter is a useful sketch, but several pieces would fail or silently corrupt data in production.
Each row: what the starter does, why it matters, what the kit does instead, and the test that proves it.
(The starter is left untouched as the input; the kit is the corrected implementation.)

## Ingestion - data correctness

| # | Starter (file) | Problem | Kit fix | Proof |
|---|---|---|---|---|
| I1 | `ingestion/model.py` `utc_string(None)` returns **now()**; unparseable strings pass through unchanged | Events without timestamps get the ingest time -> wrong incident timelines; non-UTC strings reach `timestamptz` | `timeutil.parse_timestamp` raises; normaliser **quarantines** with reason codes (`timestamp_missing/invalid/naive`) | `test_normalize.py::test_missing_timestamp_is_quarantined_not_defaulted_to_now`, `test_time_and_windows.py` |
| I2 | Nanosecond Grail timestamps (`.123456789Z`) | `fromisoformat` rejects >6 fraction digits on older Pythons | Fraction truncated to microseconds before parsing | `test_nanosecond_iso_from_grail` |
| I3 | `run_once.py` windows = `last - overlap` .. `now - lag` | Window identity changes every run -> S3 keys differ -> duplicates; a retry is not recognisable | **Grid-aligned windows** (`windows.plan_windows`) + per-window ledger | `test_same_window_always_has_same_key`, pipeline tests |
| I4 | One window per run, `INGEST_WINDOW_MAX_MINUTES` cap | After an outage catch-up is slow and unbounded runs are possible | `INGEST_MAX_WINDOWS_PER_RUN`, bounded catch-up | `test_catch_up_is_bounded` |
| I5 | Watermark advanced only after S3 **and** PG (`write_both`) | Master prompt requires separation: a PG outage stops collection; PG failure after S3 upload re-uploads under new keys | Bronze stage commits window + outbox atomically; **index stage** retries PG/OpenSearch independently with backoff + dead-letter | `test_index_failure_is_retried_and_never_touches_watermark`, `test_index_dead_letter_and_requeue` |
| I6 | Late events only via 60 s overlap | Late-indexed records beyond 60 s are lost | One **final re-scan** per window after `INGEST_FINAL_RESCAN_AFTER_MINUTES`; newest run authoritative | `test_late_event_is_picked_up_by_final_rescan` |
| I7 | `pa.Table.from_pylist(rows)` infers schema per batch | All-null column in one batch -> `null` type -> parts incompatible in Athena/Glue | Fixed Arrow schema `opsi.event.v1` | `test_parquet_schema_is_identical_across_parts_even_with_all_null_columns` |
| I8 | No checksum/manifest/quarantine/schema version/classification/source ref | Cannot prove completeness or detect corruption; no citation pointer | Parts + `_manifest.json` commit marker with SHA-256 per part, quarantine file, `schema_version`, `classification`, `source_ref` | `test_index_detects_tampered_part`, `test_quarantine_file_written_and_counted` |
| I9 | `upsert_pg` writes `raw jsonb` of every event into PostgreSQL | Violates "never bulk-ingest raw logs into the 6+ TB Postgres" | Only curated subset: problems, per-window error signatures, capped evidence samples | `aggregate_signatures` test, integration tests |
| I10 | Elastic `helpers.scan` (scroll) | No resumable total order; heavier contexts | PIT + `search_after` sorted `[ts, _shard_doc]`, PIT always closed | `test_elastic_pit_search_after_pagination` |
| I11 | `elasticsearch>=8.15,<10` | pip may install 9.x, which **fails against 8.x clusters** | Pin client major to cluster major (docs + requirements comment) | [verified-facts.md](verified-facts.md) |
| I12 | Grail: static `DYNATRACE_PLATFORM_BEARER_TOKEN` | OAuth tokens expire (~300 s): collector breaks within minutes | Client-credentials token provider with refresh + one retry on 401 | `test_oauth_token_is_cached_until_near_expiry`, `test_grail_401_refreshes_token_once` |
| I13 | Grail: timeframe inside DQL, `| limit N`, no RUNNING/NOT_STARTED handling, no cancel | Truncation only detectable by count; abandoned queries consume quota | Timeframe in body, `maxResultRecords = cap+1`, notification/sampled checks, cancel on budget overrun, recursive **window splitting** | `test_grail_*`, `test_result_cap_splits_window_and_collects_every_event_exactly_once` |
| I14 | Problems v2: no 429/5xx handling | Rate limits abort runs | `request_with_retry` honours `Retry-After`, fails fast on 4xx with scrubbed messages | `test_http_retry.py` |
| I15 | `checkpoints.py` SQLite without WAL/busy timeout; connections never closed | Concurrent cron jobs collide ("database is locked") | WAL + busy timeout; PostgreSQL backend option | `test_pg_ingest.py` |
| I16 | No dry run | First run on EC2 writes to S3 immediately | `collect --dry-run` fetches one window, writes nothing | `test_dry_run_writes_nothing` |

## Scripts and operations

| # | Starter | Problem | Kit fix |
|---|---|---|---|
| S1 | `01_clone_opsi.sh` sets `core.hooksPath /dev/null` on the baseline | That **disables** hooks; it does not protect the baseline | `clone_repos.sh` disables **push** on baseline and legacy remotes |
| S2 | `01_clone_opsi.sh` runs `gh repo create ... --push` automatically | Master prompt: never push without explicit authorisation | Prints the push command; never pushes |
| S3 | `02_fetch_upstreams.sh` clones HEAD unless `OM_REF` set | Unpinned upstreams | Pins `OM_REF=2.0.6-release` default, writes `upstream/PROVENANCE.md`; ADR-0020 adds mirrors + selective vendoring |
| S4 | `03_openmetadata_dev.sh` uses upstream dev compose as-is (with `--build`) | Publishes 7 ports incl. JDWP 5005 and security-disabled OpenSearch on 0.0.0.0; `-p` doesn't isolate fixed container names | Lab override with `!reset/!override`, `compose_safe.sh` renders + **fails closed** via `check_port_exposure.py` |
| S5 | `04_create_s3.sh` SSE-S3 only, no bucket policy/lifecycle | No TLS enforcement, no KMS, no retention | `infrastructure/aws/s3/*` policy + lifecycle + KMS key policy |
| S6 | `05_install_cron.sh` logs grow forever | Disk fills | logrotate config; systemd timers with `OnFailure=` alerts preferred |
| S7 | `07_smoke.sh` `compileall ... || true` | Hides failures | `smoke_all.sh` reports pass/fail per step and exits non-zero |

## Backend, frontend, data model

| # | Starter | Problem | Kit fix |
|---|---|---|---|
| B1 | `search.py` sync `requests` in an async API; no RBAC beyond tenant term; no citations | Blocks the event loop; no service scoping; answers can't be cited | `SearchRouter` with typed routes, scope checks, budgets, timeouts, citation registry |
| B2 | `context_contract.py` unbounded `filters`, actions validated only by name | Oversized/forged context; arbitrary args | Size-limited validated context; per-action pydantic schemas; scope checks; approvals |
| B3 | No agent endpoint, no runtime bridge | Master prompt core requirement | AG-UI FastAPI endpoint + Node runtime bridge, contract + E2E tests |
| F1 | `CopilotKitV2Host.example.tsx` | Imports were correct for V2 (verified), but no auth headers, tools, persistence | Provider with async auth headers, frontend tools, HITL, renderers, thread restore |
| D1 | `sql/001` no RLS, `messages` without tenant_id, edges without provenance/validity rules | Cross-tenant leakage risk; unverifiable graph | Migrations 0001-0007 with roles, RLS (tested), provenance, temporal edges, audit |
| D2 | `incident_events.raw jsonb NOT NULL` | Raw logs in PostgreSQL | Not continued; curated tables only |

## Still open (needs your environment - tracked in [requirements-traceability.md](requirements-traceability.md))

- Real Opsi source inventory (run `scripts/phase0/inventory_opsi.py`), auth adapter for `OPSI_AUTH_MODE=existing`.
- Real vendor captures to replace synthetic fixtures; Grail field names in your tenant; Problems selector.
- Portkey routing config + Bedrock model/profile ids; Broadcom OI contract.
- OpenMetadata release-image deployment against dedicated RDS + OpenSearch; legal sign-off on the ingestion package licence.
- IAM roles/KMS keys created by Cloud Security; GuardDuty malware protection on the attachments bucket.
