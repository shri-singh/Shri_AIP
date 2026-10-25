#!/usr/bin/env python3
"""Redact a captured vendor response (JSON or text) before using it as a test fixture.

    python3 tools/redact_file.py capture.json > services/ingestion/fixtures/new_fixture.json
    python3 tools/redact_file.py --level standard app.log > app.redacted.log

Uses the same rules as the collectors (services/ingestion/opsi_ingest/redaction.py). Regexes are a
safety net: ALWAYS read the output before committing it, and replace real hostnames, ids and
customer names by hand.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ingestion"))
from opsi_ingest.redaction import Redactor  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--level", choices=["strict", "standard"], default="strict")
    args = ap.parse_args()
    redactor = Redactor(args.level)
    text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        result = redactor.redact_text(text)
        sys.stdout.write(result.text)
        print(f"\n# redactions: {result.hits}", file=sys.stderr)
        return 0
    redacted, hits = redactor.redact_value(data)
    json.dump(redacted, sys.stdout, indent=2, ensure_ascii=False)
    print(f"\n# redactions: {hits} - now review by hand (hostnames, ids, names are NOT auto-removed)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
