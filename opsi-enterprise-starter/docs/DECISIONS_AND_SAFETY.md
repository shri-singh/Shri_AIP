# Decisions, constraints, and things NOT to conflate

1. OpenMetadata (the product) is distinct from OpenStack (the cloud platform). Here, **OpenMetadata** is intended.
2. OpenMetadata's backend is not a plug-in React widget; start as a separate backend and selectively adapt UI.
3. The source repo and release runtime are distinct. The upstream `docker/development/docker-compose-postgres.yml` is a **development build**, may take considerable RAM/CPU and disables OpenSearch security. Review it before execution; do not publish its ports or use it as the production config.
4. The catalog's OpenSearch should not become the primary multi-TB logs cluster. Use separate roles/indexes and verify availability/reindex strategy.
5. CopilotKit **V2** only: `@copilotkit/react-core/v2`, `CopilotKitProvider`, and AG-UI; avoid V1 examples that use `<CopilotKit>` from old modules. Verify current exports against installed version.
6. A CopilotKit React provider cannot replace its compatible **runtime/AG-UI endpoint**. Build a runtime bridge to FastAPI or use the official supported integration. Do not fake a plain SSE stream and call it AG-UI compliant.
7. Do not point Opsi at OpenMetadata's *DB tables* directly. Connect the metadata API and preserve its migrations.
8. Source logs are untrusted: remove credentials, tokens, PII and injected instructions before passing to Bedrock. Retain immutable evidence references and model prompt safeguards.
9. `aws s3` Parquet is a **data archive**, not a restorable PostgreSQL snapshot. For RDS/Aurora use native snapshots/PITR/approved AWS Backup. Snapshot-to-S3 Parquet exports are **not directly restorable as databases**.
10. Collector checkpoints advance only after S3 upload **and** curated PostgreSQL commit, if configured. Deterministic upsert IDs and overlapping windows help retry; they do not guarantee full exactly-once delivery. Address late arrivals, delete/update semantics and DLQ before production.
11. The delivered collectors are bounded starter examples: Grail `limit` can truncate a high-volume interval, so the code fails if the limit is reached. Production backfills must partition time/filters, account for vendor rate limits and prove completeness.
12. Credentials: use EC2 instance profile for AWS, dedicated least-privilege Elasticsearch and Dynatrace accounts, and an approved secret store or restricted env file. GitHub PAT only in credential manager or `GH_TOKEN` prompt; never in URL or `git remote -v`.
13. Internal licensing: Apache 2.0 permits reuse with notice and license obligations. Review individual vendored assets, fonts, images, and dependencies.
14. Portkey routing to Bedrock must be validated against the actual enterprise Portkey deployment/configuration; the generic gateway adapter in this starter is deliberately not a claimed working client.
15. `Broadcom OI` APIs/authorization differ by installation; leave disabled until contract and sample payloads are known.
16. For highly sensitive environments, don't export corporate logs/code onto personal machines without approval. Scan package before transfer.
17. The upstream repositories change. Pin immutable commit SHA/tag, record licenses and SHA, run supply-chain checks, and avoid auto-merging updates into production.
