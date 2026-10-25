# PostgreSQL / psql

## Connect
```bash
psql "postgresql://user@host:5432/db?sslmode=require"        # password via ~/.pgpass (chmod 600) or PGPASSWORD for one command
psql -X -v ON_ERROR_STOP=1 -f file.sql "$URL"                 # scripts: no psqlrc, stop on error
\conninfo  \dn  \dt opsi_chat.*  \d+ opsi_chat.threads  \du  \dp opsi_chat.threads  \x auto  \timing on
```

## Act like the app (RLS)
```sql
BEGIN;
SET LOCAL ROLE opsi_app;                                    -- if your login may
SELECT set_config('opsi.tenant_id', 'tenant-a', true), set_config('opsi.user_id', 'alice', true);
SELECT id, title FROM opsi_chat.threads ORDER BY last_message_at DESC LIMIT 5;
ROLLBACK;
SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname LIKE 'opsi%' OR rolname = current_user;
SELECT schemaname, tablename, rowsecurity, forcerowsecurity FROM pg_tables WHERE schemaname LIKE 'opsi%';
SELECT * FROM pg_policies WHERE schemaname = 'opsi_chat';
```

## Health, locks, sizes
```sql
SELECT pid, usename, state, wait_event_type, now()-query_start AS age, left(query,80) FROM pg_stat_activity
 WHERE state <> 'idle' ORDER BY age DESC;
SELECT l.locktype, l.mode, l.granted, a.pid, left(a.query,60) FROM pg_locks l JOIN pg_stat_activity a USING (pid) WHERE NOT l.granted;
SELECT nspname, pg_size_pretty(sum(pg_total_relation_size(c.oid))) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE nspname LIKE 'opsi%' GROUP BY 1;
SELECT relname, n_live_tup, n_dead_tup, last_autovacuum FROM pg_stat_user_tables WHERE schemaname LIKE 'opsi%' ORDER BY n_live_tup DESC;
SELECT pg_cancel_backend(<pid>);   -- polite;  pg_terminate_backend(<pid>) - last resort
```

## Session safety for manual DDL
```sql
SET lock_timeout = '5s'; SET statement_timeout = '15min';
CREATE INDEX CONCURRENTLY IF NOT EXISTS ...;   -- outside a transaction block
```

## Migrations and drills
```bash
MIGRATE_DATABASE_URL=$URL scripts/migrate.sh status
MIGRATE_DATABASE_URL=$URL scripts/migrate.sh apply --yes --approval CHG-123
psql "$URL" -c "select version, applied_at, applied_by from opsi_meta.schema_migrations order by version"
pg_dump -Fc --schema=opsi_chat -f chat.dump "$URL";  pg_restore -l chat.dump | head
```

## Ingestion checks
```sql
SELECT set_config('opsi.tenant_id','<tenant>',false);
SELECT source, max(window_end) AS freshest FROM opsi_ingest.error_signature_windows GROUP BY 1;
SELECT status, count(*) FROM opsi_ingest.outbox GROUP BY 1;               -- PG state backend
SELECT source, dataset, committed_until FROM opsi_ingest.watermarks;
```
