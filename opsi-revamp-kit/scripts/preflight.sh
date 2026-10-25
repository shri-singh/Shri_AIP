#!/usr/bin/env bash
# Read-only readiness check for the EC2 host. Exit 0 = all required checks passed.
set -uo pipefail
FAIL=0; WARN=0
ok() { printf '  OK    %s\n' "$*"; }
bad() { printf '  FAIL  %s\n' "$*"; FAIL=$((FAIL+1)); }
warn() { printf '  WARN  %s\n' "$*"; WARN=$((WARN+1)); }
vge() { [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" == "$2" ]]; }  # $1 >= $2

echo "== tools"
PY="$(command -v python3.12 || command -v python3.11 || command -v python3)"
pyv="$($PY -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo 0)"
vge "$pyv" 3.11 && ok "python $pyv ($PY)" || bad "python >= 3.11 required (found $pyv). AL2023: sudo dnf install python3.12"
if command -v node >/dev/null; then nv="$(node -v | tr -d v)"; vge "$nv" 20.18 && ok "node $nv" || bad "node >= 20.18 required (found $nv)"; else warn "node missing (needed for copilot-runtime and migration validator)"; fi
command -v git >/dev/null && ok "git $(git --version | awk '{print $3}')" || bad "git missing"
if command -v docker >/dev/null; then
  cv="$(docker compose version --short 2>/dev/null || echo 0)"
  vge "${cv#v}" 2.24 && ok "docker compose $cv (supports !reset/!override)" || bad "docker compose >= 2.24 required for the lab override (found $cv)"
else warn "docker missing (only needed for compose stacks)"; fi
command -v psql >/dev/null && ok "psql $(psql --version | awk '{print $3}')" || warn "psql missing (migrations/backup drills)"
command -v aws >/dev/null && ok "aws cli $(aws --version 2>&1 | awk '{print $1}')" || warn "aws cli missing"

echo "== identity / time"
if aws sts get-caller-identity --query Arn --output text >/dev/null 2>&1; then ok "AWS identity $(aws sts get-caller-identity --query Arn --output text)"; else warn "no AWS identity (instance profile not attached?)"; fi
if command -v chronyc >/dev/null && chronyc tracking 2>/dev/null | grep -q "Leap status     : Normal"; then ok "time synchronised (chrony)"; else warn "cannot confirm time sync - JWT validation and S3 signatures need accurate clocks"; fi

echo "== resources"
free_gb=$(df -Pk . | awk 'NR==2{print int($4/1024/1024)}'); [[ $free_gb -ge 20 ]] && ok "disk free ${free_gb}G" || warn "disk free ${free_gb}G (< 20G)"
mem_gb=$(awk '/MemTotal/{print int($2/1024/1024)}' /proc/meminfo 2>/dev/null || echo 0); [[ $mem_gb -ge 8 ]] && ok "memory ${mem_gb}G" || warn "memory ${mem_gb}G (< 8G; OpenMetadata lab needs ~12-16G)"
if [[ -r /proc/sys/vm/max_map_count ]]; then mmc=$(cat /proc/sys/vm/max_map_count); [[ $mmc -ge 262144 ]] && ok "vm.max_map_count=$mmc" || warn "vm.max_map_count=$mmc (< 262144 needed by OpenSearch/Elasticsearch containers)"; fi

echo "== secrets hygiene"
for f in .env /etc/opsi/*.env; do
  [[ -f "$f" ]] || continue
  perm=$(stat -c '%a' "$f"); [[ "$perm" =~ ^[0-7]00$ ]] && ok "$f mode $perm" || bad "$f mode $perm (run: chmod 600 $f)"
  grep -qE '^(PORTKEY_API_KEY|DYNATRACE_API_TOKEN|ELASTIC_API_KEY)=.+' "$f" && warn "$f holds secrets in plain text - prefer Secrets Manager rendering"
done
git ls-files --error-unmatch .env >/dev/null 2>&1 && bad ".env is tracked by git!" || ok ".env not tracked"

echo; echo "preflight: $FAIL failure(s), $WARN warning(s)"
exit $(( FAIL > 0 ))
