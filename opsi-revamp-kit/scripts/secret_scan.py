#!/usr/bin/env python3
"""Scan files tracked by git (or a directory) for secret-looking strings. Prints file:line:pattern, never the value.

    python3 scripts/secret_scan.py            # tracked files of the current repo
    python3 scripts/secret_scan.py some/dir   # any directory (e.g. a support bundle before sharing it)
Exit 1 when anything matches. Prefer gitleaks/trufflehog if your company provides them; this is the fallback.
Allowlist a deliberate test value by adding `# secret-scan: allow` on the same line.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PATTERNS = {
    "aws_access_key_id": re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    "aws_secret_assignment": re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}"),
    "private_key_block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "dynatrace_token": re.compile(r"\bdt0[a-z]\d{2}\.[A-Za-z0-9]{24}\.[A-Za-z0-9]{64}\b"),
    "github_token": re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b"),
    "slack_token": re.compile(r"\bxox[abpors]-[A-Za-z0-9-]{20,}"),
    "portkey_key": re.compile(r"\bpk-[A-Za-z0-9]{30,}"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"),
    "password_literal": re.compile(r"(?i)\b(password|passwd|client_secret|api_key|secret_key)\s*[:=]\s*['\"][^'\"\s${}<>]{8,}['\"]"),
    "url_with_password": re.compile(r"\b[a-z][a-z0-9+.-]*://[^/\s:@'\"]+:[^/\s@'\"$<{]{4,}@"),
}
SKIP_SUFFIXES = (".png", ".jpg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".parquet", ".lock", ".woff", ".woff2", ".pyc", ".exe")
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv", "dist"}


def files(target: Path | None) -> list[Path]:
    if target:
        return [p for p in target.rglob("*") if p.is_file() and not SKIP_DIRS.intersection(p.parts)]
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True).stdout.decode().split("\0")
    return [Path(p) for p in out if p]


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    hits = 0
    for path in files(target):
        if path.suffix.lower() in SKIP_SUFFIXES or not path.exists() or path.stat().st_size > 2_000_000:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            if "secret-scan: allow" in line:
                continue
            for name, rx in PATTERNS.items():
                if rx.search(line):
                    print(f"{path}:{number}: {name}")
                    hits += 1
    print(f"secret scan: {hits} finding(s)")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
