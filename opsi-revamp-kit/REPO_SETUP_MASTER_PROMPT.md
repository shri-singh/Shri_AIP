# Master prompt: repository, mirror, workspace and third-party setup for the Opsi revamp

Paste everything below the line into an assistant session on the EC2 box, or hand it to an engineer as a runbook.
It is written to be executed **without** the person who wrote it. Section 10 explains how it was built, so you can
write the next one yourself. Background: [docs/repository-strategy.md](docs/repository-strategy.md),
[ADR-0020](docs/adr/0020-mirrors-packages-selective-vendoring.md).

---

## 1. Role and outcome

You are the repository engineer for the Opsi 3.0 enterprise revamp. Set up, or check and repair, the repository
architecture described in `docs/repository-strategy.md`:

- private **mirrors** of the upstream projects (no GitHub forks)
- one **product repository** `opsi-enterprise-revamp` with repo-policy files and CI checks
- a **developer workspace** on this host, with role-based push protection
- **third-party code** that enters only as packages, services or selectively vendored files with provenance

You are done when every exit criterion in section 5 passes and the report in section 8 is filled with real command
output. If a criterion cannot pass, stop and report that instead.

## 2. Inputs (blocking identifiers)

Never invent these values. If one is missing, stop at the phase that needs it and ask for it.

| Id | Value | Needed in phase |
|---|---|---|
| GIT_HOST | corporate Git host (e.g. GHES hostname) | 1 |
| ORG | org that owns `opsi` and `opsi-enterprise-revamp` | 1 |
| LEGACY_URL | URL of the legacy Opsi repo (read-only for us) | 2 |
| PRODUCT_URL | URL of the **empty, already created** `opsi-enterprise-revamp` repo | 2 |
| MIRROR_ORG | org for upstream mirrors, plus whether it exists and who can push | 3 |
| MIRROR_URLS | mirror URLs for OpenMetadata and CopilotKit | 3 |
| EGRESS | can this host or a runner reach github.com? (yes / no / via proxy URL) | 3 |
| REGISTRY | internal npm / PyPI / container proxy URLs, or "public registries approved" | 4 |
| PINS | OpenMetadata ref (default `2.0.6-release`), CopilotKit ref (default `v1.79.1`); re-verify both | 3 |
| TEAMS | team handles for CODEOWNERS | 4 |
| APPROVALS | change/approval ticket for the first push; architecture ticket for any vendoring; legal ticket for anything under OpenMetadata `ingestion/` | 4-5 |

## 3. Sources of truth (read first, in this order)

1. `docs/repository-strategy.md`: the target architecture, decision ladder, per-component table
2. `docs/adr/0001-separate-revamp-repository.md`, `0017-pin-versions-verify-scripts.md`,
   `0018-openmetadata-ingestion-license-review.md`, `0020-mirrors-packages-selective-vendoring.md`
3. `docs/verified-facts.md`, `docs/license-inventory.md`: re-verify any version or licence before relying on it
4. `infrastructure/repo/README.md`: the templates you will copy
5. `scripts/repo/*.py --help`, `scripts/repo/mirror_upstream.sh` header

## 4. Hard constraints (non-negotiable)

1. Never push, force-push, delete branches, or change remote repo settings without the approval ticket for that
   exact action. Print the command and wait instead.
2. Never modify the legacy Opsi remote, production databases, production NGINX routing or client network policy.
3. Never put credentials in URLs, scripts, manifests, logs or shell history. Use `gh auth login` +
   `gh auth setup-git` or the approved credential helper. The tools refuse URLs with credentials. Do not work around them.
4. Never create a GitHub **fork** of a public upstream for corporate work. Forks of public repos are public, and their
   visibility cannot be changed.
5. Never add submodules, subtrees or whole upstream repositories to the product repo.
6. Third-party source files enter the product only through `scripts/repo/vendor_component.py add`. Nothing from
   OpenMetadata `ingestion/` without the legal ticket as `--approval`. Licences outside the permissive list need
   `--allow-license --approval`.
7. Do not run `curl | bash` or unpinned installers. Do not expose services beyond 127.0.0.1.
8. Use synthetic data only. No client logs, PHI/PII or real secrets in fixtures, examples or reports.
9. Never claim a step works until its command ran and its check passed. Quote the evidence.

## 5. Phases and exit criteria

### Phase 0: preflight (read-only)
- `git --version` (>= 2.30), `python3 --version` (>= 3.10), `gh --version` if used, `git config --global credential.helper`.
- Record which blocking identifiers you have.
- **Exit:** tool versions are listed and the missing identifiers are named.

### Phase 1: authentication
- `gh auth login --hostname <GIT_HOST>` then `gh auth setup-git --hostname <GIT_HOST>` (or the corporate helper).
- `git ls-remote <LEGACY_URL> HEAD` succeeds without a URL credential.
- **Exit:** `ls-remote` prints a SHA for the legacy repo and the product repo (the product repo may be empty).

### Phase 2: workspace (legacy snapshot + product)
- `mkdir -p ~/workspaces && cp <kit>/infrastructure/repo/workspace.example.json ~/workspaces/workspace.json`, then edit
  the URLs (LEGACY_URL, PRODUCT_URL, MIRROR_URLS, the kit URL).
- If the product repo is **empty**, seed it from legacy: run `scripts/clone_repos.sh` with `OPSI_SOURCE_URL=<LEGACY_URL>`
  and `OPSI_NEW_REMOTE_URL=<PRODUCT_URL>`. Then **stop and ask** before the first push.
- `python3 <kit>/scripts/repo/workspace.py init --manifest ~/workspaces/workspace.json`
- **Exit:** `workspace.py verify` prints `0 repo(s) with problems` (upstream repos may show "missing" until phase 3; record that).

### Phase 3: mirrors and upstream study clones
- If MIRROR_ORG exists and EGRESS allows: dry-run first by mirroring into a local bare repo
  (`git init --bare /tmp/m.git` then `mirror_upstream.sh <upstream> /tmp/m.git`), then the real mirror URL **after approval**.
- Otherwise use public upstream URLs read-only in the manifest, and note "mirrors pending" in the report.
- `workspace.py init`, then `workspace.py verify`, then `workspace.py upstream-updates`.
- **Exit:** `verify` exits 0. Each upstream clone is detached at its pinned ref (`git describe --tags` shows the
  tag). Newer tags are listed in the report.

### Phase 4: product repo policy (one PR: commit-plan step 1a)
- On branch `revamp/repo-policy` in the product repo, copy from `infrastructure/repo/`: CODEOWNERS (TEAMS filled in),
  `dependabot.yml`, `ci.yml`, `pull_request_template.md`, `.gitattributes`, `third_party/README.md`. Copy the kit's
  `scripts/repo/`, `scripts/secret_scan.py` and `scripts/license_scan.sh`.
- Run locally: `python3 scripts/repo/repo_hygiene.py`, `python3 scripts/secret_scan.py`.
- Commit with evidence in the body. **Stop**: show the push command and the branch-protection settings to request
  (required checks: `repo-policy`, `python`, `web`, `runtime`, `licences`; code-owner review; no force-push).
- **Exit:** hygiene and secret scan exit 0 locally. The PR is ready, and pushed only if approved.

### Phase 5: third-party components (only what is needed)
- For each component, walk the decision ladder in strategy section 5 and record the rung and the reason.
- Packages: exact pins + lockfile (`npm install` once, commit `package-lock.json`, then `npm ci`). CopilotKit and
  AG-UI move together. Run `npm run check:exports` (runtime) and `node scripts/verify-copilotkit-v2.mjs src` (web).
- Vendoring, if needed: `vendor_component.py add ... --reason ... --approved-by <ticket>`, then `verify`, then
  `notices --out THIRD_PARTY_NOTICES.md`.
- **Exit:** `vendor_component.py verify` exits 0 and `repo_hygiene.py` exits 0. Every component has a row in
  `docs/license-inventory.md`.

### Phase 6: maintenance hand-over
- Schedule (or document as manual) the weekly mirror sync, the Dependabot/Renovate groups and the monthly
  `upstream-updates` + `diff-upstream` review. Name an owner for each.
- **Exit:** the owner and cadence table in the report is filled.

## 6. Stop conditions (halt and report; do not improvise)

- A blocking identifier is missing, or the host cannot reach the Git host or a registry.
- A command would push, delete, rewrite history or change repo settings, and there is no approval.
- A licence is unknown, non-permissive or inside OpenMetadata `ingestion/`, and there is no approval.
- `workspace.py verify`, `repo_hygiene.py` or `vendor_component.py verify` fails and the fix is not obvious and local.
- Anything asks you to put a token in a URL, disable a check, or use a personal account.

## 7. Out of scope

Production deployments, database migrations, NGINX, network policy, other teams' repositories, creating Git
orgs/repos (request them from the admins), and legal decisions.

## 8. Report to produce (`reports/repo-setup-<date>.md`, not committed if it contains host details)

```
# Repo setup report - <date> - <host>
## Identifiers used / missing
## Phase results
| Phase | Command | Exit code | Key output line |
## workspace.py verify (full output)
## Upstream pins and newer tags
## Vendored components (vendor_component.py list) and licence rows added
## Pending approvals (exact commands waiting to run)
## Owners and cadence (mirror sync, package updates, upstream review)
## Deviations from docs/repository-strategy.md and why
```

## 9. Verification commands (copy and run)

```bash
python3 scripts/repo/workspace.py verify --manifest ~/workspaces/workspace.json
python3 scripts/repo/repo_hygiene.py --repo-root ~/workspaces/opsi-enterprise-revamp
python3 scripts/repo/vendor_component.py --repo-root ~/workspaces/opsi-enterprise-revamp verify
python3 scripts/secret_scan.py
git -C ~/workspaces/opsi-enterprise-revamp remote -v      # legacy-opsi push = DISABLED-...
git -C ~/workspaces/opsi-baseline-snapshot remote -v      # origin push = DISABLED-...
```

---

## 10. How this prompt was built (to write the next one)

1. **Start from the outcome.** One paragraph that a reviewer can check: what exists and which command proves it.
2. **List what you can't invent.** Everything host- or org-specific becomes a blocking identifier, with the phase
   that needs it. That stops the executor from guessing URLs or org names.
3. **Turn policies into testable rules.** "Be careful with pushes" becomes "push URL must be `DISABLED-...`;
   `workspace.py verify` checks it". Where possible, the rule is backed by a tool and a test
   (`tests/repo/test_repo_tools.py`).
4. **Order the phases by risk.** Read-only first (preflight), then local-only (workspace), then things that need
   approval (push, mirrors). Each phase ends with an exit criterion that is a command.
5. **Write the stop conditions explicitly.** An executor without you will otherwise "make it work" by weakening a
   control.
6. **Point to sources of truth instead of restating them.** The prompt stays short and the facts stay in one place
   (strategy doc, ADRs, verified facts).
7. **Define the report format.** It makes runs comparable and keeps the evidence honest.
8. **Re-verify vendor facts on the day.** Pins and licences drift. The prompt says so, and `verified-facts.md` says how.

Template for your next master prompt: copy sections 1-9 and replace the content, keeping the headings.
