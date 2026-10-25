# Git and gh

## Authenticate without leaking tokens
```bash
gh auth login --hostname git.corp.example --git-protocol https     # GitHub Enterprise Server
gh auth status --hostname git.corp.example
gh auth setup-git --hostname git.corp.example
git config --global credential.helper            # should show gh / manager
# never put credentials in clone URLs (https://<user>:<token>@host/...); never echo $GH_TOKEN
history | grep -i token                          # check; remove lines with: history -d <n>
```
If an env token is unavoidable: `read -rs -p 'token: ' GH_TOKEN; export GH_TOKEN` ... `unset GH_TOKEN`.
Cross-host forks (github.com -> GHES) don't exist; import/mirror with approval instead.

## Two-clone workflow
```bash
git -C ~/workspaces/opsi-baseline-snapshot remote -v       # push = DISABLED...
git -C ~/workspaces/opsi-enterprise-revamp remote -v       # legacy-opsi push disabled, origin = new repo
git -C ~/workspaces/opsi-enterprise-revamp fetch legacy-opsi
git log --oneline legacy-opsi/main -10
git cherry-pick <sha>                         # bring a legacy fix
git diff legacy-opsi/main...HEAD --stat       # what the revamp changed
```

## Everyday
```bash
git switch -c revamp/<topic>
git add -p                                     # review hunks
git commit -m "ingestion: add grail collector config" -m "Evidence: pytest tests/ingestion 93 passed" -m "Rollback: revert"
git log --oneline --graph -15
git stash push -m wip; git stash pop
git restore --staged <file>; git restore <file>
git revert <sha>                               # safe rollback of a pushed commit
python3 scripts/secret_scan.py                 # before every push
git push -u origin revamp/<topic>              # only with approval; never to legacy-opsi
gh pr create --fill --base main
```

## Pinned upstreams
```bash
U=~/workspaces/upstream/OpenMetadata
git -C $U describe --tags; git -C $U rev-parse HEAD
git -C $U log -1 --format='%H %ad %s' --date=short
git -C $U show 2.0.6-release:docker/development/docker-compose-postgres.yml | less
git -C $U worktree add ../worktrees/OpenMetadata-<tag> <tag>      # second version side by side
```

## Workspace, mirrors, vendoring ([../repository-strategy.md](../repository-strategy.md))
```bash
python3 scripts/repo/workspace.py verify --manifest ~/workspaces/workspace.json     # push protection + pins
python3 scripts/repo/workspace.py upstream-updates --manifest ~/workspaces/workspace.json
python3 scripts/repo/vendor_component.py list          # also: verify, diff-upstream --id X --upstream DIR --to TAG
python3 scripts/repo/repo_hygiene.py                   # before every PR
git remote -v | grep push                              # only the product origin may show a real push URL
```
