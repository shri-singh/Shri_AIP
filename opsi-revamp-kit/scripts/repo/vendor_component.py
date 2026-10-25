#!/usr/bin/env python3
"""Selective vendoring with provenance: copy ONLY the upstream files you need into third_party/.

Every vendored component is recorded in third_party/VENDORED.json with upstream URL, ref, commit,
source path, destination, SPDX licence, reason, approver and a SHA-256 per file. The licence file
nearest to the source path (and the upstream NOTICE, if any) is copied next to it.

    python3 scripts/repo/vendor_component.py add --upstream ~/workspaces/upstream/OpenMetadata \
        --project openmetadata --id om-db-connection-schemas \
        --source openmetadata-spec/src/main/resources/json/schema/entity/services/connections/database \
        --dest third_party/openmetadata/schema/connections/database \
        --spdx Apache-2.0 --reason "connector settings forms (@rjsf)" --approved-by "arch-review ARCH-12"
    python3 scripts/repo/vendor_component.py verify                 # CI: exit 1 on undocumented edits / missing licence
    python3 scripts/repo/vendor_component.py mark-modified --id om-db-connection-schemas --note "added x-opsi-ui hints"
    python3 scripts/repo/vendor_component.py diff-upstream --id om-db-connection-schemas --upstream <dir> --to 2.0.7-release
    python3 scripts/repo/vendor_component.py update --id om-db-connection-schemas --upstream <dir checked out at new ref>
    python3 scripts/repo/vendor_component.py notices --out THIRD_PARTY_NOTICES.md
    python3 scripts/repo/vendor_component.py list

Run from the product repository root (or pass --repo-root). Standard library + git only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PERMISSIVE = {"Apache-2.0", "MIT", "BSD-2-Clause", "BSD-3-Clause", "ISC", "0BSD", "CC0-1.0", "Unlicense", "Zlib"}
# Paths inside upstream repos that carry a different, non-permissive licence (verified 2026-10-24).
RESTRICTED = {
    "openmetadata": [("ingestion/", "Collate Community License Agreement 1.0 (see ADR-0018)")],
}
LICENSE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "LICENCE")
NOTICE_NAMES = ("NOTICE", "NOTICE.md", "NOTICE.txt")
_CREDS = re.compile(r"://[^/@\s]+@")


class VendorError(Exception):
    pass


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise VendorError(f"git {' '.join(args)} failed in {cwd}: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(p for p in path.rglob("*") if p.is_file() and ".git" not in p.parts)


class Registry:
    def __init__(self, repo_root: Path, third_party: str = "third_party") -> None:
        self.root = repo_root.resolve()
        self.dir = self.root / third_party
        self.path = self.dir / "VENDORED.json"
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self.data = {"version": 1, "components": []}

    @property
    def components(self) -> list[dict]:
        return self.data["components"]

    def get(self, cid: str) -> dict:
        for c in self.components:
            if c["id"] == cid:
                return c
        raise VendorError(f"unknown component id {cid!r}")

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.components.sort(key=lambda c: c["id"])
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def hashes(self, dest: Path) -> dict[str, str]:
        base = dest if dest.is_dir() else dest.parent
        return {p.relative_to(base).as_posix(): _sha256(p) for p in _files(dest)}


def _upstream_facts(upstream: Path, source: str) -> dict:
    if not (upstream / ".git").exists():
        raise VendorError(f"{upstream} is not a git checkout")
    if not (upstream / source).exists():
        raise VendorError(f"source path {source} does not exist in {upstream}")
    if _git(upstream, "status", "--porcelain", "--", source):
        raise VendorError(f"upstream has local changes under {source}; vendor only pristine upstream content")
    url = _git(upstream, "remote", "get-url", "origin")
    if _CREDS.search(url):
        raise VendorError("upstream remote URL contains credentials")
    try:
        ref = _git(upstream, "describe", "--tags", "--exact-match")
    except VendorError:
        ref = _git(upstream, "describe", "--tags", "--always")
    return {"upstream_url": url, "upstream_ref": ref, "upstream_commit": _git(upstream, "rev-parse", "HEAD")}


def _nearest(upstream: Path, source: str, names: tuple[str, ...]) -> Path | None:
    current = (upstream / source)
    current = current if current.is_dir() else current.parent
    while True:
        for name in names:
            if (current / name).is_file():
                return current / name
        if current.resolve() == upstream.resolve():
            return None
        current = current.parent


def _copy(src: Path, dest: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git"))
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def _install_legal(reg: Registry, project: str, cid: str, src_file: Path | None, kind: str) -> str | None:
    if src_file is None:
        return None
    project_dir = reg.dir / project
    project_dir.mkdir(parents=True, exist_ok=True)
    target = project_dir / kind
    content = src_file.read_bytes()
    if target.exists() and target.read_bytes() != content:
        target = project_dir / f"{kind}.{re.sub(r'[^A-Za-z0-9_.-]', '-', cid)}"
    target.write_bytes(content)
    return target.relative_to(reg.root).as_posix()


def cmd_add(reg: Registry, a: argparse.Namespace, replace: bool = False) -> dict:
    upstream = Path(a.upstream).resolve()
    facts = _upstream_facts(upstream, a.source)
    source_dir = a.source.replace("\\", "/").strip("/") + "/"
    for prefix, why in RESTRICTED.get(a.project, []):
        if source_dir.startswith(prefix) and not (a.allow_restricted and a.approval):
            raise VendorError(f"{a.source} is under {prefix} ({why}); needs --allow-restricted --approval <ticket>")
    if a.spdx not in PERMISSIVE and not (a.allow_license and a.approval):
        raise VendorError(f"licence {a.spdx} is not on the permissive list; needs --allow-license --approval <ticket>")
    dest = (reg.root / a.dest).resolve()
    if reg.dir.resolve() not in dest.parents:
        raise VendorError(f"destination must be inside {reg.dir.relative_to(reg.root)}/")
    if not replace and any(c["id"] == a.id for c in reg.components):
        raise VendorError(f"component id {a.id} already exists (use update)")
    if dest.exists():
        if not replace:
            raise VendorError(f"{a.dest} already exists")
        shutil.rmtree(dest) if dest.is_dir() else dest.unlink()
    _copy(upstream / a.source, dest)
    license_file = _install_legal(reg, a.project, a.id, _nearest(upstream, a.source, LICENSE_NAMES), "LICENSE")
    if license_file is None:
        raise VendorError("no LICENSE file found between the source path and the upstream root - cannot vendor")
    notice_file = _install_legal(reg, a.project, a.id, _nearest(upstream, a.source, NOTICE_NAMES), "NOTICE")
    entry = {
        "id": a.id, "project": a.project, **facts, "source_path": a.source.replace("\\", "/"),
        "dest_path": dest.relative_to(reg.root).as_posix(), "spdx": a.spdx, "license_file": license_file,
        "notice_file": notice_file, "reason": a.reason, "approved_by": a.approved_by, "approval": a.approval,
        "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "modified": False,
        "modification_note": None, "files": reg.hashes(dest),
    }
    reg.data["components"] = [c for c in reg.components if c["id"] != a.id] + [entry]
    reg.save()
    return entry


def cmd_verify(reg: Registry) -> list[str]:
    problems = []
    for c in reg.components:
        dest = reg.root / c["dest_path"]
        if not dest.exists():
            problems.append(f"{c['id']}: destination {c['dest_path']} missing")
            continue
        if not (reg.root / c["license_file"]).exists():
            problems.append(f"{c['id']}: licence file {c['license_file']} missing")
        actual = reg.hashes(dest)
        recorded = c["files"]
        for rel in sorted(set(recorded) - set(actual)):
            problems.append(f"{c['id']}: file deleted: {rel}")
        for rel in sorted(set(actual) - set(recorded)):
            problems.append(f"{c['id']}: untracked file added: {rel}")
        for rel in sorted(set(actual) & set(recorded)):
            if actual[rel] != recorded[rel]:
                problems.append(f"{c['id']}: {rel} changed without mark-modified (document local edits)")
    return problems


def cmd_mark_modified(reg: Registry, cid: str, note: str) -> None:
    if not note.strip():
        raise VendorError("a modification note is required (it becomes part of the notices)")
    c = reg.get(cid)
    c["files"] = reg.hashes(reg.root / c["dest_path"])
    c["modified"] = True
    c["modification_note"] = note
    c["modified_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reg.save()


def cmd_diff_upstream(reg: Registry, cid: str, upstream: Path, to: str) -> str:
    c = reg.get(cid)
    try:
        _git(upstream, "fetch", "--tags", "--quiet", "origin")
    except VendorError as exc:  # offline / mirror unreachable: compare against what is already fetched
        print(f"warning: fetch failed, using local refs only ({exc})", file=sys.stderr)
    return _git(upstream, "diff", "--stat", c["upstream_commit"], to, "--", c["source_path"]) or "no upstream changes"


def cmd_notices(reg: Registry) -> str:
    lines = ["# Third-party notices", "", "Generated by scripts/repo/vendor_component.py from third_party/VENDORED.json.",
             "Packages installed from npm/PyPI are listed by scripts/license_scan.sh, not here.", ""]
    seen_licenses: set[str] = set()
    for c in sorted(reg.components, key=lambda x: (x["project"], x["id"])):
        lines += [f"## {c['project']} - {c['id']}",
                  f"- Upstream: {c['upstream_url']} @ {c['upstream_ref']} ({c['upstream_commit'][:12]})",
                  f"- Source path: `{c['source_path']}` -> `{c['dest_path']}`",
                  f"- Licence: {c['spdx']} (`{c['license_file']}`)"]
        if c.get("modified"):
            lines.append(f"- **Modified by Opsi**: {c['modification_note']} ({c.get('modified_at', '')})")
        lines.append("")
        for legal in (c["license_file"], c.get("notice_file")):
            if legal and legal not in seen_licenses and (reg.root / legal).exists():
                seen_licenses.add(legal)
                text = (reg.root / legal).read_text(encoding="utf-8", errors="replace")
                lines += [f"<details><summary>{legal}</summary>", "", "```", text.strip(), "```", "", "</details>", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("add", "update"):
        p = sub.add_parser(name)
        p.add_argument("--upstream", required=True, help="checkout of the upstream repo at the ref to vendor")
        p.add_argument("--id", required=True)
        if name == "add":
            p.add_argument("--project", required=True)
            p.add_argument("--source", required=True, help="path inside the upstream repo")
            p.add_argument("--dest", required=True, help="path inside third_party/")
            p.add_argument("--spdx", required=True)
            p.add_argument("--reason", required=True)
            p.add_argument("--approved-by", required=True)
            p.add_argument("--allow-restricted", action="store_true")
            p.add_argument("--allow-license", action="store_true")
            p.add_argument("--approval", default=None, help="ticket id for restricted paths / non-permissive licences")
        else:
            p.add_argument("--force", action="store_true", help="overwrite documented local modifications")
    sub.add_parser("verify")
    sub.add_parser("list")
    m = sub.add_parser("mark-modified")
    m.add_argument("--id", required=True)
    m.add_argument("--note", required=True)
    d = sub.add_parser("diff-upstream")
    d.add_argument("--id", required=True)
    d.add_argument("--upstream", required=True)
    d.add_argument("--to", required=True)
    n = sub.add_parser("notices")
    n.add_argument("--out", default="THIRD_PARTY_NOTICES.md")
    a = ap.parse_args(argv)
    reg = Registry(Path(a.repo_root))
    try:
        if a.cmd == "add":
            entry = cmd_add(reg, a)
            print(f"vendored {entry['id']}: {len(entry['files'])} file(s) from {entry['upstream_ref']} "
                  f"({entry['upstream_commit'][:12]}) -> {entry['dest_path']}")
        elif a.cmd == "update":
            old = reg.get(a.id)
            if old.get("modified") and not a.force:
                raise VendorError(f"{a.id} has documented local modifications; re-apply them after update (--force)")
            ns = argparse.Namespace(upstream=a.upstream, project=old["project"], id=a.id, source=old["source_path"],
                                    dest=old["dest_path"], spdx=old["spdx"], reason=old["reason"],
                                    approved_by=old["approved_by"], approval=old.get("approval"),
                                    allow_restricted=bool(old.get("approval")), allow_license=bool(old.get("approval")))
            entry = cmd_add(reg, ns, replace=True)
            print(f"updated {a.id}: {old['upstream_ref']} -> {entry['upstream_ref']}")
        elif a.cmd == "verify":
            problems = cmd_verify(reg)
            for p in problems:
                print(f"FAIL {p}")
            print(f"vendored components: {len(reg.components)}, problems: {len(problems)}")
            return 1 if problems else 0
        elif a.cmd == "mark-modified":
            cmd_mark_modified(reg, a.id, a.note)
            print(f"recorded local modification of {a.id}")
        elif a.cmd == "diff-upstream":
            print(cmd_diff_upstream(reg, a.id, Path(a.upstream), a.to))
        elif a.cmd == "notices":
            Path(a.out).write_text(cmd_notices(reg), encoding="utf-8")
            print(f"wrote {a.out}")
        elif a.cmd == "list":
            for c in reg.components:
                print(f"{c['id']:<32} {c['project']:<14} {c['upstream_ref']:<18} {c['spdx']:<12} "
                      f"{'MODIFIED ' if c.get('modified') else ''}{c['dest_path']}")
        return 0
    except VendorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
