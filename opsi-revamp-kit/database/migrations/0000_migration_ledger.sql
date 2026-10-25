-- 0000 - migration ledger used by scripts/migrate.sh
-- Target: the Opsi APPLICATION database (never OpenMetadata's database).
-- Compatible with PostgreSQL 13+ / Aurora PostgreSQL 13+.
-- If Opsi already uses Alembic, wrap each file in an Alembic revision instead
-- (op.execute(Path(...).read_text())) and skip this ledger. See database/README.md.

CREATE SCHEMA IF NOT EXISTS opsi_meta;

CREATE TABLE IF NOT EXISTS opsi_meta.schema_migrations (
    version     text PRIMARY KEY,
    checksum    text NOT NULL,          -- sha256 of the .sql file as applied
    applied_at  timestamptz NOT NULL DEFAULT now(),
    applied_by  text NOT NULL DEFAULT current_user,
    notes       text
);

COMMENT ON TABLE opsi_meta.schema_migrations IS
  'Opsi revamp SQL migrations. A changed checksum for an applied version means someone edited history: stop and investigate.';
