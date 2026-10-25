#!/usr/bin/env bash
# Two separate clones (NOT a branch): a read-only baseline snapshot and the revamp working copy.
# Safer replacement for the starter's scripts/01_clone_opsi.sh:
#   - push is DISABLED on the baseline and on the legacy remote of the revamp clone
#   - the new private remote is only added when OPSI_NEW_REMOTE_URL is given
#   - nothing is ever pushed by this script (it prints the command for you to run after approval)
#   - no tokens in URLs: authenticate with `gh auth login` / credential helper first
#
#   export OPSI_SOURCE_URL='https://git.corp.example/ORG/opsi.git'
#   export OPSI_NEW_REMOTE_URL='https://git.corp.example/ORG/opsi-enterprise-revamp.git'   # optional, must already exist
#   scripts/clone_repos.sh [workspace_dir]
set -euo pipefail
: "${OPSI_SOURCE_URL:?set OPSI_SOURCE_URL (corporate-approved Git URL, no credentials inside)}"
[[ "$OPSI_SOURCE_URL" =~ ://[^/]*@ ]] && { echo "refusing: credentials embedded in OPSI_SOURCE_URL" >&2; exit 2; }
ROOT="${1:-${OPSI_WORKSPACES:-$HOME/workspaces}}"
BASE="$ROOT/opsi-baseline-snapshot"
NEW="$ROOT/opsi-enterprise-revamp"
mkdir -p "$ROOT"
for p in "$BASE" "$NEW"; do [[ -e "$p" ]] && { echo "refusing to overwrite existing $p" >&2; exit 1; }; done

git clone "$OPSI_SOURCE_URL" "$BASE"
git -C "$BASE" remote set-url --push origin "DISABLED-baseline-is-read-only"
git -C "$BASE" config --local opsi.role baseline-snapshot
echo "baseline at $(git -C "$BASE" rev-parse HEAD) (push disabled)"

git clone "$OPSI_SOURCE_URL" "$NEW"
git -C "$NEW" remote rename origin legacy-opsi
git -C "$NEW" remote set-url --push legacy-opsi "DISABLED-legacy-is-read-only"
git -C "$NEW" config --local opsi.role revamp
if [[ -n "${OPSI_NEW_REMOTE_URL:-}" ]]; then
  [[ "$OPSI_NEW_REMOTE_URL" =~ ://[^/]*@ ]] && { echo "refusing: credentials embedded in OPSI_NEW_REMOTE_URL" >&2; exit 2; }
  [[ "$OPSI_NEW_REMOTE_URL" == "$OPSI_SOURCE_URL" ]] && { echo "refusing: new remote equals the legacy source" >&2; exit 2; }
  git -C "$NEW" remote add origin "$OPSI_NEW_REMOTE_URL"
  echo "revamp origin -> $OPSI_NEW_REMOTE_URL (NOT pushed)"
  echo "After approval, publish with:  git -C '$NEW' push -u origin $(git -C "$NEW" rev-parse --abbrev-ref HEAD)"
else
  echo "No OPSI_NEW_REMOTE_URL: revamp has no writable remote yet (create the private repo first)."
fi
git -C "$NEW" checkout -b revamp/phase-1
git -C "$NEW" remote -v
