# ADR-0020: Private mirrors instead of forks; components as packages; selective vendoring with provenance
- Status: Accepted (refines the upstream-location bullet of ADR-0001)
- Date: 2026-10-24

## Context
The revamp mixes components from OpenMetadata (about 3.2 GB repo, Apache-2.0 except `ingestion/`, which is under the
Collate Community License), CopilotKit/AG-UI (MIT, fast-moving npm packages) and several smaller libraries. The
enterprise wants one clean, reviewable product repository and no exposure of internal code. On GitHub, a fork of a
public repository is public, and its visibility cannot be changed. GitHub Enterprise Server cannot fork github.com
repositories at all. ADR-0001 put upstream study clones in a `vendor/` folder next to the product clone, which
conflicts with the term "vendoring" and had no mechanism for bringing selected files into the product.

## Decision
- **Mirrors, not forks.** Public upstreams are mirrored (branches + tags only) into a private `upstream-mirrors` org
  by a scheduled job (`scripts/repo/mirror_upstream.sh`). Humans never push to mirrors.
- **One product repository** (`opsi-enterprise-revamp`). It has no submodules, no subtrees and no whole upstream
  repositories.
- **Decision ladder** for every component: service, then package, then code generated from a contract, then
  selectively vendored files, then a temporary package patch, then a patched fork (a separate repo publishing an
  internal package). Take the first rung that works.
- **Selective vendoring** only through `scripts/repo/vendor_component.py`: files under `third_party/`, with
  provenance (URL, ref, commit, SHA-256 per file), the nearest LICENSE/NOTICE copied, a reason and approval, and
  recorded modifications. OpenMetadata `ingestion/` and non-permissive licences need an approval reference.
- **Workspace** on developer hosts managed by `scripts/repo/workspace.py` from a manifest. Roles are product,
  readonly, upstream and reference. Push is disabled on everything except the product repo. Upstream study clones
  live in `~/workspaces/upstream/` (was `vendor/`), pinned and detached.
- **CI enforcement** in the product: `repo_hygiene.py`, `vendor_component.py verify`, a notices diff, the secret
  scan, the licence scan, and CODEOWNERS on `third_party/`, lockfiles and repo policy.

## Consequences
- The product repo stays small and reviewable, and every foreign file is traceable to an upstream commit and licence.
- Upgrades are explicit PRs (grouped package bumps, `diff-upstream` plus `update`). They cost a little effort and
  never surprise you.
- Someone must own the mirror job, the Dependabot/Renovate groups and the monthly upstream review.
- A patched fork, if it ever exists, adds a release process (an internal package). That cost is intentional, so it
  stays rare.

## Alternatives considered
- GitHub forks of the upstreams: public by design; unavailable across GHES and github.com.
- Submodules/subtrees of upstream monorepos: whole-repo scope, mixed licences, fragile CI, unreviewable diffs.
- Copying whole upstream folders by hand: no provenance, and licence obligations get lost.
- vendir: a good declarative tool. It stays an option (`infrastructure/repo/vendir.example.yml`), but the CI checks
  rely on `VENDORED.json`.

## Verification
`python3 scripts/repo/workspace.py verify --manifest ~/workspaces/workspace.json` exits 0;
`python3 scripts/repo/repo_hygiene.py` and `python3 scripts/repo/vendor_component.py verify` exit 0 in product CI;
the tests in `tests/repo/test_repo_tools.py` cover each rule.
