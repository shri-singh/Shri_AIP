# Convenience targets (GNU make). Everything is local and read-only unless stated.
PY ?= .venv/bin/python
WS ?= $(HOME)/workspaces/workspace.json
REPO ?= .
.PHONY: help venv test test-integration lint smoke validate-sql runtime web e2e kb secrets licenses preflight \
	test-repo workspace-verify upstream-updates repo-hygiene vendored-verify

help:
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/ -/'

venv: ## create .venv with all Python deps (Python >= 3.11)
	python3 -m venv .venv && $(PY) -m pip install -U pip && $(PY) -m pip install -r requirements/dev.txt

test: ## unit tests (ingestion + api)
	$(PY) -m pytest -q

test-integration: ## PostgreSQL integration tests against a throwaway PGlite server (needs node)
	cd database/validate && npm ci --silent && (node serve_pglite.mjs --port 55432 --seed & echo $$! > /tmp/pglite.pid; sleep 5)
	TEST_DATABASE_URL='postgresql://postgres@127.0.0.1:55432/postgres?sslmode=disable' $(PY) -m pytest -m integration -q; \
	  status=$$?; kill $$(cat /tmp/pglite.pid); exit $$status

lint: ## ruff
	$(PY) -m ruff check services apps/opsi-api tests tools scripts

validate-sql: ## apply migrations + RLS checks on PGlite
	cd database/validate && npm ci --silent && node validate_migrations.mjs

runtime: ## build + test the CopilotKit V2 runtime bridge
	cd apps/copilot-runtime && SCARF_ANALYTICS=false npm ci && npm test

web: ## type-check the React features against CopilotKit V2
	cd apps/opsi-web && SCARF_ANALYTICS=false npm ci && npx tsc -p tsconfig.json --noEmit && node scripts/verify-copilotkit-v2.mjs src

e2e: ## browser-shaped request -> runtime -> FastAPI AG-UI -> restore thread
	$(PY) tests/e2e/bridge_smoke.py

smoke: ## run every local check and summarise
	PYTHON=$(PY) scripts/smoke_all.sh

kb: ## ask the kit: make kb Q="how do I reset a watermark"
	$(PY) tools/kb/ask.py "$(Q)"

secrets: ## scan tracked files for secrets
	$(PY) scripts/secret_scan.py

licenses: ## dependency license reports into reports/
	PYTHON=$(PY) scripts/license_scan.sh

preflight: ## host readiness (read-only)
	scripts/preflight.sh

test-repo: ## repository-tool tests (workspace, vendoring, hygiene, mirror) on throwaway git repos
	$(PY) -m pytest tests/repo -q

workspace-verify: ## workspace policy: make workspace-verify WS=~/workspaces/workspace.json
	$(PY) scripts/repo/workspace.py verify --manifest $(WS)

upstream-updates: ## newer upstream tags than the pinned refs in $(WS)
	$(PY) scripts/repo/workspace.py upstream-updates --manifest $(WS)

repo-hygiene: ## product repo cleanliness: make repo-hygiene REPO=~/workspaces/opsi-enterprise-revamp
	$(PY) scripts/repo/repo_hygiene.py --repo-root $(REPO)

vendored-verify: ## vendored files match third_party/VENDORED.json (REPO=product repo)
	$(PY) scripts/repo/vendor_component.py --repo-root $(REPO) verify
