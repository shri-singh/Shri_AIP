# ADR-0018: OpenMetadata ingestion package requires legal review
- Status: Proposed (pending legal)
- Date: 2026-10-24

## Context
The master prompt prefers Apache-2.0/MIT for copied code and asks for legal review when uncertain. Verified on
2026-10-24: the OpenMetadata *server* repository is Apache-2.0, but the `openmetadata-ingestion` PyPI package
(1.12.x and 2.0.x) and the repo's `ingestion/` directory are licensed under the **Collate Community License
Agreement 1.0**: use, modification and distribution allowed, but not for an "Excluded Purpose" (offering a
competing SaaS/PaaS); notices must be retained; no sublicensing; termination on breach. The `metadata ingest` CLI
and the ingestion container image both use this package.

## Decision
- Do not copy any code from `ingestion/` into Opsi.
- Using the CLI/container to catalogue Opsi's own databases internally is *likely* within the licence, but must be
  confirmed by legal before production use. Record the decision here.
- Fallback if legal declines: push metadata through OpenMetadata's REST API with Opsi-owned code (create/update
  databaseService, database, databaseSchema, table entities) - more work, fully Apache/MIT.

## Verification
`docs/license-inventory.md` lists the package with licence and the legal decision reference.
