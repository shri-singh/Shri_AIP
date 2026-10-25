# Phase 1 - repositories and development containers

## 1.1 Authenticate Git safely (no tokens in URLs)
```bash
gh auth login --hostname git.corp.example        # GitHub Enterprise Server; or plain `gh auth login` for github.com
gh auth setup-git --hostname git.corp.example    # credential helper; review org policy
git config --global credential.helper            # confirm a helper is set
```
Never `export GH_TOKEN=...` in shell history; if you must, `read -rs -p 'token: ' GH_TOKEN; export GH_TOKEN` and `unset GH_TOKEN` after.
Details: [../cheatsheets/git-and-gh.md](../cheatsheets/git-and-gh.md).

## 1.2 Two clones
```bash
export OPSI_SOURCE_URL='https://git.corp.example/ORG/opsi.git'
export OPSI_NEW_REMOTE_URL='https://git.corp.example/ORG/opsi-enterprise-revamp.git'   # created by Git admins, empty
scripts/clone_repos.sh ~/workspaces
git -C ~/workspaces/opsi-enterprise-revamp remote -v
#   legacy-opsi  https://git.corp.example/ORG/opsi.git (fetch)
#   legacy-opsi  DISABLED-legacy-is-read-only (push)
#   origin       https://git.corp.example/ORG/opsi-enterprise-revamp.git (fetch/push)
```
Uncommitted work in someone's existing checkout is **not** in these clones - ask them to commit/push it to an approved place first.
First push only after approval: `git -C ~/workspaces/opsi-enterprise-revamp push -u origin revamp/phase-1`.

## 1.3 Pinned upstream study clones and the workspace manifest
Strategy and reasons: [../repository-strategy.md](../repository-strategy.md) (mirrors not forks, components not repos).
```bash
OM_REF=2.0.6-release COPILOT_REF=v1.79.1 scripts/fetch_upstreams.sh ~/workspaces/upstream   # or OM_URL/COPILOT_URL = corporate mirrors
cat ~/workspaces/upstream/PROVENANCE.md
cp infrastructure/repo/workspace.example.json ~/workspaces/workspace.json && vi ~/workspaces/workspace.json
python3 scripts/repo/workspace.py init   --manifest ~/workspaces/workspace.json
python3 scripts/repo/workspace.py verify --manifest ~/workspaces/workspace.json      # must report 0 problems
```
Keep `upstream/` outside the revamp repo. **No submodules.** Files enter the product only via
`scripts/repo/vendor_component.py` (provenance + licence), never by hand.

## 1.3b Product repo policy (commit-plan step 1a)
Copy the templates from [../../infrastructure/repo/](../../infrastructure/repo/README.md) (CODEOWNERS, CI, Dependabot,
PR template, `.gitattributes`, `third_party/README.md`), run `python3 scripts/repo/repo_hygiene.py`, open the PR, and
ask the repo admins to protect `main` with the CI jobs as required checks.

## 1.4 OpenMetadata lab (isolated host only)
Prerequisites: Docker Compose >= 2.24, `vm.max_map_count >= 262144`, ~16 GiB RAM free, isolated security group.
```bash
cp infrastructure/compose/openmetadata.lab.env.example .openmetadata-lab.env && chmod 600 .openmetadata-lab.env
vi .openmetadata-lab.env    # generate every value (commands are in the file)
export OM_DEV_COMPOSE=~/workspaces/upstream/OpenMetadata/docker/development/docker-compose-postgres.yml
scripts/compose_safe.sh openmetadata-lab config       # must print "port exposure check passed"
I_ACCEPT_LAB_ONLY=YES scripts/compose_safe.sh openmetadata-lab up     # builds from source: 20-40 min first time
scripts/compose_safe.sh openmetadata-lab ps
curl -s http://127.0.0.1:8586/healthcheck
```
Reach the UI with an SSH/SSM tunnel: `aws ssm start-session --target <instance-id> --document-name AWS-StartPortForwardingSession --parameters '{"portNumber":["8585"],"localPortNumber":["8585"]}'`
then http://localhost:8585 (default lab login per OpenMetadata docs; change it).

Faster alternative (no source build): the 2.0.6 **quickstart** compose uses release images (`docker/docker-compose-quickstart/docker-compose-postgres.yml`,
Elasticsearch 9.3.0). It has the same exposure problems - write an equivalent override (service `elasticsearch`
instead of `opensearch`) and check it with `scripts/check_port_exposure.py`.

## 1.5 Revamp side-car stack (later phases, validate now)
```bash
sudo install -m 0600 /dev/null /etc/opsi/revamp.env   # fill from .env.example sections
scripts/compose_safe.sh opsi-revamp config
```

## Exit criteria
- Clones exist with push disabled on legacy; new origin set; nothing pushed without approval.
- `upstream/PROVENANCE.md` recorded; `workspace.py verify` exits 0.
- Product repo policy PR open (hygiene + secret scan green locally).
- OpenMetadata lab healthy on 127.0.0.1 only (or consciously deferred), compose config checks pass.
