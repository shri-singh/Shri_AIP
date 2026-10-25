#!/usr/bin/env bash
# Phase 0 host inventory - READ-ONLY. Writes inventory/phase0-host-<ts>.md
# Usage: scripts/phase0/inventory_host.sh [--check-egress]
#   --check-egress  also tests HTTPS reachability (HEAD requests) to package registries and vendor APIs
# Uses sudo only for `ss -p` / `nginx -T`, and only if passwordless sudo is already configured (sudo -n).
set -uo pipefail
OUT_DIR="${OUT_DIR:-inventory}"; mkdir -p "$OUT_DIR"
OUT="$OUT_DIR/phase0-host-$(date -u +%Y%m%dT%H%M%SZ).md"
CHECK_EGRESS=0; [[ "${1:-}" == "--check-egress" ]] && CHECK_EGRESS=1
section() { printf '\n## %s\n\n```\n' "$1" >> "$OUT"; }
endsec() { printf '```\n' >> "$OUT"; }
run() { echo "\$ $*" >> "$OUT"; timeout 20 "$@" >> "$OUT" 2>&1 || echo "(exit $?)" >> "$OUT"; }

echo "# Phase 0 host inventory - $(hostname) - $(date -u +%FT%TZ)" > "$OUT"
section "OS / kernel / hardware"; run cat /etc/os-release; run uname -a; run nproc; run free -h; run df -hT -x tmpfs -x devtmpfs; run lsblk; endsec
section "Identity"; run id; run aws sts get-caller-identity; endsec
section "EC2 metadata (IMDSv2)"
TOKEN=$(curl -s -m 2 -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60" || true)
if [[ -n "$TOKEN" ]]; then
  for p in instance-type placement/region placement/availability-zone iam/info; do
    echo "$p: $(curl -s -m 2 -H "X-aws-ec2-metadata-token: $TOKEN" "http://169.254.169.254/latest/meta-data/$p")" >> "$OUT"
  done
else echo "IMDSv2 not reachable (not EC2, or hop limit/IMDS disabled)" >> "$OUT"; fi
endsec
section "Runtimes"; for c in python3 python3.11 python3.12 node npm git docker gh aws psql nginx java; do printf '%-10s ' "$c" >> "$OUT"; (command -v "$c" >/dev/null && "$c" --version 2>&1 | head -1 || echo "missing") >> "$OUT"; done; run docker compose version; endsec
section "Available Python packages (dnf)"; run bash -c "dnf list available 'python3.1*' 2>/dev/null | head -20"; endsec
section "Docker"; run docker info --format '{{.ServerVersion}} storage={{.Driver}} cgroup={{.CgroupDriver}} rootless={{.SecurityOptions}}'; run docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'; endsec
section "Listening sockets"; if sudo -n true 2>/dev/null; then run sudo -n ss -lntp; else run ss -lnt; fi; endsec
section "Services / timers / cron"; run bash -c "systemctl list-units --type=service --state=running --no-pager | grep -Ei 'opsi|nginx|docker|postgres|redis|node|uvicorn|gunicorn' "; run systemctl list-timers --no-pager; run crontab -l; endsec
section "NGINX (config test + server names; no secrets expected)"; if sudo -n true 2>/dev/null; then run bash -c "sudo -n nginx -T 2>/dev/null | grep -E '^\s*(server_name|listen|location|proxy_pass|include)\b' | head -200"; else echo "skipped (needs sudo)" >> "$OUT"; fi; endsec
section "Security posture"; run bash -c "getenforce 2>/dev/null || echo selinux:n/a"; run bash -c "chronyc tracking 2>/dev/null | head -5 || timedatectl"; run bash -c "env | grep -iE '^(https?|no)_proxy=' | sed -E 's#(://)[^@/]+@#\\1***@#' || true"; endsec
if [[ $CHECK_EGRESS == 1 ]]; then
  section "Egress (HTTP status of HEAD request; 000 = blocked/unresolvable)"
  for url in https://pypi.org/simple/ https://registry.npmjs.org/ https://github.com https://docker.getcollate.io/v2/ \
             https://registry-1.docker.io/v2/ https://sso.dynatrace.com https://api.portkey.ai https://cdn.jsdelivr.net; do
    printf '%-40s %s\n' "$url" "$(curl -s -o /dev/null -m 8 -I -w '%{http_code}' "$url")" >> "$OUT"
  done
  endsec
fi
echo "wrote $OUT"
