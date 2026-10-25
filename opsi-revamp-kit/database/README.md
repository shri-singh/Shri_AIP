# Database (Opsi application DB only - never OpenMetadata's)

```
migrations/0000_migration_ledger.sql          opsi_meta.schema_migrations
migrations/0001_roles_and_schemas.sql         NOLOGIN group roles opsi_owner/app/ingest_writer/readonly; schemas
migrations/0002_ingest.sql                    collector state (PG backend) + curated problems/signatures/samples
migrations/0003_chat.sql                      folders, threads, messages, tags, attachments, runs, tool runs, evidence, approvals, feedback, audit
migrations/0004_knowledge.sql                 ontology: kinds, relation types, entities, edges (time + provenance), neighborhood(), catalog xrefs
migrations/0005_rls.sql                       RLS: RESTRICTIVE tenant policies + owner/visibility policies, FORCE RLS
migrations/0006_pgvector_optional.sql         documents with vector(1024) + HNSW (optional)
migrations/0007_openmetadata_reader_optional.sql   REFERENCES-only role for OpenMetadata's connector (optional)
migrations/rollback/000N_down.sql             guarded (SET opsi.allow_destructive='yes' required)
samples/synthetic_seed.sql                    demo tenant 'tenant-demo' (lab only)
validate/validate_migrations.mjs              PGlite: apply, re-apply, seed, 30+ RLS/constraint checks, rollbacks
validate/serve_pglite.mjs                     throwaway wire-protocol PostgreSQL for integration tests
```
Compatible with PostgreSQL 13+ (`gen_random_uuid`, generated columns, RESTRICTIVE policies); validated on 18.

## Validate locally (no server)
```bash
cd database/validate && npm ci && node validate_migrations.mjs     # expect "ALL CHECKS PASSED"
```

## Apply (DBA)
1. Rehearse on a restored snapshot (runbook). 2. `MIGRATE_DATABASE_URL=... scripts/migrate.sh status`.
3. `scripts/migrate.sh apply --yes [--approval CHG-123]` (optional files need `--include-optional` or `--only <file>`).
4. Create LOGIN users and grant groups:
```sql
CREATE ROLE opsi_api_svc LOGIN PASSWORD '<from secrets manager>' IN ROLE opsi_app;
CREATE ROLE opsi_collector_svc LOGIN PASSWORD '...' IN ROLE opsi_ingest_writer;
ALTER ROLE opsi_api_svc SET statement_timeout = '15s';
ALTER ROLE opsi_api_svc SET idle_in_transaction_session_timeout = '60s';
```

## Using Alembic instead
One revision per file:
```python
from pathlib import Path
from alembic import op
SQL = Path(__file__).parents[2] / "database/migrations/0003_chat.sql"   # adjust
def upgrade(): op.execute(SQL.read_text())
def downgrade(): op.execute("SET opsi.allow_destructive = 'yes';" + (SQL.parent / "rollback/0003_down.sql").read_text())
```

## If the starter's `sql/001_opsi_extensions.sql` was already applied
Its `opsi_ingest.incident_events` (raw jsonb) and `opsi_chat`/`opsi_knowledge` tables conflict in shape. Rename the old
schemas (`ALTER SCHEMA opsi_chat RENAME TO opsi_chat_starter;` etc.) after exporting, then apply 0000+; migrate any data
deliberately. Don't drop without a backup.
