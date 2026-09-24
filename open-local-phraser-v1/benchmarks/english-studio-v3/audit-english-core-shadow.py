"""Compatibility wrapper for the canonical English Core shadow audit.

The benchmark intentionally keeps exactly one audit implementation:
`audit-english-core-shadow.mjs`.

This Python entry point remains only for callers that previously invoked the
Python script. It delegates to the canonical JS audit so structural rules cannot
drift between two implementations.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CANONICAL = HERE / "audit-english-core-shadow.mjs"


def main() -> None:
    if len(sys.argv) > 2:
        raise SystemExit("Usage: python audit-english-core-shadow.py [english-core-shadow.seed.json]")

    cmd = ["node", str(CANONICAL)]
    if len(sys.argv) == 2:
        # The canonical audit currently audits the repository seed only. Reject a
        # different path instead of pretending the argument was honored.
        requested = Path(sys.argv[1]).resolve()
        canonical_seed = (HERE / "english-core-shadow.seed.json").resolve()
        if requested != canonical_seed:
            raise SystemExit(
                "The compatibility wrapper only supports the canonical repository seed. "
                "Run/copy the canonical audit deliberately if auditing another dataset."
            )

    completed = subprocess.run(cmd, cwd=HERE)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
