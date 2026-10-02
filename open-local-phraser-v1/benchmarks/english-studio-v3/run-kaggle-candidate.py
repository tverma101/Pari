#!/usr/bin/env python3
"""Single entry point for a pinned Kaggle candidate run.

The candidate roster decides the runtime. This dispatcher contains no model
selection logic and does not modify prompts, quantization, or runtime identity.
Product task files are deterministically rebuilt when needed so execution agents
do not need to remember separate build steps.
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
BUILD_STRENGTH = HERE / "build-word-studio-strength-suite.py"
BUILD_TRANSFORM = HERE / "build-word-studio-transform-suite.py"
SYNTHETIC_SEED = HERE / "word-studio-synthetic.seed.json"
STRENGTH_TASKS = HERE / "word-studio-strength.jsonl"
TRANSFORM_TASKS = HERE / "word-studio-transform.jsonl"


def jsonl_count(path: Path) -> int:
    if not path.is_file():
        return 0
    ids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        task_id = row.get("id")
        if not task_id:
            raise SystemExit(f"generated task without id in {path}")
        ids.append(str(task_id))
    if len(ids) != len(set(ids)):
        raise SystemExit(f"generated task file has duplicate ids: {path}")
    return len(ids)


def ensure_product_tasks(stage: str) -> None:
    if stage == "word-studio":
        cmd = [
            sys.executable, str(BUILD_STRENGTH),
            "--synthetic-seed", str(SYNTHETIC_SEED),
        ]
        expected = 112
        output = STRENGTH_TASKS
    elif stage == "transform":
        cmd = [sys.executable, str(BUILD_TRANSFORM)]
        expected = 100
        output = TRANSFORM_TASKS
    else:
        return

    print("+", " ".join(cmd), flush=True)
    build = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if build.stdout:
        print(build.stdout, end="" if build.stdout.endswith("\n") else "\n", flush=True)
    if build.returncode != 0:
        raise SystemExit(f"product task build failed before GPU inference; rc={build.returncode}")
    actual = jsonl_count(output)
    if actual != expected:
        raise SystemExit(f"product task build count mismatch for {output.name}: expected {expected}, got {actual}")
    print(f"verified product task build: {output.name} cases={actual}", flush=True)


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

    ensure_product_tasks(args.stage)

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
