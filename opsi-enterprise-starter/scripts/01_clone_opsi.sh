#!/usr/bin/env bash
# Clone current committed Opsi twice (baseline and revamp), optionally create NEW private remote.
set -euo pipefail
: "${OPSI_SOURCE_URL:?Set OPSI_SOURCE_URL to a corporate-approved Git URL}"
ROOT="${OPSI_WORKSPACES:-$PWD/workspaces}"
mkdir -p "$ROOT"
BASE="$ROOT/opsi-baseline-snapshot"
NEW="$ROOT/opsi-enterprise-revamp"
for p in "$BASE" "$NEW"; do
  if [[ -e "$p" ]]; then echo "Refusing to overwrite $p" >&2; exit 1; fi
done
# Use enterprise credential helper / GH CLI authenticated git, NOT token in remote URL.
git clone "$OPSI_SOURCE_URL" "$BASE"
git clone "$OPSI_SOURCE_URL" "$NEW"
chmod -R u+w "$NEW"
# Snapshot is a separate local clone, NOT a new branch; protect it from accidental commits.
git -C "$BASE" config core.hooksPath /dev/null
printf 'Baseline: %s\nRevamp: %s\n' "$BASE" "$NEW"
if [[ -n "${OPSI_GH_DEST:-}" ]]; then
  command -v gh >/dev/null || { echo 'gh required for new remote'; exit 1; }
  if [[ -z "${GH_TOKEN:-}" && -z "${GH_ENTERPRISE_TOKEN:-}" ]]; then echo "Set appropriate GH_TOKEN or GH_ENTERPRISE_TOKEN" >&2; exit 1; fi
  cd "$NEW"
  git remote rename origin legacy-opsi
  # gh repo create creates a DIFFERENT remote repository; does not overwrite old.
  gh repo create "$OPSI_GH_DEST" --private --source=. --remote=origin --push
  echo "New private remote: $OPSI_GH_DEST"
else
  echo 'No OPSI_GH_DEST configured: revamp is a local clone with same origin. Do NOT push until you set a new remote.'
fi
