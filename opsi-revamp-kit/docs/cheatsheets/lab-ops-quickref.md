# Lab ops quick reference: Docker, OpenMetadata lab, ports, Git

Bash on Amazon Linux 2023 (most lines work on any Linux). Placeholders: `<c>` = container name or ID,
`<svc>` = Compose service, `KIT` = where this kit is checked out (systemd units assume `/opt/opsi-revamp-kit`).
Related sheets: [docker-compose.md](docker-compose.md), [linux-ec2.md](linux-ec2.md),
[openmetadata-api.md](openmetadata-api.md), [git-and-gh.md](git-and-gh.md).

1. [Docker: live streams and checks](#1-docker-live-streams-and-checks)
2. [Resource configuration](#2-resource-configuration)
3. [OpenMetadata 2.0.6 lab: PostgreSQL + OpenSearch](#3-openmetadata-206-lab-postgresql--opensearch)
4. [Change ports without a new FER per test](#4-change-ports-without-a-new-fer-per-test)
5. [Git: copy, back up, fork](#5-git-copy-back-up-fork)

```bash
KIT=${KIT:-/opt/opsi-revamp-kit}
```

---

## 1. Docker: live streams and checks

### Logs
```bash
docker logs -f --timestamps --tail 100 <c>                 # follow from the last 100 lines
docker logs --since 15m <c>                                # a window: --since/--until take 10m, 1h or 2026-10-25T10:00:00
docker logs -f <c> 2>&1 | grep --line-buffered -iE 'error|exception|warn'   # live filter (many apps log to stderr)
docker compose -p <project> logs -f --tail 50 <svc1> <svc2>                 # several services, prefixed by name
docker compose -p <project> logs -f --no-log-prefix <svc>
sudo tail -F "$(docker inspect -f '{{.LogPath}}' <c>)"     # the raw json-file log on disk
```

### Events: a live stream of what the daemon does
```bash
docker events --filter type=container --format '{{.Time}} {{.Actor.Attributes.name}} {{.Action}}'
docker events --filter event=die --filter event=oom --filter event=health_status   # same key = OR
docker events --since 30m --until 1s --filter container=<c>                         # replay history, then exit
```

### Health, restarts, resources
```bash
docker stats                                               # live; Ctrl-C to stop
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}\t{{.PIDs}}'
watch -n 5 "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"   # Status shows (healthy)/(unhealthy)
docker inspect -f '{{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{end}} restarts={{.RestartCount}} oom={{.State.OOMKilled}} exit={{.State.ExitCode}}' <c>
docker inspect -f '{{range .State.Health.Log}}{{.End}} rc={{.ExitCode}} {{.Output}}{{end}}' <c>   # last healthcheck outputs
docker ps -a --filter status=exited --filter status=restarting
docker top <c>                                             # processes inside, seen from the host
```

### Inside a container, and between containers
```bash
docker exec -it <c> sh                                     # bash if the image has it
docker exec <c> env | sort | grep -v -iE 'pass|secret|token|key'   # check config without printing secrets
docker exec <c> cat /sys/fs/cgroup/memory.max              # memory limit actually applied (cgroup v2)
docker cp <c>:/path/in/container ./local-copy
docker exec <c> sh -c 'curl -sS -m 5 http://<other-svc>:<port>/'  # container-to-container via Compose DNS
docker network inspect <project>_<network> -f '{{range .Containers}}{{.Name}} {{.IPv4Address}}{{"\n"}}{{end}}'
```
HTTP streams (SSE) through a port: `curl -N` disables buffering - see [copilotkit-v2-ag-ui.md](copilotkit-v2-ag-ui.md)
and the proxy buffering settings in [nginx.md](nginx.md).

### The daemon itself
```bash
sudo systemctl status docker --no-pager
journalctl -u docker -f                                    # pull failures, iptables, storage errors
docker info -f 'cgroup=v{{.CgroupVersion}} storage={{.Driver}} root={{.DockerRootDir}} logging={{.LoggingDriver}}'
```

---

## 2. Resource configuration

### Host (once; OpenSearch needs the sysctl)
```bash
nproc; free -h; df -h / /var/lib/docker
sysctl vm.max_map_count                                    # OpenSearch/Elasticsearch need >= 262144
echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-opensearch.conf && sudo sysctl --system
grep -i 'open files' /proc/$(pgrep -xo dockerd)/limits     # file limit containers inherit by default
```

### One container (`docker run`)
```bash
# --memory-swap equal to --memory means "no swap"; always bind published ports to 127.0.0.1
docker run -d --name <c> \
  --memory 2g --memory-swap 2g --cpus 1.5 --pids-limit 512 \
  --ulimit nofile=65536:65536 \
  --log-opt max-size=20m --log-opt max-file=5 \
  --restart unless-stopped \
  -p 127.0.0.1:18080:8080 <image>
```

### Compose
```yaml
services:
  app:
    mem_limit: 2g
    memswap_limit: 2g
    cpus: 1.5
    pids_limit: 512
    ulimits:
      nofile: {soft: 65536, hard: 65536}
      memlock: {soft: -1, hard: -1}        # OpenSearch / Elasticsearch
    shm_size: 256m                         # PostgreSQL parallel queries, headless browsers
    logging:
      driver: json-file
      options: {max-size: "20m", max-file: "5"}
    # Equivalent spelling, also honoured by Compose v2 - use one style, not both:
    # deploy: {resources: {limits: {cpus: "1.5", memory: 2g}, reservations: {memory: 1g}}}
```

### Change limits on a running container
```bash
docker update --memory 3g --memory-swap 3g --cpus 2 <c>    # immediate, no restart
docker inspect -f 'mem={{.HostConfig.Memory}} swap={{.HostConfig.MemorySwap}} nanocpus={{.HostConfig.NanoCpus}}' <c>
```
`docker update` is lost when Compose recreates the container. Put anything that should stick in the compose file or `.env`.

### JVM heap vs container limit
A JVM sizes its heap from its own variable, not from the container limit. Keep the heap at about 50-60 % of `mem_limit`;
the rest goes to metaspace, threads, direct buffers and (for OpenSearch) the page cache.

| Container | Heap variable | Lab default (section 3) |
|---|---|---|
| OpenSearch | `OPENSEARCH_JAVA_OPTS=-Xms1g -Xmx1g` | `mem_limit` 2g |
| OpenMetadata server | `OPENMETADATA_HEAP_OPTS=-Xmx2g -Xms2g` (upstream default 1G) | `mem_limit` 4g |
| OpenMetadata ingestion (Airflow, Python) | none: size `mem_limit` to the biggest pipeline | `mem_limit` 3g |
| PostgreSQL | `shared_buffers` (`command: postgres -c shared_buffers=512MB`) | `mem_limit` 2g |

`oom=true` in `docker inspect` or an `oom` event means you need a bigger `mem_limit` or a smaller heap.

### Docker daemon defaults (`/etc/docker/daemon.json`)
```json
{
  "log-driver": "json-file",
  "log-opts": {"max-size": "50m", "max-file": "5"},
  "default-ulimits": {"nofile": {"Name": "nofile", "Soft": 65536, "Hard": 65536}},
  "live-restore": true
}
```
```bash
sudo cp -a /etc/docker/daemon.json /etc/docker/daemon.json.bak.$(date +%F) 2>/dev/null || true
sudo vi /etc/docker/daemon.json && python3 -m json.tool /etc/docker/daemon.json >/dev/null && echo valid
sudo systemctl reload docker     # enough for live-restore
sudo systemctl restart docker    # needed for log/ulimit defaults; with live-restore active, containers keep running
```
New log options only apply to containers created afterwards. On a shared host this changes everyone's containers,
so agree on it first.

### Disk cleanup
```bash
docker system df -v | head -40
docker image prune -f; docker builder prune -f             # dangling images, build cache
docker container prune -f                                  # stopped containers
docker volume ls -f dangling=true                          # LOOK first: `docker volume prune` deletes data
```

---

## 3. OpenMetadata 2.0.6 lab: PostgreSQL + OpenSearch

This lab uses the **release images**, so nothing is built from source and the first start takes about 5-10 minutes,
mostly image pulls. Upstream ships two PostgreSQL flavours:

- the release asset `docker-compose-postgres.yml`, which uses release images with **Elasticsearch 9.3.0**;
- the dev file `docker/development/docker-compose-postgres.yml`, which uses **OpenSearch 3.4.0** but builds from source.
  That one is the kit's `openmetadata-lab` stack.

The override below gives you release images with OpenSearch. On 2026-10-25 we checked the 2.0.6 release asset list and
the file contents, rendered the merge with `docker compose config` (Compose v5.3.1) and confirmed that
`check_port_exposure.py` passes.

> **Lab only.** OpenSearch security is off inside the Docker network. The JWT signing keys are the public ones that
> ship in the image, so anyone can mint tokens for this server. Keep it on 127.0.0.1 and use synthetic or approved
> data only. For shared environments use `infrastructure/compose/openmetadata.prod-reviewed.example.yml`.
> The upstream file pins `container_name`s (`openmetadata_server`, `openmetadata_postgresql`, ...), so you can run
> **only one OpenMetadata stack per Docker host**. Stop the kit's `opsi-om-lab` before starting this one.

### 3.1 Prerequisites
```bash
docker compose version            # >= 2.24 (the override uses !reset / !override)
sysctl vm.max_map_count           # >= 262144 (section 2)
free -g; df -h /var/lib/docker    # ~11 GiB RAM for the limits below (16 GiB host), ~20 GiB free disk
```

### 3.2 Download the pinned release file
```bash
OM_VER=2.0.6
mkdir -p ~/om-lab && cd ~/om-lab
curl -fsSL -o docker-compose-postgres.yml \
  "https://github.com/open-metadata/OpenMetadata/releases/download/${OM_VER}-release/docker-compose-postgres.yml"
sha256sum docker-compose-postgres.yml | tee docker-compose-postgres.yml.sha256      # record what you ran
grep -n 'image:' docker-compose-postgres.yml   # openmetadata/{postgresql,server,ingestion}:2.0.6 + elasticsearch:9.3.0
```
Other assets in the same release: `docker-compose.yml` (MySQL + Elasticsearch), `docker-compose-openmetadata.yml`
(migrate + server only, you bring the database and search), `docker-compose-ingestion.yml` (Airflow only).
List them with `curl -s https://api.github.com/repos/open-metadata/OpenMetadata/releases/tags/${OM_VER}-release | jq -r '.assets[].name'`.
Behind a proxy, set `HTTPS_PROXY` for curl and pull images through the corporate registry mirror.

### 3.3 Secrets and ports: `.env`
```bash
cd ~/om-lab && umask 077
gen() { python3 -c 'import secrets;print(secrets.token_urlsafe(24))'; }
cat > .env <<EOF
# OpenMetadata ${OM_VER:-2.0.6} lab - generated $(date -u +%F). Mode 600, never commit, back it up with the data.
OM_PG_SUPERUSER_PASSWORD=$(gen)
DB_USER_PASSWORD=$(gen)
AIRFLOW_DB_PASSWORD=$(gen)
AIRFLOW_PASSWORD=$(gen)
FERNET_KEY=$(python3 -c 'import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')
SEARCH_TYPE=opensearch
OM_HEAP_OPTS="-Xmx2g -Xms2g"
# Host-side ports (all bound to 127.0.0.1). Change here, then run: omc up -d (section 4)
OM_HTTP_HOST_PORT=8585
OM_ADMIN_HOST_PORT=8586
AIRFLOW_HOST_PORT=8080
EOF
chmod 600 .env
```
- `DB_USER_PASSWORD`, `AIRFLOW_DB_PASSWORD`, `AIRFLOW_PASSWORD`, `FERNET_KEY` and `SEARCH_TYPE` are variables the
  upstream file already reads. The override wires up the others.
- `FERNET_KEY` encrypts the connection secrets that OpenMetadata stores. Set it once: if you change it later, saved
  service passwords can no longer be read.

### 3.4 Override: OpenSearch instead of Elasticsearch, loopback-only ports, limits
```bash
cat > ~/om-lab/opensearch-lab.override.yml <<'EOF'
# OpenMetadata 2.0.6 quickstart (release images) -> PostgreSQL + OpenSearch, loopback-only. LAB ONLY.
# Use with the upstream release file:  -f docker-compose-postgres.yml -f opensearch-lab.override.yml
# Needs Docker Compose >= 2.24 (!reset / !override). Values come from .env in this directory.
services:
  postgresql:
    environment:
      POSTGRES_PASSWORD: ${OM_PG_SUPERUSER_PASSWORD:?set in .env}   # only applied when the data dir is first created
    ports: !reset []      # psql: docker exec -it openmetadata_postgresql psql -U postgres
    # ports: !override ["127.0.0.1:15432:5432"]   # instead of the line above, to psql from the host
    mem_limit: ${OM_PG_MEM:-2g}

  # The service keeps the name "elasticsearch" on purpose: the upstream file's depends_on blocks and
  # ELASTICSEARCH_HOST all point at that name. Only the image and its settings change.
  elasticsearch:
    image: opensearchproject/opensearch:${OPENSEARCH_VERSION:-3.4.0}
    container_name: openmetadata_opensearch
    environment: !override
      - discovery.type=single-node
      - DISABLE_SECURITY_PLUGIN=true     # lab only: no TLS/auth inside the docker network, no demo certs
      - OPENSEARCH_JAVA_OPTS=${OM_OS_JAVA_OPTS:--Xms1g -Xmx1g}
      - indices.query.bool.max_clause_count=4096
    volumes: !override
      - os-data:/usr/share/opensearch/data
    ports: !reset []      # check it with: docker exec openmetadata_opensearch curl -s localhost:9200
    ulimits:
      memlock: {soft: -1, hard: -1}
      nofile: {soft: 65536, hard: 65536}
    mem_limit: ${OM_OS_MEM:-2g}

  execute-migrate-all:
    ports: !reset []

  openmetadata-server:
    environment:
      OPENMETADATA_HEAP_OPTS: ${OM_HEAP_OPTS:--Xmx2g -Xms2g}
    ports: !override
      - "127.0.0.1:${OM_HTTP_HOST_PORT:-8585}:8585"
      - "127.0.0.1:${OM_ADMIN_HOST_PORT:-8586}:8586"
    mem_limit: ${OM_SERVER_MEM:-4g}

  ingestion:
    environment:
      AIRFLOW_ADMIN_PASSWORD: ${AIRFLOW_PASSWORD:?set in .env}   # Airflow admin; the server logs in with AIRFLOW_PASSWORD
    ports: !override
      - "127.0.0.1:${AIRFLOW_HOST_PORT:-8080}:8080"
    mem_limit: ${OM_INGESTION_MEM:-3g}

volumes:
  os-data:
EOF
```
Without `!override`/`!reset`, Compose **appends** `ports:`, `volumes:` and list-style `environment:` to the upstream
values. You would then keep the `0.0.0.0` bindings, mount the Elasticsearch data path, and pass `xpack.*` settings that
make OpenSearch refuse to start.

### 3.5 A shortcut, then validate
```bash
omc() { docker compose -p om-lab --project-directory ~/om-lab --env-file ~/om-lab/.env \
          -f ~/om-lab/docker-compose-postgres.yml -f ~/om-lab/opensearch-lab.override.yml "$@"; }
# keep it: add the two lines above to ~/.bashrc

omc config --services        # postgresql elasticsearch execute-migrate-all openmetadata-server ingestion
omc config --format json | python3 "$KIT/scripts/check_port_exposure.py"   # must print "port exposure check passed"
omc config | grep -nE 'image:|host_ip|published'
```
You can ignore the warning ``the attribute `version` is obsolete``: it comes from the upstream file.

### 3.6 First start (the order matters)
The `openmetadata/postgresql` image creates `openmetadata_user` and `airflow_user` on first init, with the fixed
passwords `openmetadata_password` and `airflow_pass` (upstream `docker/postgresql/postgres-script.sql`). Change those
passwords to your `.env` values **before** anything connects, or the migration fails to authenticate.
```bash
omc pull
omc up -d postgresql
until [ "$(docker inspect -f '{{.State.Health.Status}}' openmetadata_postgresql)" = healthy ]; do sleep 5; done
( set -a; . ~/om-lab/.env; set +a
  docker exec -i -e DB_USER_PASSWORD -e AIRFLOW_DB_PASSWORD openmetadata_postgresql \
    psql -U postgres -v ON_ERROR_STOP=1 <<'SQL'
\getenv om_pw DB_USER_PASSWORD
\getenv af_pw AIRFLOW_DB_PASSWORD
ALTER ROLE openmetadata_user PASSWORD :'om_pw';
ALTER ROLE airflow_user PASSWORD :'af_pw';
SQL
)                                       # subshell: the secrets do not stay in your shell
omc up -d                               # opensearch -> migrate (runs once, exits 0) -> server -> ingestion
omc ps -a                               # execute_migrate_all should show "Exited (0)"
omc logs -f --tail 50 execute-migrate-all openmetadata-server
```
If you already ran `omc up -d` before changing the passwords, the migration fails. Run the `ALTER ROLE` block, then
`omc up -d` again.

### 3.7 Verify
```bash
curl -fsS http://127.0.0.1:8586/healthcheck; echo                       # admin port
curl -fsS http://127.0.0.1:8585/api/v1/system/version; echo
docker exec openmetadata_opensearch curl -s localhost:9200 | grep -E '"distribution"|"number"'   # opensearch 3.4.0
docker exec openmetadata_opensearch curl -s 'localhost:9200/_cluster/health?pretty'
docker exec openmetadata_opensearch curl -s 'localhost:9200/_cat/indices?v&s=index' | head -30
```
To open the UI, tunnel port 8585 to your laptop (section 4.2) and browse to http://localhost:8585. The default 2.0.x
basic-auth login is `admin@open-metadata.org` / `admin`: change it right away.

To get an API token, go to Settings -> Bots -> `ingestion-bot` and copy its token:
```bash
read -rs -p 'OpenMetadata bot token: ' OM_TOKEN; echo; export OM_TOKEN
OM=http://127.0.0.1:8585; H="Authorization: Bearer $OM_TOKEN"
curl -fsS -H "$H" "$OM/api/v1/system/status" | jq     # checks database, search, migrations, pipeline client, JWKS
```

### 3.8 Check the ingestors
There are two layers: **(a)** the OpenMetadata server's link to Airflow (the "pipeline service client"), and
**(b)** each ingestion pipeline, which runs as an Airflow DAG, and its runs.

```bash
# (a) Is Airflow up, and can OpenMetadata reach it?
docker inspect -f '{{.State.Status}} restarts={{.RestartCount}} oom={{.State.OOMKilled}}' openmetadata_ingestion
curl -fsS http://127.0.0.1:8080/api/v2/monitor/health | jq      # Airflow 3: metadatabase, scheduler, dag_processor
curl -fsS -H "$H" "$OM/api/v1/services/ingestionPipelines/status" | jq   # OpenMetadata's view: code 200 + Airflow version
omc logs -f --tail 100 ingestion                                 # scheduler (foreground process)
docker exec openmetadata_ingestion tail -n 50 /opt/airflow/logs/api-server.log /opt/airflow/logs/dag-processor.log
```

```bash
# (b) The pipelines OpenMetadata knows about, with the state of their latest run
curl -fsS -H "$H" "$OM/api/v1/services/ingestionPipelines?fields=pipelineStatuses&limit=50" \
  | jq -r '.data[] | [.fullyQualifiedName, .pipelineType, (.enabled|tostring),
      ((.pipelineStatuses // []) | if length == 0 then "never-run" else (max_by(.startDate // 0) | .pipelineState) end)] | @tsv' \
  | column -t
# states: queued, running, success, partialSuccess, failed, stopped

FQN=$(python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1], safe=""))' '<service>.<pipeline-name>')
ID=$(curl -fsS -H "$H" "$OM/api/v1/services/ingestionPipelines/name/$FQN" | jq -r .id)

# Run history for the last 7 days (timestamps are epoch milliseconds)
now=$(date +%s000); since=$(( now - 7*24*3600*1000 ))
curl -fsS -H "$H" "$OM/api/v1/services/ingestionPipelines/$FQN/pipelineStatus?startTs=$since&endTs=$now" \
  | jq -r '.data[] | [((.startDate // 0)/1000 | floor | todate), .pipelineState, .runId] | @tsv'

# Logs of the last run, trigger, (re)deploy to Airflow, pause/resume, kill
curl -fsS -H "$H" "$OM/api/v1/services/ingestionPipelines/logs/$ID/last" | jq -r 'to_entries[] | "== \(.key)\n\(.value)"' | tail -80
curl -fsS -X POST -H "$H" "$OM/api/v1/services/ingestionPipelines/trigger/$ID" | jq
curl -fsS -X POST -H "$H" "$OM/api/v1/services/ingestionPipelines/deploy/$ID" | jq
curl -fsS -X POST -H "$H" "$OM/api/v1/services/ingestionPipelines/toggleIngestion/$ID" | jq '{name, enabled}'
curl -fsS -X POST -H "$H" "$OM/api/v1/services/ingestionPipelines/kill/$ID" | jq
```

```bash
# The same from the Airflow side (Airflow 3.3 CLI in the ingestion container; DAG id = pipeline name)
af() { docker exec openmetadata_ingestion airflow "$@"; }
af dags list -o table                      # includes the "paused" column
af dags list-import-errors                 # broken or badly generated DAG files
af dags list-runs <dag_id> -o table        # Airflow 3: dag_id is positional (no -d)
af tasks states-for-dag-run <dag_id> <run_id>
af dags unpause <dag_id>; af dags trigger <dag_id>
docker exec openmetadata_ingestion sh -c 'find /opt/airflow/logs -name "attempt=*.log" -mmin -30'   # recent task logs
```
For the Airflow UI, tunnel port 8080 and log in as `admin` with `AIRFLOW_PASSWORD` from `.env`. The example DAGs
that ship in the image (sample data) can stay paused.

You can also ingest without Airflow, which is the kit's production approach: `metadata ingest -c <workflow>.yaml`
exits non-zero on failure. See [../../infrastructure/openmetadata/README.md](../../infrastructure/openmetadata/README.md).
Inside this lab the server URL for workflow configs is `http://openmetadata-server:8585/api`. The
`openmetadata-ingestion` package is under the Collate Community License (ADR-0018).

### 3.9 Day 2: stop, back up, upgrade, reset
```bash
omc ps; omc stop; omc start; omc restart openmetadata-server
omc down                                   # keeps the data: ./docker-volume/db-data-postgres + named volumes
docker exec openmetadata_postgresql pg_dump -U postgres -Fc openmetadata_db > ~/om-lab/om-$(date +%F).dump
# Upgrade: set OM_VER, download into a new file, `diff -u` it against the current one, take a dump, then
#   omc pull && omc up -d       (the migration runs automatically; 2.0 has NO automated downgrade)
# Full reset - DELETES all lab metadata:
omc down -v && sudo rm -rf ~/om-lab/docker-volume
```

---

## 4. Change ports without a new FER per test

A FER (firewall exception request) is only needed when traffic has to cross a firewall or security group to reach
the host. If every test service binds to **127.0.0.1** and you reach it through a channel that is already approved
(SSM, SSH, or an existing NGINX port), new test ports need no new rule. Check that your existing approval allows
reaching a new service that way: some approvals are scoped per service, not per port.

Port convention for test copies: **10000 + the standard port** (18585, 18080, 18000, 14000, 15432). That way a test
copy never collides with the real service and is easy to spot in `ss`.

### 4.1 What is using a port, and pick a free one
```bash
sudo ss -lntp                                   # every listening TCP socket + owning process
sudo ss -lntp 'sport = :8585'
sudo lsof -iTCP:8585 -sTCP:LISTEN               # sudo dnf install -y lsof if missing
docker ps --filter publish=8585 --format '{{.Names}} {{.Ports}}'
docker ps --format '{{.Names}}\t{{.Ports}}'     # every published port
python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])'   # any free port
for p in $(seq 18080 18090); do ss -lnt "sport = :$p" | grep -q LISTEN || { echo "free: $p"; break; }; done
```

### 4.2 Reach loopback ports from your laptop (no inbound rule)
```bash
# SSM: no inbound port, no SSH key (needs the session-manager-plugin on the laptop). One session per port.
# portNumber = port on the instance, localPortNumber = port on your laptop.
aws ssm start-session --target i-0123456789abcdef0 --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8585"],"localPortNumber":["8585"]}'
aws ssm start-session --target i-0123456789abcdef0 --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["8080"],"localPortNumber":["18080"]}'          # second terminal: Airflow
# A host only the instance can reach (RDS, an OpenSearch domain):
aws ssm start-session --target i-0123456789abcdef0 --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["<db>.<id>.<region>.rds.amazonaws.com"],"portNumber":["5432"],"localPortNumber":["15432"]}'
# SSH, if SSH is the approved path: many ports over one connection
ssh -N -L 8585:127.0.0.1:8585 -L 18080:127.0.0.1:8080 -L 14000:127.0.0.1:4000 ec2-user@<host>
```
On a Windows laptop (PowerShell), put the parameters in a file to avoid quoting problems:
`--parameters file://pf-8585.json`, where the file holds `{"portNumber":["8585"],"localPortNumber":["8585"]}`.

### 4.3 Remap a container's host port (the app inside does not change)
You cannot change the published ports of a running container: it has to be recreated. With Compose, change the value
and run `up -d`, which recreates only the services whose config changed.
```bash
# OpenMetadata lab (section 3): the host ports come from .env
sed -i 's/^OM_HTTP_HOST_PORT=.*/OM_HTTP_HOST_PORT=18585/' ~/om-lab/.env
omc up -d openmetadata-server
omc port openmetadata-server 8585           # -> 127.0.0.1:18585
```
Remapping the **host** side is safe because containers talk to each other on container ports
(`http://openmetadata-server:8585/api`, `http://ingestion:8080`), so nothing else needs to change.

Any other Compose project: add a small override file.
```yaml
# ports-test.override.yml
services:
  <svc>:
    ports: !override                 # without !override the new mapping is ADDED next to the old one
      - "127.0.0.1:18080:8080"
```
```bash
docker compose -p <project> -f compose.yml -f ports-test.override.yml config --format json \
  | python3 "$KIT/scripts/check_port_exposure.py"
docker compose -p <project> -f compose.yml -f ports-test.override.yml up -d <svc>
```
For the kit's stacks, `scripts/compose_safe.sh` only knows its fixed files. To use an override, run `docker compose`
with both files plus the same `--env-file`, and pipe through `check_port_exposure.py` as shown above.

Plain `docker run` containers have to be recreated by hand, so prefer Compose:
```bash
docker inspect <c> -f '{{.Config.Image}} {{json .HostConfig.PortBindings}} {{json .Config.Env}} {{json .Mounts}}'
docker stop <c> && docker rename <c> <c>-old
docker run -d --name <c> -p 127.0.0.1:18080:8080 <same env, volumes and image as shown above>
docker rm <c>-old                           # once the new one works
```

### 4.4 Change the port an app listens on
| App | How | Watch out |
|---|---|---|
| Opsi FastAPI (uvicorn) | `uvicorn app.main_example:lab_app --factory --host 127.0.0.1 --port 18000` | NGINX `proxy_pass` and `OPSI_AGENT_BASE_URL` must follow |
| copilot-runtime (systemd) | `sudo systemctl edit opsi-copilot-runtime` -> `[Service]` + `Environment=RUNTIME_PORT=14000`, then `sudo systemctl restart opsi-copilot-runtime` | a `RUNTIME_PORT` in `/etc/opsi/copilot-runtime.env` wins over `Environment=`; update NGINX |
| copilot-runtime (compose) | override `environment: {RUNTIME_PORT: "14000"}` | host network: the listen port *is* the host port |
| OpenMetadata server | `SERVER_PORT` / `SERVER_ADMIN_PORT` | also change the container side of `ports:`, the healthcheck (hard-codes 8586), `SERVER_HOST_API_URL` and every workflow `hostPort`. Remap the host port instead (4.3) |
| Airflow (OpenMetadata ingestion image) | not configurable: `ingestion_dependency.sh` starts `airflow api-server --port 8080` | remap the host port only |
| PostgreSQL container | `command: ["postgres", "-p", "5433"]` | healthcheck and every client. Remap instead |
| OpenSearch container | `http.port=9201` in `environment` | healthcheck and `ELASTICSEARCH_PORT`. Remap instead |
| NGINX | `listen 127.0.0.1:18443 ssl;` then `sudo nginx -t && sudo systemctl reload nginx` | |

Check the app after the change:
`sudo ss -lntp | grep -E ':(18000|14000)\b'` and `curl -fsS -m 5 http://127.0.0.1:18000/...`.

### 4.5 Reuse an already approved port through NGINX paths
If 443 on the NGINX host is already approved, put a test app behind a path instead of a new port:
```nginx
# inside the existing revamp server block (SSE/buffering settings: infrastructure/nginx/opsi-revamp.locations.conf)
location /lab/test-api/ {
    proxy_pass http://127.0.0.1:18000/;      # trailing slash strips the /lab/test-api prefix
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```
```bash
sudo cp -a /etc/nginx/conf.d/<file>.conf /etc/nginx/conf.d/<file>.conf.bak.$(date +%F)
sudo nginx -t && sudo systemctl reload nginx
```
This only works for apps that support a base path: FastAPI `root_path`, Airflow `AIRFLOW__API__BASE_URL`, and most
Node servers. Single-page UIs that assume `/` need a tunnel (4.2). Everyone who can reach 443 can reach the path, so
keep authentication on and remove the location when the test ends.

### 4.6 Side-by-side copies
`docker compose -p test1 ...` keeps volumes and networks separate per project. Give each copy its own host ports
(an `.env` per copy). A `container_name:` in the file defeats `-p`, so the OpenMetadata files allow one stack per host.

### 4.7 After any port change
```bash
sudo ss -lntp | grep -vE '127\.0\.0\.[0-9]+:|\[::1\]:'   # anything listening beyond loopback?
docker ps --format '{{.Names}} {{.Ports}}' | grep -E '(0\.0\.0\.0|\[::\]):[0-9]+->'   # published on all interfaces
```
If a line shows up, the port is reachable from the network: the host firewall does not stop Docker-published ports,
so only the security group or your FER stands in the way. Fix the binding to 127.0.0.1 rather than asking for a rule.

---

## 5. Git: copy, back up, fork

Set the URLs once. Authenticate with `gh auth login` or a credential helper, and **never put credentials in URLs**
([git-and-gh.md](git-and-gh.md)). `gh` takes `[HOST/]OWNER/REPO`: on GHES, prefix the host or set `GH_HOST`.
```bash
SRC=https://git.corp.example/ORG/reference.git      # the repo you copy from
DST=https://git.corp.example/ORG/working.git        # an EMPTY repo you created (gh repo create / Git admins)
```

### 5.1 Basics
```bash
git status -sb; git log --oneline --graph --decorate -20
git diff; git diff --staged; git diff main...HEAD --stat
git switch main && git pull --ff-only
git switch -c test/<topic>
git add -p && git commit -m "area: what changed"
git fetch --all --prune; git branch -vv            # tracking branch + ahead/behind
git push -u origin test/<topic>
git stash push -m wip; git stash list; git stash pop
git restore <file>                                 # discard unstaged edits (cannot be undone)
git reset --soft HEAD~1                            # undo the last LOCAL commit, keep its changes staged
git revert <sha>                                   # undo a PUSHED commit with a new commit
git reflog | head -20                              # find "lost" commits after a bad reset/rebase
git clean -nd                                      # preview untracked files to delete (-fd deletes)
```

### 5.2 Copy a reference repo into a new working repo (full history)
```bash
TMP=$(mktemp -d)
git clone --bare "$SRC" "$TMP/ref.git"
git -C "$TMP/ref.git" lfs fetch --all 2>/dev/null && git -C "$TMP/ref.git" lfs push --all "$DST"   # only if it uses LFS
git -C "$TMP/ref.git" push "$DST" '+refs/heads/*:refs/heads/*' '+refs/tags/*:refs/tags/*'
rm -rf "$TMP"
gh repo edit ORG/working --default-branch main     # if the wrong branch became the default

git clone "$DST" ~/workspaces/working && cd ~/workspaces/working
git remote add reference "$SRC"
git remote set-url --push reference DISABLED-reference-is-read-only   # you can fetch it but never push to it
git remote -v
```
- Push branches and tags explicitly rather than `clone --mirror` + `push --mirror`. A mirror clone of a GitHub repo
  also carries the read-only `refs/pull/*`, and pushing those fails. `scripts/repo/mirror_upstream.sh` does the same
  for this reason.
- The `+` overwrites. Only point this at an **empty** target.

### 5.3 New repo from a reference snapshot (no history)
```bash
REF=<tag-or-branch>
mkdir ~/workspaces/working && cd ~/workspaces/working && git init -b main
git -C ~/workspaces/reference archive --format=tar "$REF" | tar -x -C .
git add -A && git commit -m "Import reference at $REF ($(git -C ~/workspaces/reference rev-parse --short "$REF"))"
git remote add origin "$DST" && git push -u origin main
```

### 5.4 Bring selected files or folders from a reference into your repo
```bash
git remote add reference "$SRC"; git remote set-url --push reference DISABLED-reference-is-read-only
git fetch reference
git log --oneline HEAD..reference/main                         # what the reference has that you don't
git restore --source=reference/main --staged --worktree -- path/to/dir path/file.py
git diff --staged --stat && git commit -m "Copy path/to/dir from reference@$(git rev-parse --short reference/main)"
git cherry-pick <sha>                                          # a single commit from the reference
```
To give one folder its own repo **with its history**:
```bash
git -C ~/workspaces/reference subtree split --prefix=path/to/dir -b split/dir   # missing? sudo dnf install -y git-subtree
git -C ~/workspaces/reference push "$DST" split/dir:main
```
For the **product** repo, bring third-party code in with `scripts/repo/vendor_component.py`, which records provenance
and the licence. Don't copy it by hand ([../repository-strategy.md](../repository-strategy.md)).

### 5.5 Back up a repo: fork vs independent backup
A fork is quick, but only works on the same host:
```bash
gh repo fork ORG/repo --org MYORG --fork-name repo-backup --clone=false
gh repo sync MYORG/repo-backup --source ORG/repo               # later: refreshes the default branch only
```
A fork is **not** a backup you control:
- forks of public repos are always public;
- private forks are deleted when the parent private repo is deleted or your access to it is removed;
- you cannot fork across hosts (github.com -> GHES);
- a fork only holds what was pushed.

For a real backup, use an independent private repo:
```bash
gh repo create MYORG/repo-backup --private --description "Backup of ORG/repo"
BACKUP=https://git.corp.example/MYORG/repo-backup.git
"$KIT/scripts/repo/mirror_upstream.sh" "$SRC" "$BACKUP"       # bare cache, branches + tags, prune; re-run to refresh
```
The script works for any repo, not just upstreams. Schedule it with a systemd timer for a rolling backup
([systemd-cron.md](systemd-cron.md)). It propagates deletions (`--prune`), so also keep point-in-time bundles:
```bash
mkdir -p ~/backups
git -C ~/workspaces/working bundle create ~/backups/working-$(date +%F).bundle --all
git -C ~/workspaces/working bundle verify ~/backups/working-$(date +%F).bundle
(cd ~/backups && sha256sum *.bundle > SHA256SUMS)
git clone ~/backups/working-2026-10-25.bundle restored          # restore = clone the bundle
```
Some things are not in Git and have to be exported separately:
- issues and PRs: `gh issue list --state all --limit 1000 --json number,title,state,body,comments > issues.json`
- the wiki: a separate repo, `<repo>.wiki.git`, which you can clone the same way
- releases and their assets
- Actions secrets and variables, and branch protection rules

### 5.6 Before any push
```bash
git remote -v                                      # only the intended origin has a real push URL
git log --oneline @{u}..HEAD                       # exactly what will be pushed
python3 "$KIT/scripts/secret_scan.py"              # the kit's secret scan
```
Push only with approval, and never to `legacy-opsi` (see the two-clone workflow in [git-and-gh.md](git-and-gh.md)).
