"""The API's redaction module must stay identical to the collectors' canonical copy."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_redaction_copies_are_in_sync():
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / "sync_redaction.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
