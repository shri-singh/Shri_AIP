# GitHub token safety and forks

Use approved corporate Git credential manager when possible. Do not interpolate tokens into HTTPS URLs, echo tokens or set shell xtrace (`set -x`).

For GitHub.com / Enterprise Cloud:
```bash
read -rs -p 'GitHub.com / Cloud token: ' GH_TOKEN; echo; export GH_TOKEN
gh auth status
gh auth setup-git  # configures a credential helper; review org policy
```

For **GitHub Enterprise Server** (on-prem `git.company.example`):
```bash
export GH_HOST=git.company.example
read -rs -p 'GitHub Enterprise Server token: ' GH_ENTERPRISE_TOKEN; echo; export GH_ENTERPRISE_TOKEN
gh auth status --hostname "$GH_HOST"
gh auth setup-git --hostname "$GH_HOST"
```

No token is committed to disk by the environment-variable authentication itself. Beware shell history, terminal sharing, process tracing and corporate credential policies. Run `unset GH_TOKEN GH_ENTERPRISE_TOKEN` after commands.

Clone baseline and **new** revamp repo (two clones, no feature branch):
```bash
export OPSI_SOURCE_URL='https://git.company.example/ORG/opsi.git'
export OPSI_GH_DEST='ORG/opsi-enterprise-revamp'
bash scripts/01_clone_opsi.sh
```

Optional fork *on github.com*, if approved by your company:
```bash
export GITHUB_FORK_ORG='my-approved-org-on-github-com'
bash scripts/08_fork_upstreams.sh
```
You cannot create a native GitHub fork **across** GitHub.com and an independently hosted GitHub Enterprise Server. Mirror/import with approvals instead of assuming `gh repo fork` works cross-host. No need to fork upstream if read-only clones suffice.
