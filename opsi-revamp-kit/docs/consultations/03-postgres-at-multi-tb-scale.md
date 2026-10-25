# 03 - Working safely next to a multi-TB PostgreSQL

## The question
"Opsi's PostgreSQL is several TB and busy. How do we add schemas, indexes, RLS and new workloads without hurting it?"

## Short answer
Keep the revamp's data **small and separate** (own schemas, curated data only), apply DDL that only *creates* objects,
build any index on existing big tables `CONCURRENTLY` in a window, cap every session with `statement_timeout` and
`lock_timeout`, use dedicated roles, and move heavy reads (analytics, vectors) to a replica or S3/Athena.

## What the revamp adds and why it is light
| Object | Expected size | Write rate |
|---|---|---|
| `opsi_ingest.problems` | 10^4-10^6 rows | per window |
| `error_signature_windows` | O(signatures x windows) ~ 10^4-10^5 rows/day/source | per window, replace |
| `evidence_samples` | <= N per signature per window | per window |
| `opsi_chat.*` | users x threads x messages; MB-GB | interactive |
| `opsi_knowledge.*` | 10^3-10^6 entities/edges | low |
| `documents` (pgvector) | 10^3-10^5 chunks x 4 KB vectors | low |
No table holds raw logs (ADR-0006).

## Migration safety rules
1. Rehearse on a restored snapshot; measure time and locks (`SELECT * FROM pg_locks l JOIN pg_stat_activity a USING (pid)`).
2. Only `CREATE ... IF NOT EXISTS` on new objects in 0000-0007 - no rewrites of existing tables.
3. Session settings for any DDL touching existing tables: `SET lock_timeout='5s'; SET statement_timeout='15min';`
   and retry on lock timeout rather than queueing behind long transactions (a waiting `ALTER` blocks everyone behind it).
4. Indexes on large existing tables: `CREATE INDEX CONCURRENTLY` (not inside a transaction; `migrate.sh` runs files in a
   transaction - put such statements in a separate file run with `psql -f` outside a transaction).
5. Never `VACUUM FULL`/`CLUSTER` big tables in business hours; check bloat first.

## Runtime safety
- Roles per workload (`opsi_app`, `opsi_ingest_writer`, `opsi_readonly`, `om_catalog_reader`) with
  `ALTER ROLE ... SET statement_timeout` / `idle_in_transaction_session_timeout` / `CONNECTION LIMIT`.
- Connection budgets: API pool <= 10 per process; collectors 1 connection per index run; OM reader 2. Use RDS Proxy if
  connection counts grow (kit disables server-side prepares for compatibility).
- `tenant_tx` sets `statement_timeout` per transaction (default 15 s) - keeps a bad query from hogging the primary.
- Reads for dashboards/aggregations at scale -> **read replica** (point `PgIncidentStore` at a replica URL).

## RLS performance notes
- Policies call `opsi_meta.current_tenant()` (STABLE) - the planner evaluates it once per statement.
- Every tenant table leads its indexes with `tenant_id` - RLS filter + index prefix align.
- Child-table policies use `EXISTS (SELECT 1 FROM threads ...)` - covered by the primary key; fine at chat scale.
- Check plans as the app role: `SET ROLE opsi_app; SELECT set_config('opsi.tenant_id','t',false); EXPLAIN ANALYZE ...`.

## Retention jobs (add when volumes are known)
```sql
-- run as opsi_ingest_writer with opsi.tenant_id set per tenant, or as owner with RLS-aware loop
DELETE FROM opsi_ingest.evidence_samples WHERE window_start < now() - interval '90 days';
DELETE FROM opsi_ingest.error_signature_windows WHERE window_start < now() - interval '400 days';
```
Batch deletes (`... AND ctid IN (SELECT ctid ... LIMIT 10000)`) to avoid long locks; or switch to monthly partitions
(declarative partitioning by `window_start`, drop old partitions) once tables pass ~100 M rows.

## pgvector on the primary?
HNSW indexes live in memory when queried; 10^5 x 1024-dim float4 ~ 400 MB raw + graph overhead. Fine on a large instance;
otherwise put `documents` on a replica-readable path or a separate small RDS. Set `hnsw.ef_search` per query (route does 64).

## Backups vs exports
RDS snapshots + PITR are the backup. `pg_dump` of revamp schemas is a supplement. "Export snapshot to S3" = Parquet for
analytics, not restorable.

## Verify
`scripts/migrate.sh status` on staging/prod; `pg_stat_statements` top queries by `total_exec_time` for `opsi_*` schemas;
lock waits during migration windows = 0.
