#!/usr/bin/env python3
"""Single entry point for a pinned Kaggle candidate run.

The candidate roster decides the runtime. This dispatcher contains no model
selection logic and does not modify prompts, quantization, or runtime identity.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROSTER = HERE / "kaggle-candidate-roster.json"
VLLM = HERE / "run-kaggle-vllm-candidate.py"
PRISM = HERE / "run-kaggle-prism-candidate.py"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate_id")
    ap.add_argument("--stage", choices=["smoke", "full", "word-studio", "transform"], required=True)
    ap.add_argument("--benchmark-revision", required=True)
    ap.add_argument("--decode", choices=["normal", "mtp", "qwen3_next_mtp"], default="normal")
    ap.add_argument("--speculative-tokens", type=int, default=1)
    ap.add_argument("--runtime-artifact-id", default=None)
    ap.add_argument("--results-dir", type=Path, default=Path("/kaggle/working/results"))
    args = ap.parse_args()

    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in roster["candidates"]}
    c = by_id.get(args.candidate_id)
    if c is None:
        raise SystemExit(f"unknown candidate {args.candidate_id}; allowed: {', '.join(sorted(by_id))}")

    runtime = c.get("runtime")
    if runtime == "vllm":
        cmd = [
            sys.executable, str(VLLM), args.candidate_id,
            "--stage", args.stage,
            "--decode", args.decode,
            "--speculative-tokens", str(args.speculative_tokens),
            "--benchmark-revision", args.benchmark_revision,
            "--results-dir", str(args.results_dir),
        ]
    elif runtime == "llama.cpp":
        if args.decode != "normal":
            raise SystemExit("this pinned Prism/Bonsai path has no validated speculative decode; use --decode normal")
        cmd = [
            sys.executable, str(PRISM), args.candidate_id,
            "--stage", args.stage,
            "--benchmark-revision", args.benchmark_revision,
            "--results-dir", str(args.results_dir),
        ]
        if args.runtime_artifact_id:
            cmd += ["--runtime-artifact-id", args.runtime_artifact_id]
    else:
        raise SystemExit(f"candidate {args.candidate_id} has unsupported canonical runtime {runtime!r}")

    print("+", " ".join(cmd), flush=True)
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
