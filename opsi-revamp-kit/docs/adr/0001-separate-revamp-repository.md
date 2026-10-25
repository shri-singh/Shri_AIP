# ADR-0001: Separate revamp repository with a read-only baseline clone
- Status: Accepted (upstream study-clone location and vendoring refined by [ADR-0020](0020-mirrors-packages-selective-vendoring.md))
- Date: 2026-10-24

## Context
The master prompt forbids overwriting the current Opsi source and asks for a distinct private
`opsi-enterprise-revamp` remote - explicitly not a feature branch. Production Opsi keeps shipping from
the legacy repository while the revamp evolves. Engineers need an untouched reference of today's code
to diff against and to roll back to.

## Decision
- Two local clones of the same commit: `opsi-baseline-snapshot` (read-only) and `opsi-enterprise-revamp`.
- In the baseline, the push URL is set to an invalid value (`git remote set-url --push origin DISABLED...`).
- In the revamp, the original remote is renamed `legacy-opsi` and its push URL disabled; a **new private
  remote** becomes `origin` only after it has been created by the repository owners.
- No script pushes. Publishing is a deliberate, approved human step.
- Upstream sources (OpenMetadata, CopilotKit) live in `vendor/` outside tracked code, pinned by tag/SHA, with
  `vendor/PROVENANCE.md`.

Implemented by `scripts/clone_repos.sh` and `scripts/fetch_upstreams.sh`.

## Consequences
- Fixes to legacy Opsi must be cherry-picked or re-applied in the revamp (record them in the commit plan).
- The revamp can be deleted and recreated without affecting production.
- Need periodic `git fetch legacy-opsi` + merge review to avoid drift.

## Alternatives considered
- Feature branch in the legacy repo - rejected by the master prompt; mixes risk with production history.
- Fork on github.com - not possible across GitHub.com and GitHub Enterprise Server; may violate data policy.
- Copying vendor monorepos into the revamp - licence/provenance noise and huge diffs.

## Verification
`git -C opsi-baseline-snapshot remote -v` shows a `DISABLED...` push URL; `git -C opsi-enterprise-revamp remote -v`
shows `legacy-opsi` with a disabled push URL and `origin` pointing to the new private repository.
