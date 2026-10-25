# third_party/

Code in this folder was **not written by us**. It is copied, selectively and on purpose, from pinned upstream
releases. Everything else we use from open source comes in as packages (npm/PyPI/container images) and is not here.

Rules (docs/repository-strategy.md, ADR-0020):

1. Add or update only with `python3 scripts/repo/vendor_component.py add|update ...` - never copy by hand.
   The tool records upstream URL, tag, commit, source path, SPDX licence, approval and a SHA-256 per file in
   `VENDORED.json`, and copies the nearest LICENSE/NOTICE into `third_party/<project>/`.
2. Prefer not to edit. If you must, edit and then run `vendor_component.py mark-modified --id <id> --note "..."`;
   the note goes into `THIRD_PARTY_NOTICES.md` ("Modified by ...").
3. CI runs `vendor_component.py verify` and `repo_hygiene.py`; unrecorded edits, stray files or missing licences fail the build.
4. Nothing from OpenMetadata `ingestion/` (Collate Community License) without a legal ticket recorded as `--approval`.
5. Regenerate notices after any change: `vendor_component.py notices --out THIRD_PARTY_NOTICES.md`.

| id | project | upstream ref | what / why |
|---|---|---|---|
| *(run `vendor_component.py list`)* | | | |
