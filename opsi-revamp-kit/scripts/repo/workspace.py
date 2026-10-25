#!/usr/bin/env python3
"""Manifest-driven developer workspace: every repository in its own folder, with its role enforced.

Roles (docs/repository-strategy.md):
  product    the ONE writable product repo (opsi-enterprise-revamp); extra remotes may be read-only
  readonly   e.g. the legacy Opsi baseline snapshot - push disabled on every remote
  upstream   pinned study copy of an open-source project (partial clone, detached at a tag) - push disabled
  reference  this kit or other docs repos - push disabled, updated by pulling only

Commands (standard library + git only):
  python3 scripts/repo/workspace.py init     --manifest infrastructure/repo/workspace.example.json
  python3 scripts/repo/workspace.py status   --manifest ...
  python3 scripts/repo/workspace.py verify   --manifest ...     # exit 1 on any policy violation
  python3 scripts/repo/workspace.py upstream-updates --manifest ...   # newer upstream tags than pinned

`init` only clones what is missing and (re)applies remote settings; it never deletes, resets or pushes.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

DISABLED_PUSH = "DISABLED-read-only-remote"
ROLES = ("product", "readonly", "upstream", "reference")
_CREDS_IN_URL = re.compile(r"://[^/@\s]+@")


class WorkspaceError(Exception):
    pass


@dataclass
class Remote:
    name: str
    url: str
    push: bool = False


@dataclass
class Repo:
    name: str
    dir: Path
    url: str
    role: str
    ref: str | None = None
    partial: bool = False
    branch: str | None = None
    extra_remotes: list[Remote] = field(default_factory=list)


def git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise WorkspaceError(f"git {' '.join(args)} failed: {result.stderr.strip()[:500]}")
    return result.stdout.strip()


def load_manifest(path: Path) -> list[Repo]:
    data = json.loads(path.read_text(encoding="utf-8"))
    root = Path(os.path.expanduser(data.get("root", "~/workspaces")))
    if not root.is_absolute():
        root = (path.parent / root).resolve()
    repos: list[Repo] = []
    names: set[str] = set()
    for item in data.get("repos", []):
        role = item.get("role")
        if role not in ROLES:
            raise WorkspaceError(f"{item.get('name')}: role must be one of {ROLES}")
        for url in [item.get("url", "")] + [r.get("url", "") for r in item.get("extra_remotes", [])]:
            if _CREDS_IN_URL.search(url):
                raise WorkspaceError(f"{item.get('name')}: credentials embedded in URL - use a credential helper")
        if item["name"] in names:
            raise WorkspaceError(f"duplicate repo name {item['name']}")
        names.add(item["name"])
        if role == "upstream" and not item.get("ref"):
            raise WorkspaceError(f"{item['name']}: upstream repos must pin a 'ref' (tag or commit)")
        repos.append(Repo(
            name=item["name"], dir=root / item["dir"], url=item["url"], role=role, ref=item.get("ref"),
            partial=bool(item.get("partial", role == "upstream")), branch=item.get("branch"),
            extra_remotes=[Remote(r["name"], r["url"], bool(r.get("push", False)))
                           for r in item.get("extra_remotes", [])],
        ))
    products = [r for r in repos if r.role == "product"]
    if len(products) > 1:
        raise WorkspaceError("only one product repository per workspace (keeps ownership unambiguous)")
    return repos


def _configure(repo: Repo) -> None:
    if repo.role != "product":
        git("remote", "set-url", "--push", "origin", DISABLED_PUSH, cwd=repo.dir)
    existing = git("remote", cwd=repo.dir).split()
    for remote in repo.extra_remotes:
        if remote.name not in existing:
            git("remote", "add", remote.name, remote.url, cwd=repo.dir)
        else:
            git("remote", "set-url", remote.name, remote.url, cwd=repo.dir)
        if not remote.push or repo.role != "product":
            git("remote", "set-url", "--push", remote.name, DISABLED_PUSH, cwd=repo.dir)
    git("config", "--local", "workspace.role", repo.role, cwd=repo.dir)


def init(repos: list[Repo], only: str | None = None) -> list[str]:
    actions = []
    for repo in repos:
        if only and repo.name != only:
            continue
        if not (repo.dir / ".git").exists():
            repo.dir.parent.mkdir(parents=True, exist_ok=True)
            args = ["clone"]
            if repo.partial:
                args += ["--filter=blob:none"]
            if repo.ref:
                args += ["--no-checkout"]
            git(*args, repo.url, str(repo.dir))
            if repo.ref:
                git("-c", "advice.detachedHead=false", "checkout", "--detach", repo.ref, cwd=repo.dir)
            elif repo.branch:
                git("checkout", repo.branch, cwd=repo.dir)
            actions.append(f"cloned {repo.name} -> {repo.dir}")
        _configure(repo)
        actions.append(f"configured {repo.name} ({repo.role})")
    return actions


@dataclass
class RepoStatus:
    repo: Repo
    exists: bool
    head: str = ""
    describe: str = ""
    dirty: bool = False
    push_urls: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


def inspect(repo: Repo, all_repos: list[Repo]) -> RepoStatus:
    st = RepoStatus(repo, (repo.dir / ".git").exists())
    if not st.exists:
        st.problems.append("missing (run init)")
        return st
    st.head = git("rev-parse", "HEAD", cwd=repo.dir, check=False)
    st.describe = git("describe", "--tags", "--always", cwd=repo.dir, check=False)
    st.dirty = bool(git("status", "--porcelain", cwd=repo.dir, check=False))
    for name in git("remote", cwd=repo.dir).split():
        url = git("remote", "get-url", name, cwd=repo.dir)
        push = git("remote", "get-url", "--push", name, cwd=repo.dir)
        st.push_urls[name] = push
        if _CREDS_IN_URL.search(url) or _CREDS_IN_URL.search(push):
            st.problems.append(f"remote {name} has credentials in its URL")
        push_enabled = not push.startswith("DISABLED")
        allowed = repo.role == "product" and (name == "origin" or any(
            r.name == name and r.push for r in repo.extra_remotes))
        if push_enabled and not allowed:
            st.problems.append(f"remote {name} must be read-only (push URL is enabled)")
    if repo.role == "product":
        origin = git("remote", "get-url", "origin", cwd=repo.dir, check=False)
        protected = {r.url for r in all_repos if r.role in ("readonly", "upstream")}
        protected |= {x.url for x in repo.extra_remotes if not x.push}
        if origin in protected:
            st.problems.append("product origin points at a read-only/legacy/upstream URL")
    if repo.role == "upstream" and repo.ref:
        wanted = git("rev-parse", f"{repo.ref}^{{commit}}", cwd=repo.dir, check=False)
        if wanted and st.head != wanted:
            st.problems.append(f"HEAD is not at pinned ref {repo.ref}")
    if repo.role in ("readonly", "upstream", "reference") and st.dirty:
        st.problems.append("has local changes (read-only copies must stay clean)")
    return st


def upstream_updates(repo: Repo) -> list[str]:
    git("fetch", "--tags", "--quiet", "origin", cwd=repo.dir)
    pinned = git("rev-parse", f"{repo.ref}^{{commit}}", cwd=repo.dir)
    pinned_date = int(git("log", "-1", "--format=%ct", pinned, cwd=repo.dir))
    # newer = descends from the pinned commit (same line) or was created later (e.g. a newer release branch)
    descendants = set(git("tag", "--contains", pinned, cwd=repo.dir).split())
    newer = []
    for line in git("for-each-ref", "--sort=-creatordate",
                    "--format=%(refname:short) %(creatordate:unix) %(objectname) %(*objectname)",
                    "refs/tags", cwd=repo.dir).splitlines()[:200]:
        tag, ts, obj, *peeled = line.split()
        if (peeled[0] if peeled else obj) == pinned:
            continue
        if tag in descendants or (ts.isdigit() and int(ts) > pinned_date):
            newer.append(tag)
    return newer


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["init", "status", "verify", "upstream-updates"])
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--only", help="limit init to one repo name")
    args = ap.parse_args(argv)
    try:
        repos = load_manifest(args.manifest)
        if args.command == "init":
            for line in init(repos, args.only):
                print(line)
            return 0
        if args.command == "upstream-updates":
            for repo in repos:
                if repo.role == "upstream" and (repo.dir / ".git").exists():
                    newer = upstream_updates(repo)
                    print(f"{repo.name}: pinned {repo.ref}; newer tags: {', '.join(newer[:10]) or 'none'}")
            return 0
        statuses = [inspect(r, repos) for r in repos]
        bad = 0
        for st in statuses:
            flag = "OK  " if not st.problems else "FAIL"
            print(f"{flag} {st.repo.name:<28} {st.repo.role:<9} {st.describe or '-':<28} "
                  f"{'dirty' if st.dirty else 'clean':<5} {st.repo.dir}")
            for problem in st.problems:
                print(f"       - {problem}")
            bad += bool(st.problems)
        if args.command == "verify":
            print(f"workspace verify: {bad} repo(s) with problems")
            return 1 if bad else 0
        return 0
    except WorkspaceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
