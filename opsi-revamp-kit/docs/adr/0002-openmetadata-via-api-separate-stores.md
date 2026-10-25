# ADR-0002: OpenMetadata as the catalog, used only through its API, with dedicated stores
- Status: Accepted
- Date: 2026-10-24

## Context
Opsi needs schema/table/column metadata, owners, teams, domains, tags/classification and data lineage.
OpenMetadata (Apache-2.0 server, release 2.0.6 at the time of writing) provides these with its own
PostgreSQL schema, search indices and migrations. 2.0 requires PostgreSQL >= 15 and OpenSearch 3.x or
Elasticsearch 9.x, runs its own migrations, and has no automated downgrade. Opsi's production PostgreSQL is
multi-TB and must not be destabilised.

## Decision
- OpenMetadata runs as a **separate deployment** (own compose project or host) with:
  a **dedicated PostgreSQL database** (separate RDS instance preferred; at minimum a separate database and role -
  never the Opsi app DB or the log DB) and a **dedicated, security-enabled search cluster**.
- Opsi integrates only through OpenMetadata's **REST API** (and optionally its MCP endpoint) using a read-only bot
  token held server-side. The browser never talks to OpenMetadata with a token.
- Opsi's own DB is catalogued by OpenMetadata via the PostgreSQL connector in **metadata-only, read-only** mode
  (`database/migrations/0007_openmetadata_reader_optional.sql`, `infrastructure/openmetadata/`).
- Cross-references are stored in `opsi_knowledge.catalog_xrefs` (FQN + UUID), refreshed via the API.
- UI: build Opsi-native components that call `/api/v2/catalog/*`; deep-link to the OpenMetadata UI for advanced
  work. OpenMetadata UI components are not copied wholesale (React 18 + antd 4 + i18next + its state/API layer).

## Consequences
- Two systems to operate and upgrade; OpenMetadata upgrades follow its release notes with a DB snapshot first.
- Catalog outages degrade `metadata_search` only; incident investigation continues.
- Bot token rotation is an operational task (runbook).

## Alternatives considered
- Read OpenMetadata's tables directly - couples Opsi to internal schemas that change every release (2.0 renamed
  tables); forbidden by the master prompt.
- Share Opsi's PostgreSQL schema - uncontrolled competing migrations; forbidden.
- Build a catalog inside Opsi - duplicates a mature product.

## Verification
`scripts/compose_safe.sh openmetadata config` shows no bundled DB/search and loopback-only ports; code search finds
no SQL against OpenMetadata tables; `catalog/openmetadata.py` is the only integration point.
