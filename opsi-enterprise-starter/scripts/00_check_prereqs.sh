#!/usr/bin/env bash
set -euo pipefail
for tool in git docker python3 aws; do
  if ! command -v "$tool" >/dev/null 2>&1; then echo "MISSING: $tool"; else "$tool" --version 2>&1 | head -n 1; fi
done
docker compose version || true
if command -v gh >/dev/null 2>&1; then gh --version | head -n 1; else echo 'OPTIONAL: gh CLI missing'; fi
echo '--- resources ---'; free -h; df -h .
echo '--- identity ---'; aws sts get-caller-identity || echo 'AWS identity not configured'
