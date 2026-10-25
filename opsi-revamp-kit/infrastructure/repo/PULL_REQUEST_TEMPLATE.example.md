<!-- Copy to .github/pull_request_template.md in opsi-enterprise-revamp -->
## What and why
<!-- One paragraph. Link the ticket and the commit-plan step (docs/commit-plan.md). -->

## Third-party code and dependencies
- [ ] No new third-party code, **or** it was added with `scripts/repo/vendor_component.py add` (provenance + licence recorded)
- [ ] Vendored files I edited are recorded with `vendor_component.py mark-modified --note ...`
- [ ] New/changed packages are pinned exactly and the lockfile is committed
- [ ] CopilotKit / AG-UI bumps moved together and `verify-*.mjs` passed
- [ ] Nothing copied from OpenMetadata `ingestion/` (Collate Community License) without the legal ticket: ____

## Safety
- [ ] No secrets, tokens, client data or real log samples (synthetic fixtures only)
- [ ] No ports published beyond 127.0.0.1; no changes to legacy Opsi, production DB, NGINX or network policy
- [ ] Identity/tenant comes from the verified token; RLS untouched or tests updated

## Evidence
<!-- Paste the commands you ran and their result lines (pytest summary, tsc exit code, verify scripts). -->

## Rollback
<!-- `git revert <sha>` is enough? Migrations? Feature flag? -->
