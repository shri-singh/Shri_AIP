# Licence inventory and NOTICE obligations

Not legal advice. This inventory gives legal/compliance reviewers the facts; decisions belong to them.
Regenerate dependency reports with `scripts/license_scan.sh` (writes `reports/licenses-*/` incl. `*-REVIEW.csv`).

## 1. Components used by the kit

| Component | Version | Licence (SPDX) | How used | Obligation / note |
|---|---|---|---|---|
| CopilotKit (`@copilotkit/react-core`, `@copilotkit/runtime`) | 1.79.1 | MIT | npm dependency | keep copyright notice in distributions |
| AG-UI (`@ag-ui/client`, `ag-ui-protocol`) | 1.0.2 / 1.0.0 | MIT | dependency | notice |
| OpenMetadata server | 2.0.6 | Apache-2.0 | separate service (container image) | NOTICE file if redistributed; state changes if modified |
| **openmetadata-ingestion** (PyPI) / repo `ingestion/` | 2.0.6.x | **Collate Community License Agreement 1.0** (not OSI) | `metadata` CLI for catalogue ingestion | **legal review required** (ADR-0018): Excluded Purpose (competing SaaS), keep notices, no sublicensing, auto-termination on breach |
| FastAPI | 0.162.0 | MIT | dependency | notice |
| Starlette | 1.9.0 | BSD-3-Clause | dependency | notice |
| pydantic | 2.14.1 | MIT | dependency | notice |
| uvicorn | 0.54.0 | BSD-3-Clause | dependency | notice |
| httpx | 0.28.1 | BSD-3-Clause | dependency | notice |
| python-multipart | 0.0.32 | Apache-2.0 | dependency | notice |
| psycopg / psycopg-pool | 3.3.6 / 3.3.3 | **LGPL-3.0-only** | dynamically imported library | LGPL: allow replacement of the library; don't statically bundle modified copies without compliance review |
| pyarrow | 26.0.0 | Apache-2.0 | dependency | notice |
| boto3 / botocore | 1.43.118 | Apache-2.0 | dependency | notice |
| elasticsearch (py client) | 8.19.3 | Apache-2.0 | dependency | client only (the Elasticsearch *server* licence is separate: Elastic License 2.0 / SSPL / AGPL - your existing cluster) |
| portkey-ai | 2.3.4 | MIT | dependency | notice; Portkey service terms separate |
| PyJWT / cryptography | 2.15.1 / 50.x | MIT / Apache-2.0 OR BSD-3-Clause | dependency | notice |
| jsonpatch | 1.36 | BSD-3-Clause | dependency | notice |
| requests / python-dotenv | 2.34.2 / 1.2.4 | Apache-2.0 / BSD-3-Clause | dependency | notice |
| OpenTelemetry SDK/exporter/instrumentation | 1.45.1 / 0.66b1 | Apache-2.0 | dependency | notice |
| otelcol-contrib image | 0.137.0 | Apache-2.0 | container | notice |
| ECharts | 6.1.0 | Apache-2.0 | npm dependency (web) | NOTICE (ECharts ships one) |
| React Flow (`@xyflow/react`) | 12.12.0 | MIT | npm dependency | notice (pro features not used) |
| zod | 4.6.7 | MIT | dependency | notice |
| React | 19.x (or Opsi's 18.x) | MIT | dependency | notice |
| PGlite (`@electric-sql/pglite`, `-socket`, `-pgvector`) | 0.5.11 / 0.2.14 / 0.0.12 | Apache-2.0 (+ PostgreSQL License) | **test tooling only** | not shipped |
| pgvector (extension) | per RDS version | PostgreSQL License | DB extension | notice |
| Mermaid CLI | 11 | MIT | docs tooling only | not shipped |
| NGINX | existing | BSD-2-Clause | existing | - |

## 2. OpenMetadata UI dependencies (if any UI code were reused)
Full list: [reference/openmetadata-ui-2.0.6-dependency-licenses.tsv](reference/openmetadata-ui-2.0.6-dependency-licenses.tsv)
(113 runtime deps: 90 MIT, 12 Apache-2.0, 3 BSD-3-Clause, 1 ISC, 3 OFL-1.1 fonts, plus):

| Package | Licence | Why it matters |
|---|---|---|
| `@melloware/react-logviewer` | MPL-2.0 | file-level copyleft: modified files must stay MPL |
| `elkjs` | EPL-2.0 OR GPL-3.0-or-later | choose EPL-2.0; weak copyleft obligations |
| `dompurify` | MPL-2.0 OR Apache-2.0 | choose Apache-2.0 |
| `@fontsource*` | OFL-1.1 | fonts: OFL terms (no selling fonts alone, name restrictions) |
| `@openmetadata/ui-core-components` | workspace link (repo Apache-2.0) | verify file headers |
The kit's decision (ADR-0002): **no wholesale copy** of OpenMetadata UI code. If a specific file is adapted later,
record it in section 3.

## 3. Copied or adapted third-party code (fill in when it happens)

| File in revamp | Origin (repo@sha:path) | Licence | Modified? | Notice added? | Reviewer |
|---|---|---|---|---|---|
| *(none so far)* | | | | | |

Rules: keep the original licence header; add "Modified by <company> on <date>"; add the licence text to `THIRD_PARTY_NOTICES`;
never copy from `ingestion/` (CCLA) without legal approval.
In the product repo this table is backed by `third_party/VENDORED.json`: add files only with
`scripts/repo/vendor_component.py add` (records repo@sha:path, SPDX, licence/notice copies, approval) and generate
`THIRD_PARTY_NOTICES.md` with `vendor_component.py notices`. See [repository-strategy.md](repository-strategy.md).

## 4. NOTICE template (ship with any distribution)

```
This product includes software developed by:
- CopilotKit (MIT License) - https://github.com/CopilotKit/CopilotKit
- AG-UI Protocol (MIT License) - https://github.com/ag-ui-protocol/ag-ui
- Apache ECharts (Apache License 2.0) - https://echarts.apache.org  [include ECharts NOTICE]
- xyflow / React Flow (MIT License) - https://github.com/xyflow/xyflow
- OpenTelemetry (Apache License 2.0) - https://opentelemetry.io
- Apache Arrow (Apache License 2.0) - https://arrow.apache.org
... (generate the full list with scripts/license_scan.sh)
OpenMetadata is used as a separately deployed service (Apache License 2.0).
psycopg is used under the GNU LGPL v3; its source is available at https://github.com/psycopg/psycopg.
```

## 5. Review checklist before production
- [ ] `scripts/license_scan.sh` run on the final lockfiles; every `*-REVIEW.csv` row decided.
- [ ] Legal decision recorded for `openmetadata-ingestion` (ADR-0018).
- [ ] LGPL compliance confirmed for psycopg in your packaging (wheels installed unmodified in a venv are typical).
- [ ] No GPL/AGPL/SSPL code linked into Opsi.
- [ ] Fonts/icons/images licences checked if any are added to the UI.
- [ ] THIRD_PARTY_NOTICES generated and shipped.
