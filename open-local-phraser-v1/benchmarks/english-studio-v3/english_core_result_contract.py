"""Shared gate for Python consumers of English Core model-result artifacts."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VALIDATOR = HERE / "validate-english-core-run.py"


def validate_result(path: Path | str, *, promotion: bool = False, compat_legacy_v0: bool = False) -> dict:
    command = [sys.executable, str(VALIDATOR), str(Path(path).resolve())]
    if promotion:
        command.append("--promotion")
    if compat_legacy_v0:
        if promotion:
            raise ValueError("legacy result compatibility cannot be used for promotion")
        command.append("--compat-legacy-v0")
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode:
        detail = completed.stdout.strip() or completed.stderr.strip() or f"exit {completed.returncode}"
        raise ValueError(f"English Core result validation failed:\n{detail}")
    return json.loads(completed.stdout)
