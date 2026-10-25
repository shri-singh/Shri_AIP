# Repository templates

Templates for the repository strategy in [../../docs/repository-strategy.md](../../docs/repository-strategy.md)
([ADR-0020](../../docs/adr/0020-mirrors-packages-selective-vendoring.md)). Copy each one to its target, then
replace `ORG`, `git.corp.example` and the team handles.

| Template | Copy to | Purpose |
|---|---|---|
| `workspace.example.json` | `~/workspaces/workspace.json` | manifest for `scripts/repo/workspace.py` (roles, pinned upstream refs) |
| `CODEOWNERS.example` | product `.github/CODEOWNERS` | extra review for `third_party/`, lockfiles, CI and repo policy |
| `dependabot.example.yml` | product `.github/dependabot.yml` | grouped, weekly package updates (CopilotKit + AG-UI move together) |
| `ci-product.example.yml` | product `.github/workflows/ci.yml` | required checks: hygiene, vendored verify, notices, secrets, tests, V2 checks, licences |
| `mirror-sync.example.yml` | `upstream-mirrors-admin/.github/workflows/` | weekly private-mirror sync (branches + tags) by a service account |
| `gitattributes.example` | product `.gitattributes` | collapse vendored/generated files in diffs; consistent line endings |
| `PULL_REQUEST_TEMPLATE.example.md` | product `.github/pull_request_template.md` | third-party, safety and evidence checklist per PR |
| `third_party.README.example.md` | product `third_party/README.md` | rules for vendored code |
| `vendir.example.yml` | product `vendir.yml` (optional) | declarative alternative to `vendor_component.py` (verify syntax first) |

Validated while building the kit: every YAML parses and `workspace.example.json` is valid JSON. Not validated here
(needs your Git host): Actions runner labels, Dependabot availability on GHES, team handles.
