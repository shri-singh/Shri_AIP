# Linux / EC2 (Amazon Linux 2023)

## Packages
```bash
cat /etc/os-release                         # confirm AL2023
sudo dnf check-update
dnf list available 'python3.1*' 'nodejs*' 'postgresql*' 2>/dev/null | sort -u
sudo dnf install -y python3.12 python3.12-pip git jq tmux postgresql16 nodejs22 nodejs22-npm   # names vary by release
sudo dnf install -y docker && sudo systemctl enable --now docker && sudo usermod -aG docker $USER   # re-login after
docker compose version      # if missing: install the compose plugin per corporate standard (>= 2.24)
sudo dnf updateinfo list security       # pending security updates
```
`alternatives --config python3` is not needed - call `python3.12` explicitly.

## Users, permissions, files
```bash
sudo useradd --system --shell /sbin/nologin opsi-ingest
sudo install -d -o opsi-ingest -g opsi-ingest -m 0750 /var/lib/opsi-ingest
sudo install -m 0600 -o opsi-ingest -g opsi-ingest /dev/null /etc/opsi/ingest.env
stat -c '%a %U:%G %n' /etc/opsi/*.env       # expect 600 owner service user
sudo -u opsi-ingest bash                     # act as the service user (nologin shell -> use bash explicitly)
namei -l /opt/opsi-revamp-kit/.venv/bin/python   # permission chain debugging
```

## Processes, ports, resources
```bash
ss -lntp                       # listening sockets (+process with sudo)
ss -tnp state established '( dport = :5432 )'   # DB connections
ps aux --sort=-%mem | head     # top memory
free -h; df -hT; du -sh /var/lib/docker
top -o %CPU; uptime
journalctl -k --since -1h | grep -i -E "oom|killed process"   # OOM kills
sudo sysctl vm.max_map_count; echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-opensearch.conf && sudo sysctl --system
timedatectl; chronyc tracking  # time sync (JWT, S3 signatures)
```

## Networking checks
```bash
curl -sS -o /dev/null -w '%{http_code}\n' -m 8 https://pypi.org/simple/
getent hosts sso.dynatrace.com
openssl s_client -connect <host>:443 -servername <host> </dev/null 2>/dev/null | openssl x509 -noout -subject -issuer -dates
env | grep -i _proxy           # corporate proxy settings (no_proxy must include 127.0.0.1,localhost,169.254.169.254)
```

## SSM (no SSH keys needed)
```bash
aws ssm start-session --target i-0123456789abcdef0
aws ssm start-session --target i-0123... --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8585"],"localPortNumber":["8585"]}'      # OpenMetadata UI on your laptop
```

## Editing safely
```bash
cp file file.bak.$(date +%F)       # before editing configs
vi /etc/opsi/ingest.env            # :set paste  (paste without autoindent), :wq
nano -B file                       # -B keeps a backup
diff -u file.bak.* file
sed -n '1,80p' file; grep -n PATTERN file
```

## Archives and transfers
```bash
tar -czf opsi-revamp-kit.tgz --exclude=node_modules --exclude=.venv opsi-revamp-kit/
sha256sum opsi-revamp-kit.tgz     # verify after copying
python3 scripts/secret_scan.py some/dir   # before sharing any bundle
```
