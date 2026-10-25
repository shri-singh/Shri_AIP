#!/usr/bin/env bash
# Produce dependency license reports into reports/licenses-<ts>/ for docs/license-inventory.md.
# Uses tools if present, prints install hints otherwise (installs nothing by itself).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/reports/licenses-$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p "$OUT"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
if "$PY" -m piplicenses --version >/dev/null 2>&1; then
  "$PY" -m piplicenses --format=csv --with-urls --with-license-file --no-license-path > "$OUT/python.csv"
  "$PY" -m piplicenses --summary > "$OUT/python-summary.txt"
  echo "python: $OUT/python.csv"
  grep -iE 'GPL|LGPL|AGPL|SSPL|MPL|EPL|Commons Clause|Collate|BUSL|Elastic License|UNKNOWN' "$OUT/python.csv" > "$OUT/python-REVIEW.csv" || true
else
  echo "python: install pip-licenses into the venv for reports:  $PY -m pip install pip-licenses"
fi
for app in apps/copilot-runtime apps/opsi-web; do
  if [[ -d "$ROOT/$app/node_modules" ]]; then
    (cd "$ROOT/$app" && npx --yes license-checker-rseidelsohn@4 --production --csv --out "$OUT/$(basename $app).csv" >/dev/null 2>&1 \
      && npx --yes license-checker-rseidelsohn@4 --production --summary > "$OUT/$(basename $app)-summary.txt" 2>/dev/null) \
      && echo "node: $OUT/$(basename $app).csv" || echo "node: license-checker failed for $app (offline? use your internal npm mirror)"
    grep -iE 'GPL|AGPL|SSPL|MPL|EPL|BUSL|UNKNOWN|UNLICENSED' "$OUT/$(basename $app).csv" > "$OUT/$(basename $app)-REVIEW.csv" 2>/dev/null || true
  else
    echo "node: $app not installed (npm ci first)"
  fi
done
echo "Review every *-REVIEW.csv line with legal; record decisions in docs/license-inventory.md"
