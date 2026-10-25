#!/usr/bin/env bash
# Read-only study clones of upstream sources at PINNED refs, outside the revamp repo's tracked tree.
# Same layout and push policy as scripts/repo/workspace.py (docs/repository-strategy.md section 8):
# partial clone, detached at the pinned tag, push URL disabled.
# Writes <dest>/PROVENANCE.md (URL, ref, commit SHA, license file, date) for the license inventory.
#   OM_REF=2.0.6-release COPILOT_REF=v1.79.1 scripts/fetch_upstreams.sh [dest_dir]     # default ~/workspaces/upstream
#   OM_URL / COPILOT_URL override the sources (use the corporate upstream-mirrors URLs when they exist)
set -euo pipefail
DEST="${1:-${OPSI_WORKSPACES:-$HOME/workspaces}/upstream}"
OM_REF="${OM_REF:-2.0.6-release}"
COPILOT_REF="${COPILOT_REF:-v1.79.1}"
OM_URL="${OM_URL:-https://github.com/open-metadata/OpenMetadata.git}"
COPILOT_URL="${COPILOT_URL:-https://github.com/CopilotKit/CopilotKit.git}"
for u in "$OM_URL" "$COPILOT_URL"; do
  [[ "$u" =~ ://[^/@]+@ ]] && { echo "refusing: credentials embedded in URL" >&2; exit 2; }
done
mkdir -p "$DEST"
clone() { # url dir ref
  if [[ ! -d "$2/.git" ]]; then git clone --filter=blob:none --no-checkout "$1" "$2"; fi
  git -C "$2" fetch --tags --quiet origin
  git -C "$2" -c advice.detachedHead=false checkout --quiet --detach "$3"
  git -C "$2" remote set-url --push origin "DISABLED-read-only-remote"
  git -C "$2" config --local workspace.role upstream
}
clone "$OM_URL" "$DEST/OpenMetadata" "$OM_REF"
clone "$COPILOT_URL" "$DEST/CopilotKit" "$COPILOT_REF"
{
  echo "# Upstream provenance (generated $(date -u +%FT%TZ))"
  for repo in OpenMetadata CopilotKit; do
    d="$DEST/$repo"
    echo; echo "## $repo"
    echo "- url: $(git -C "$d" remote get-url origin)"
    echo "- ref: $(git -C "$d" describe --tags --always 2>/dev/null)"
    echo "- commit: $(git -C "$d" rev-parse HEAD)"
    echo "- license file: $(head -n 1 "$d/LICENSE" 2>/dev/null || echo 'MISSING')"
  done
  echo; echo "Note: OpenMetadata's ingestion/ directory carries its own LICENSE (Collate Community License) - see docs/license-inventory.md."
} > "$DEST/PROVENANCE.md"
cat "$DEST/PROVENANCE.md"
echo "Study only. Bring files into the product only with scripts/repo/vendor_component.py (records provenance + licence)."
