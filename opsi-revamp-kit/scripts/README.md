# Scripts

| Script | Changes anything? | Purpose |
|---|---|---|
| `preflight.sh` | no | tools/versions, identity, time sync, resources, env-file permissions |
| `phase0/inventory_host.sh [--check-egress]` | no (writes `inventory/`) | host inventory |
| `phase0/inventory_opsi.py <repo> --out inventory/` | no | Opsi source inventory (names/versions only; flags possible secrets) |
| `clone_repos.sh [dir]` | creates clones | baseline + revamp clones, legacy push disabled, never pushes |
| `fetch_upstreams.sh [dest_dir]` | creates clones | pinned OpenMetadata/CopilotKit study clones (default `~/workspaces/upstream`, push disabled) + PROVENANCE.md |
| `repo/workspace.py <init, status, verify, upstream-updates> --manifest f` | `init` clones missing repos, sets push URLs | manifest-driven workspace; read-only roles enforced; exit 1 on policy violations |
| `repo/vendor_component.py <add, update, verify, mark-modified, diff-upstream, notices, list>` | `add/update/mark-modified` write `third_party/` | selective vendoring with provenance, licence copy, approval and modification records |
| `repo/repo_hygiene.py [--repo-root]` | no | fails on submodules, gitlinks, stray licences, junk, big files, `package.json` without lockfile |
| `repo/mirror_upstream.sh <upstream> <mirror> [cache]` | pushes to the **mirror** URL you give | private mirror sync (branches + tags only); for the mirror job/service account |
| `compose_safe.sh <stack> <action>` | `up/down` only | render + port check (fails closed) before any compose action |
| `check_port_exposure.py` | no | parse `docker compose config --format json`, fail on non-loopback ports |
| `migrate.sh status` / `migrate.sh apply --yes` | `apply` | ordered SQL migrations with checksum ledger |
| `backup_restore_drill.sh` | restores into a `*drill*` DB | logical dump/restore + row-count comparison |
| `health.sh` | no | health of API, runtime, collector, OpenMetadata, ingestion |
| `smoke_all.sh` | no | every local check with PASS/FAIL/SKIP summary |
| `secret_scan.py [dir]` | no | secret-looking strings (file:line:pattern, never values) |
| `license_scan.sh` | writes `reports/` | Python/Node licence reports + review lists |
| `sync_redaction.py [--check]` | `--check` no | keep the API's redaction copy identical to the collectors' |
All shell scripts pass `bash -n`; Python scripts use only the standard library unless noted.
