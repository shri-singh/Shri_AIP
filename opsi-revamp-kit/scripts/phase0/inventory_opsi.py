#!/usr/bin/env python3
"""Phase 0 inventory of an Opsi source checkout - READ-ONLY, standard library only.

Produces a Markdown report (and JSON) answering the master prompt's Phase 0 questions:
package manager/lockfile, React/TS/build tool/router, existing CopilotKit usage (V1?),
FastAPI layout and routers, auth mechanism, DB libraries and migrations, Redis, existing
integrations (Elastic/OpenSearch/Dynatrace/Portkey/Bedrock/LLM SDKs), env var NAMES,
Docker/Compose/NGINX/systemd/CI files, published ports, and secret-looking strings
(reported as file + pattern name only, never the value).

    python3 scripts/phase0/inventory_opsi.py ~/workspaces/opsi-baseline-snapshot --out inventory/
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "dist", "build", "__pycache__", ".next", "coverage", ".mypy_cache",
             ".pytest_cache", "vendor", ".tox", "site-packages"}
MAX_FILE_BYTES = 1_000_000

FRONTEND_KEYS = ["react", "react-dom", "typescript", "vite", "react-scripts", "webpack", "next", "@vitejs/plugin-react",
                 "react-router-dom", "react-router", "@tanstack/react-router", "redux", "@reduxjs/toolkit", "zustand",
                 "@tanstack/react-query", "react-query", "mobx", "@mui/material", "antd", "@chakra-ui/react",
                 "tailwindcss", "echarts", "echarts-for-react", "recharts", "chart.js", "highcharts", "d3",
                 "reactflow", "@xyflow/react", "axios", "zod", "msal-browser", "@azure/msal-browser", "oidc-client-ts",
                 "keycloak-js", "@okta/okta-react", "aws-amplify", "@copilotkit/react-core", "@copilotkit/react-ui",
                 "@copilotkit/runtime", "@ag-ui/client", "jest", "vitest", "@playwright/test", "cypress"]

PY_PATTERNS = {
    "fastapi_app": re.compile(r"\bFastAPI\s*\("),
    "api_router": re.compile(r"\bAPIRouter\s*\("),
    "include_router": re.compile(r"include_router\s*\("),
    "oauth2_bearer": re.compile(r"OAuth2PasswordBearer|HTTPBearer|APIKeyHeader"),
    "jwt_decode": re.compile(r"jwt\.decode|jose\.jwt|PyJWKClient|python_jose"),
    "current_user_dep": re.compile(r"Depends\(\s*get_current_\w+"),
    "session_cookie": re.compile(r"SessionMiddleware|request\.session|set_cookie\("),
    "sqlalchemy": re.compile(r"\bfrom sqlalchemy|import sqlalchemy|create_async_engine|create_engine\("),
    "asyncpg": re.compile(r"\basyncpg\b"),
    "psycopg2": re.compile(r"\bpsycopg2\b"),
    "psycopg3": re.compile(r"\bimport psycopg\b|\bfrom psycopg\b"),
    "redis": re.compile(r"\bredis\b|aioredis"),
    "celery": re.compile(r"\bcelery\b"),
    "elasticsearch": re.compile(r"\belasticsearch\b|Elasticsearch\("),
    "opensearch": re.compile(r"\bopensearchpy\b|OpenSearch\("),
    "dynatrace": re.compile(r"dynatrace|/api/v2/problems|query:execute", re.I),
    "portkey": re.compile(r"\bportkey", re.I),
    "bedrock": re.compile(r"bedrock-runtime|bedrock_runtime|BedrockRuntime|ChatBedrock", re.I),
    "openai_sdk": re.compile(r"\bfrom openai\b|\bimport openai\b"),
    "anthropic_sdk": re.compile(r"\bimport anthropic\b|\bfrom anthropic\b"),
    "langchain": re.compile(r"\blangchain"),
    "llama_index": re.compile(r"\bllama_index\b"),
    "pgvector": re.compile(r"\bpgvector\b|Vector\(\d+\)"),
    "opentelemetry": re.compile(r"\bopentelemetry\b"),
    "sse_streaming": re.compile(r"StreamingResponse|EventSourceResponse|text/event-stream"),
}
TS_PATTERNS = {
    "copilotkit_v1_provider": re.compile(r"<CopilotKit[\s>]"),
    "copilotkit_v1_import": re.compile(r"from\s+['\"]@copilotkit/react-(core|ui)['\"]"),
    "copilotkit_v2_import": re.compile(r"from\s+['\"]@copilotkit/react-core/v2['\"]"),
    "fetch_eventsource": re.compile(r"EventSource|fetchEventSource|text/event-stream"),
    "auth_token_storage": re.compile(r"localStorage\.(get|set)Item\(\s*['\"][^'\"]*(token|jwt)", re.I),
    "react_router_routes": re.compile(r"<Routes>|createBrowserRouter\("),
}
SECRET_PATTERNS = {
    "aws_access_key_id": re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    "private_key_block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "dynatrace_token": re.compile(r"\bdt0[a-z]\d{2}\.[A-Za-z0-9]{20,}"),
    "github_token": re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    "portkey_key": re.compile(r"\bpk-[A-Za-z0-9]{20,}"),
    "jwt_literal": re.compile(r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}"),
    "password_assignment": re.compile(r"(?i)(password|passwd|secret|api_key)\s*[:=]\s*['\"][^'\"\s$]{6,}['\"]"),
    "url_with_credentials": re.compile(r"[a-z]+://[^/\s:@]+:[^/\s@]{3,}@"),
}
ENV_NAME = re.compile(r"(?:os\.getenv|os\.environ\.get|os\.environ\[|process\.env\.|import\.meta\.env\.)\(?\s*['\"]?([A-Z][A-Z0-9_]{2,})")


def walk(root: Path):
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        if path.is_file():
            yield path


def read(path: Path) -> str:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def mask_url(url: str) -> str:
    return re.sub(r"://[^@/]+@", "://***@", url)


def inventory(root: Path) -> dict:
    report: dict = {"root": str(root), "generated_at": datetime.now(timezone.utc).isoformat()}
    report["git"] = {
        "head": git(root, "rev-parse", "HEAD"), "branch": git(root, "rev-parse", "--abbrev-ref", "HEAD"),
        "remotes": [mask_url(line) for line in git(root, "remote", "-v").splitlines()],
        "uncommitted_files": len([line for line in git(root, "status", "--porcelain").splitlines() if line.strip()]),
        "last_commits": git(root, "log", "-5", "--pretty=%h %ad %s", "--date=short").splitlines(),
    }
    frontends, python_deps, migrations, infra, env_names = [], defaultdict(set), [], defaultdict(list), Counter()
    py_hits, ts_hits, secrets = defaultdict(list), defaultdict(list), defaultdict(list)
    routers: list[str] = []
    for path in walk(root):
        rel = str(path.relative_to(root))
        name = path.name
        if name == "package.json":
            try:
                pkg = json.loads(read(path) or "{}")
            except json.JSONDecodeError:
                continue
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            lock = next((lf for lf in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml") if (path.parent / lf).exists()), None)
            tsconfig = path.parent / "tsconfig.json"
            module_resolution = None
            if tsconfig.exists():
                m = re.search(r'"moduleResolution"\s*:\s*"([^"]+)"', read(tsconfig))
                module_resolution = m.group(1) if m else "default"
            frontends.append({"path": rel, "name": pkg.get("name"), "lockfile": lock, "engines": pkg.get("engines"),
                              "scripts": sorted(pkg.get("scripts", {}))[:20], "tsconfig_moduleResolution": module_resolution,
                              "key_dependencies": {k: deps[k] for k in FRONTEND_KEYS if k in deps},
                              "dependency_count": len(deps)})
        elif name.startswith("requirements") and name.endswith(".txt") or name in ("pyproject.toml", "Pipfile", "setup.cfg"):
            for line in read(path).splitlines():
                m = re.match(r"\s*\"?([A-Za-z0-9_.\-\[\]]+)\s*([<>=!~^][^;\"#]*)?", line)
                if m and not line.strip().startswith(("#", "[", "-")):
                    python_deps[rel].add((m.group(1).lower() + (m.group(2) or "")).strip())
        elif name == "alembic.ini" or (path.parent.name == "versions" and path.suffix == ".py"):
            migrations.append(rel)
        elif name.lower().startswith("dockerfile") or name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml") \
                or name.endswith((".service", ".timer")) or (name.endswith(".conf") and "nginx" in rel.lower()) \
                or ".github/workflows" in rel.replace("\\", "/") or name in (".gitlab-ci.yml", "Jenkinsfile", "buildspec.yml"):
            entry = {"file": rel}
            if "compose" in name:
                entry["published_ports"] = re.findall(r"^\s*-\s*[\"']?([\d.:]+:\d+(?::\d+)?)", read(path), re.M)
            infra["files"].append(entry)
        if path.suffix in (".py", ".ts", ".tsx", ".js", ".jsx", ".env", ".yml", ".yaml", ".json", ".ini", ".cfg", ".toml", ".sh", ".conf"):
            text = read(path)
            if not text:
                continue
            for env in ENV_NAME.findall(text):
                env_names[env] += 1
            for label, rx in SECRET_PATTERNS.items():
                if rx.search(text) and not rel.endswith((".lock", "package-lock.json")):
                    secrets[label].append(rel)
            if path.suffix == ".py":
                for label, rx in PY_PATTERNS.items():
                    if rx.search(text):
                        py_hits[label].append(rel)
                routers += [f"{rel}: prefix={m}" for m in re.findall(r"APIRouter\([^)]*prefix\s*=\s*['\"]([^'\"]+)", text)]
            elif path.suffix in (".ts", ".tsx", ".js", ".jsx"):
                for label, rx in TS_PATTERNS.items():
                    if rx.search(text):
                        ts_hits[label].append(rel)
    report["frontends"] = frontends
    report["python_dependency_files"] = {k: sorted(v) for k, v in python_deps.items()}
    report["python_signals"] = {k: sorted(v)[:15] for k, v in py_hits.items()}
    report["api_router_prefixes"] = sorted(routers)[:80]
    report["frontend_signals"] = {k: sorted(v)[:15] for k, v in ts_hits.items()}
    report["migrations"] = {"alembic_ini": [m for m in migrations if m.endswith("alembic.ini")],
                            "revision_files": len([m for m in migrations if m.endswith(".py")])}
    report["infra_files"] = infra["files"]
    report["env_var_names"] = sorted(env_names)
    report["possible_secrets"] = {k: sorted(set(v))[:20] for k, v in secrets.items()}
    return report


def to_markdown(r: dict) -> str:
    out = [f"# Phase 0 inventory - `{r['root']}`", f"_generated {r['generated_at']} (read-only scan)_", ""]
    g = r["git"]
    out += ["## Git", f"- HEAD `{g['head']}` on `{g['branch']}`; uncommitted files: **{g['uncommitted_files']}**",
            *[f"- remote: `{x}`" for x in g["remotes"]], *[f"- {c}" for c in g["last_commits"]], ""]
    out += ["## Frontend packages"]
    for f in r["frontends"]:
        out += [f"### `{f['path']}` ({f['name']})", f"- lockfile: {f['lockfile']}; tsconfig moduleResolution: {f['tsconfig_moduleResolution']}",
                f"- engines: {f['engines']}; scripts: {', '.join(f['scripts'])}",
                *[f"- {k}: `{v}`" for k, v in f["key_dependencies"].items()], ""]
    out += ["## Python dependency files"]
    for path, deps in r["python_dependency_files"].items():
        interesting = [d for d in deps if re.match(r"(fastapi|starlette|uvicorn|gunicorn|pydantic|sqlalchemy|alembic|psycopg|asyncpg|redis|elasticsearch|opensearch|boto3|portkey|openai|anthropic|langchain|llama|opentelemetry|jwt|pyjwt|python-jose|authlib|msal)", d)]
        out += [f"- `{path}`: " + ", ".join(f"`{d}`" for d in interesting or deps[:15])]
    out += ["", "## Backend signals (file hits)"]
    out += [f"- **{k}**: {len(v)} file(s) e.g. {', '.join(f'`{x}`' for x in v[:4])}" for k, v in sorted(r["python_signals"].items())]
    prefixes = [f"- {x}" for x in r["api_router_prefixes"]] or ["- none found"]
    out += ["", "## API router prefixes", *prefixes]
    out += ["", "## Frontend signals", *[f"- **{k}**: {', '.join(f'`{x}`' for x in v[:5])}" for k, v in sorted(r["frontend_signals"].items())]]
    m = r["migrations"]
    out += ["", "## Migrations", f"- alembic.ini: {m['alembic_ini'] or 'none'}; revision files: {m['revision_files']}"]
    out += ["", "## Infrastructure files"] + [f"- `{x['file']}`" + (f" ports: {x['published_ports']}" if x.get("published_ports") else "") for x in r["infra_files"]]
    out += ["", "## Environment variable NAMES referenced (values never read)", ", ".join(f"`{x}`" for x in r["env_var_names"]) or "none"]
    out += ["", "## Possible secrets committed (pattern -> files; VERIFY and rotate if real)"]
    out += [f"- **{k}**: {', '.join(f'`{x}`' for x in v)}" for k, v in r["possible_secrets"].items()] or ["- none matched"]
    out += ["", "## Decisions this report should drive (fill in)",
            "- [ ] React version vs CopilotKit V2 peer range (react ^18 || ^19) and zod >= 3.25",
            "- [ ] Build tool supports `moduleResolution: bundler` and package `exports` (Vite/webpack 5 yes; CRA needs care)",
            "- [ ] Existing auth: bearer token in JS (-> provider `headers`) or HttpOnly cookie (-> forward `cookie` or exchange)",
            "- [ ] FastAPI app factory location to call install_revamp(); existing /api/v2 prefix collisions",
            "- [ ] Migration tool (Alembic?) -> wrap database/migrations/*.sql as revisions",
            "- [ ] Existing Elastic client major version vs cluster major",
            "- [ ] Existing Portkey/Bedrock call path to reuse instead of a parallel client", ""]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", type=Path)
    ap.add_argument("--out", type=Path, default=Path("inventory"))
    args = ap.parse_args()
    if not args.repo.is_dir():
        print(f"not a directory: {args.repo}", file=sys.stderr)
        return 2
    report = inventory(args.repo.resolve())
    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (args.out / f"phase0-opsi-{stamp}.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    md = args.out / f"phase0-opsi-{stamp}.md"
    md.write_text(to_markdown(report), encoding="utf-8")
    print(f"wrote {md}")
    if report["possible_secrets"]:
        print("WARNING: secret-like strings found - review the 'Possible secrets' section before sharing the report")
    return 0


if __name__ == "__main__":
    sys.exit(main())
