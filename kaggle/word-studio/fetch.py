#!/usr/bin/env python3
"""Download a finished Word Studio v2 kernel run into the repository (#86).

    python3 kaggle/word-studio/fetch.py --run-id 2026-10-16-screen-abc1234

Copies ``runs/<run-id>/`` from the kernel output into
``bench/word-studio/v2/runs/<run-id>/`` with the kernel log, and refuses to
overwrite a run that is already there.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
RUNS = REPO_ROOT / "bench" / "word-studio" / "v2" / "runs"
sys.path.insert(0, str(HERE))
from launch import KERNEL_SLUG, kaggle_username  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--kernel", help="owner/slug (default: <your username>/" + KERNEL_SLUG + ")")
    args = parser.parse_args(argv)
    kernel = args.kernel or f"{kaggle_username()}/{KERNEL_SLUG}"
    target = RUNS / args.run_id
    if target.exists():
        raise SystemExit(f"{target} already exists; never overwrite evidence")
    status = subprocess.run(["kaggle", "kernels", "status", kernel], capture_output=True, text=True, check=True)
    print(status.stdout.strip())
    if not any(word in status.stdout.lower() for word in ("complete", "error", "cancel")):
        print("kernel is still running; try again later", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="pari-kaggle-output-") as tmp:
        subprocess.run(["kaggle", "kernels", "output", kernel, "-p", tmp], check=True)
        source = Path(tmp) / "runs" / args.run_id
        if not source.is_dir():
            found = sorted(p.name for p in (Path(tmp) / "runs").glob("*")) if (Path(tmp) / "runs").exists() else []
            raise SystemExit(f"run {args.run_id} not in the kernel output (found: {found})")
        shutil.copytree(source, target)
        for log in Path(tmp).glob("*.log"):
            shutil.copy2(log, target / "kaggle-kernel.log")
    receipt = {
        "kernel": kernel,
        "status": status.stdout.strip(),
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (target / "fetch.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"copied to {target.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
