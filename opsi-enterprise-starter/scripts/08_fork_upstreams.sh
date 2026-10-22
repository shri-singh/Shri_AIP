#!/usr/bin/env bash
# Optional public GitHub forks in an approved GitHub organization.
set -euo pipefail
: "${GITHUB_FORK_ORG:?Set GitHub.com organization authorized to own public forks}"
: "${GH_TOKEN:?Set GH_TOKEN for GitHub.com, using secure interactive read}"
command -v gh >/dev/null || { echo 'gh CLI required' >&2; exit 1; }
# gh repo fork only works in the same GitHub host. A GitHub Enterprise Server
# organization cannot directly fork a github.com repository across instances.
gh repo fork open-metadata/OpenMetadata --org "$GITHUB_FORK_ORG" --clone=false
gh repo fork CopilotKit/CopilotKit --org "$GITHUB_FORK_ORG" --clone=false
echo 'Forks created on GitHub.com (subject to organization policy). Use read-only clones/submodules to inspect upstream source.'
