#!/usr/bin/env python3
"""Fail fast when the product repository stops looking like one clean, owned codebase.

Checks the TRACKED files of a git repository (docs/repository-strategy.md, ADR-0020):
  submodules / embedded repos   .gitmodules or gitlink entries (mode 160000)
  stray third-party code        LICENSE/COPYING/NOTICE files outside the repo root and third_party/
  unregistered vendored files   files under third_party/ not covered by third_party/VENDORED.json
  build/runtime junk            node_modules/, .venv/, __pycache__/, real .env files, keys, dumps, parquet
  big files                     tracked files larger than --max-kb (default 1024) unless --allow-large
  unpinned JS dependencies      package.json without a lockfile next to it

  python3 scripts/repo/repo_hygiene.py [--repo-root .] [--max-kb 1024] [--allow-large 'docs/**/*.png']
Exit 0 clean, 1 problems found, 2 usage error. Standard library + git only.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath

LEGAL_NAMES = {"LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "COPYING", "NOTICE", "NOTICE.md", "NOTICE.txt"}
JUNK_DIRS = ("node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache")
JUNK_PATTERNS = ("*.pyc", "*.pem", "*.key", "*.p12", "*.pfx", "*.dump", "*.sqlite3", "*.parquet", "id_rsa*", "*.tfstate")
LOCKFILES = ("package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock")
THIRD_PARTY = "third_party"


def tracked(root: Path) -> list[tuple[str, str]]:
    """(mode, path) for every tracked entry."""
    out = subprocess.run(["git", "ls-files", "-s", "-z"], cwd=root, capture_output=True, check=True).stdout
    entries = []
    for raw in out.split(b"\0"):
        if raw:
            meta, _, path = raw.decode("utf-8", "surrogateescape").partition("\t")
            entries.append((meta.split()[0], path))
    return entries


def _is_env_file(name: str) -> bool:
    return (name == ".env" or name.startswith(".env.") or name.endswith(".env")) and not name.endswith(".example")


def check(root: Path, max_kb: int, allow_large: list[str]) -> list[str]:
    problems: list[str] = []
    entries = tracked(root)
    paths = [p for _, p in entries]
    if ".gitmodules" in paths:
        problems.append(".gitmodules is tracked - consume upstreams as packages or vendored files, not submodules")
    problems += [f"embedded repository (gitlink): {p}" for mode, p in entries if mode == "160000"]

    vendored_dests: list[str] = []
    registry = root / THIRD_PARTY / "VENDORED.json"
    if registry.exists():
        vendored_dests = [c["dest_path"].rstrip("/") for c in json.loads(registry.read_text("utf-8"))["components"]]

    path_set = set(paths)
    for path in paths:
        p = PurePosixPath(path)
        parts = p.parts
        if any(part in JUNK_DIRS for part in parts[:-1]) or any(fnmatch.fnmatch(p.name, pat) for pat in JUNK_PATTERNS):
            problems.append(f"build/runtime artefact or key material tracked: {path}")
        if _is_env_file(p.name):
            problems.append(f"environment file tracked (only *.example belongs in git): {path}")
        if p.name in LEGAL_NAMES and len(parts) > 1 and parts[0] != THIRD_PARTY:
            problems.append(f"licence/notice file outside third_party/ (copied upstream code?): {path}")
        if parts[0] == THIRD_PARTY and len(parts) > 1:
            covered = any(path == d or path.startswith(d + "/") for d in vendored_dests)
            legal = len(parts) == 3 and (p.name in LEGAL_NAMES or p.name.split(".")[0] in ("LICENSE", "NOTICE"))
            if not covered and not legal and path not in (f"{THIRD_PARTY}/VENDORED.json", f"{THIRD_PARTY}/README.md"):
                problems.append(f"file under third_party/ not registered in VENDORED.json: {path}")
        if p.name == "package.json" and parts[0] != THIRD_PARTY:
            folder = str(p.parent) if str(p.parent) != "." else ""
            if not any((f"{folder}/{lock}" if folder else lock) in path_set for lock in LOCKFILES):
                problems.append(f"package.json without a committed lockfile: {path}")
        full = root / path
        if full.is_file() and full.stat().st_size > max_kb * 1024 and not any(fnmatch.fnmatch(path, g) for g in allow_large):
            problems.append(f"large file ({full.stat().st_size // 1024} KiB > {max_kb} KiB): {path}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-root", type=Path, default=Path("."))
    ap.add_argument("--max-kb", type=int, default=1024)
    ap.add_argument("--allow-large", action="append", default=[], help="glob of tracked paths allowed to be large")
    args = ap.parse_args(argv)
    try:
        problems = check(args.repo_root, args.max_kb, args.allow_large)
    except (subprocess.CalledProcessError, FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for problem in problems:
        print(f"FAIL {problem}")
    print(f"repo hygiene: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
