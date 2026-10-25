# OpenMetadata: catalogue the Opsi database (metadata only)

1. **Legal first**: `openmetadata-ingestion` is under the Collate Community License (ADR-0018).
2. DBA applies `database/migrations/0007_openmetadata_reader_optional.sql` (edit the schema list), creates a LOGIN in
   `om_catalog_reader` (connection limit 2, statement timeout).
3. Install the CLI in its own venv, version-matched to the server:
   `python3.12 -m venv /opt/om-ingest-venv && /opt/om-ingest-venv/bin/pip install "openmetadata-ingestion[postgres]==2.0.6.*"`
4. `/etc/opsi/om-ingest.env` (0600) with: `OM_SERVICE_NAME, OM_PG_USER, OM_PG_PASSWORD, OM_PG_HOSTPORT, OM_PG_DATABASE,
   OM_PG_SSLMODE, OM_SCHEMA_INCLUDES_JSON, OM_API_URL, OM_INGESTION_BOT_JWT, OM_VERIFY_SSL`.
5. Run `run_metadata_ingest.sh` (renders `opsi-postgres-metadata.template.yaml` into a 0600 temp file, runs
   `metadata ingest -c`, deletes the file). Schedule daily.

The template enables tables/views only: no profiler, sample data, tags/owners import, stored procedures or DDL capture -
ownership and tags are curated in OpenMetadata itself. Field names verified against the v2.0.x Postgres connector docs.

Fallback without the CLI (if legal declines): Opsi-owned job pushing entities via REST
(`PUT /api/v1/services/databaseServices`, `/api/v1/databases`, `/api/v1/databaseSchemas`, `/api/v1/tables`) - check
request schemas in `<OM>/swagger.html` for your version.
