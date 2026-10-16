#!/usr/bin/env python3
"""Push the Word Studio v2 candidate kernel to Kaggle 2xT4 (#86).

    python3 kaggle/word-studio/launch.py --set screen \
        --candidates qwen35-2b,qwen35-4b,minicpm5-2b,phi4-mini-instruct,smollm3-3b,control-missing-revision

The kernel clones this repository at one commit, so that commit must already be
on GitHub. ``--dry-run`` writes the kernel folder without pushing. This uses
your Kaggle account and GPU quota; run it only when you mean to.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
CANDIDATE_FILES = (REPO_ROOT / "bench" / "candidates.json", REPO_ROOT / "bench" / "word-studio" / "v2" / "controls.json")
REPO_URL = "https://github.com/tverma101/Pari.git"
KERNEL_SLUG = "pari-word-studio-v2"
PIP = ["transformers==5.18.0", "accelerate==1.15.0"]
CONFIG_LINE = "CONFIG = {}  # filled in by launch.py"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()


def known_candidates() -> set[str]:
    ids: set[str] = set()
    for path in CANDIDATE_FILES:
        ids.update(c["candidate_id"] for c in json.loads(path.read_text(encoding="utf-8"))["candidates"])
    return ids


def kaggle_username() -> str:
    out = subprocess.run(["kaggle", "config", "view"], capture_output=True, text=True, check=True).stdout
    match = re.search(r"^- username: (\S+)", out, re.M)
    if not match:
        raise SystemExit("could not read the Kaggle username; pass --username")
    return match.group(1)


def build_kernel(folder: Path, config: dict, username: str) -> Path:
    source = (HERE / "kernel.py").read_text(encoding="utf-8")
    if source.count(CONFIG_LINE) != 1:
        raise SystemExit("kernel.py must contain the CONFIG placeholder exactly once")
    filled = source.replace(CONFIG_LINE, "CONFIG = json.loads(" + repr(json.dumps(config, sort_keys=True)) + ")")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "kernel.py").write_text(filled, encoding="utf-8")
    metadata = {
        "id": f"{username}/{KERNEL_SLUG}",
        "title": "Pari Word Studio v2",
        "code_file": "kernel.py",
        "language": "python",
        "kernel_type": "script",
        "is_private": True,
        "enable_gpu": True,
        "enable_tpu": False,
        "enable_internet": True,
        "machine_shape": "NvidiaTeslaT4",
        "dataset_sources": [],
        "competition_sources": [],
        "kernel_sources": [],
        "model_sources": [],
    }
    (folder / "kernel-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return folder


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", choices=["screen", "full"], required=True)
    parser.add_argument("--candidates", required=True, help="comma-separated candidate ids")
    parser.add_argument("--ref", default="HEAD", help="commit to run; it must be pushed to GitHub")
    parser.add_argument("--limit", type=int, help="first N tasks per candidate (smoke test only)")
    parser.add_argument("--timeout-s", type=int, default=7200, help="per-candidate wall-clock limit")
    parser.add_argument("--username", help="Kaggle username (default: from kaggle config view)")
    parser.add_argument("--folder", type=Path, help="where to write the kernel folder")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    candidates = [c.strip() for c in args.candidates.split(",") if c.strip()]
    unknown = sorted(set(candidates) - known_candidates())
    if unknown:
        raise SystemExit(f"unknown candidates: {unknown}")
    sha = git("rev-parse", args.ref)
    git("fetch", "--quiet", "origin")
    if not git("branch", "-r", "--contains", sha):
        raise SystemExit(f"{sha} is not on GitHub yet; push it first so the kernel can clone it")
    run_id = f"{date.today().isoformat()}-{args.set}-{sha[:7]}" + (f"-limit{args.limit}" if args.limit else "")
    config = {
        "run_id": run_id,
        "repo_url": REPO_URL,
        "git_sha": sha,
        "task_set": args.set,
        "candidates": candidates,
        "pip": PIP,
        "per_candidate_timeout_s": args.timeout_s,
        "limit": args.limit,
    }
    username = args.username or kaggle_username()
    folder = args.folder or Path(tempfile.mkdtemp(prefix=f"pari-kaggle-{run_id}-"))
    build_kernel(folder, config, username)
    print(json.dumps({"run_id": run_id, "kernel": f"{username}/{KERNEL_SLUG}", "folder": str(folder)}, indent=2))
    if args.dry_run:
        return 0
    subprocess.run(["kaggle", "kernels", "push", "-p", str(folder)], check=True)
    print(f"pushed. Check: kaggle kernels status {username}/{KERNEL_SLUG}")
    print(f"then:  python3 kaggle/word-studio/fetch.py --run-id {run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
