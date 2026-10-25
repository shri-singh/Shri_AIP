#!/usr/bin/env python3
"""Copy the canonical redaction module (ingestion) into the API package.

Usage: python scripts/sync_redaction.py [--check]
--check exits 1 when the copies differ (used by tests and CI).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "services/ingestion/opsi_ingest/redaction.py"
TARGET = ROOT / "apps/opsi-api/app/modules/_shared/redaction.py"
HEADER = (
    "# Copy of services/ingestion/opsi_ingest/redaction.py for the API process.\n"
    "# Kept byte-identical below the marker line; tests/api/test_redaction_sync.py fails if they drift.\n"
    "# Edit the ingestion copy first, then run: python scripts/sync_redaction.py\n"
    "# --- BEGIN SHARED REDACTION (do not edit here) ---\n"
)


def expected() -> str:
    return HEADER + SOURCE.read_text(encoding="utf-8")


def main() -> int:
    if "--check" in sys.argv:
        same = TARGET.exists() and TARGET.read_text(encoding="utf-8") == expected()
        print("redaction copies in sync" if same else "redaction copies DIFFER - run scripts/sync_redaction.py")
        return 0 if same else 1
    TARGET.write_text(expected(), encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
