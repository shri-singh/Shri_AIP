# Manual Linux / EC2 install runbook

## Tool checks
```bash
cat /etc/os-release
uname -a
whoami && id
git --version
docker --version
docker compose version
docker info | sed -n '1,35p'
python3 --version
aws --version
gh --version || true
aws sts get-caller-identity
free -h
df -h
```
Use `docker compose` v2, not legacy `docker-compose`. Check disk/RAM before starting OpenMetadata's dev source build.

## Edit basics
```bash
nano .env
vi .env
sed -n '1,160p' README.md
grep -R 'SEARCH_TYPE' vendor/OpenMetadata/docker/development/
find . -maxdepth 3 -type f | sort
cp .env.example .env && chmod 600 .env
```
Avoid placing secrets in version control; `.env` is gitignored.

## Clone and create separate revamp repository
```bash
export OPSI_SOURCE_URL='https://github.example.com/ORG/opsi.git'
export OPSI_GH_DEST='ORG/opsi-enterprise-revamp'
# Authenticate GH CLI first; for GitHub Enterprise pass `--hostname` as needed.
read -rs -p 'GitHub token: ' GH_TOKEN; echo; export GH_TOKEN
# For GitHub Enterprise Server use GH_HOST and GH_ENTERPRISE_TOKEN instead.
# See docs/GITHUB_AUTH_AND_FORKS.md and run gh auth setup-git for the correct host.
bash scripts/01_clone_opsi.sh
unset GH_TOKEN
```
Cloning does not capture uncommitted changes in an existing local worktree. Commit/preserve them in a **private approved** place first. A clone under another local folder is not automatically a new remote repo.

## Fetch upstream source
```bash
bash scripts/02_fetch_upstreams.sh
# Record exact upstream versions after cloning:
git -C vendor/OpenMetadata rev-parse HEAD
git -C vendor/CopilotKit rev-parse HEAD
```
Upstreams live outside the revamp app's source tree unless deliberately added as submodules; the starter's gitignore excludes `vendor/`. Source is for study and selectively cherry-picking licensed components.

## OpenMetadata development lab
```bash
bash scripts/03_openmetadata_dev.sh config
bash scripts/03_openmetadata_dev.sh up
bash scripts/03_openmetadata_dev.sh ps
bash scripts/03_openmetadata_dev.sh logs
bash scripts/03_openmetadata_dev.sh down
```
**Upstream development Compose uses insecure lab defaults and potentially public port bindings.** Run only on isolated EC2 security groups / local test VMs. Never assume database IDs, images or ports are production-safe.

## AWS S3
```bash
export AWS_REGION=us-west-2
export OPSI_ARCHIVE_BUCKET=your-org-approved-unique-bucket-name
bash scripts/04_create_s3.sh
aws s3 ls "s3://$OPSI_ARCHIVE_BUCKET/"
```
The script creates encryption (SSE-S3), versioning and public-access block. Ask security team about SSE-KMS, bucket policy, object lock, replication and retention. Don't rerun against a bucket you don't administer.

## Collectors
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r ingestion/requirements.txt
cp .env.example .env && chmod 600 .env
# Apply DB schema with DBA approval; requires psycopg user permissions
psql "$DATABASE_URL" -f sql/001_opsi_extensions.sql
python -m ingestion.run_once --source elastic
python -m ingestion.run_once --source dynatrace_problems
python -m ingestion.run_once --source dynatrace_grail
# Cron after successful smoke tests
bash scripts/05_install_cron.sh
crontab -l
sudo journalctl -u crond --no-pager -n 30 || true
```
Use systemd timers + CloudWatch logs/alarms for production. Cron invokes one source per 5 minutes with `flock`, enforcing no same-source overlap. Underlying collectors use lag + checkpoint + overlap.

## Operational diagnostics
```bash
docker compose -f compose/otel-lab.yml config
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
docker logs --tail 100 CONTAINER_NAME
ss -lntp
crontab -l
aws s3 ls "s3://$OPSI_ARCHIVE_BUCKET/raw/" --recursive | tail -n 20
psql "$DATABASE_URL" -c 'SELECT source,count(*) FROM opsi_ingest.incident_events GROUP BY 1;'
```

## PostgreSQL archive and backup
- For managed RDS/Aurora, configure snapshot/PITR and restore drills in AWS, not a daily dump of an existing multi-terabyte cluster.
- For modest Opsi *application tables*, `scripts/06_pg_dump_s3.sh` provides a manual logical `.dump` to S3 after approval.
- An RDS snapshot export to S3 produces Parquet for analytics and **cannot** be used directly to restore a DB (AWS documentation).
