#!/usr/bin/env python3
"""Mechanical Kaggle runner for pinned vLLM roster candidates.

The wrapper chooses nothing except a predeclared batch fallback on CUDA OOM. It
preserves every attempt and never mutates model identity or benchmark prompts.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from kaggle_failure_taxonomy import classify

HERE = Path(__file__).resolve().parent
ROSTER = HERE / "kaggle-candidate-roster.json"
RUNNER = HERE / "run-english-core-vllm.py"
DEFAULT_TASKS = HERE / "english-core-fixed-screen.jsonl"
BATCH_LADDER = (32, 16, 8, 4, 1)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate_id")
    ap.add_argument("--stage", choices=["smoke", "full"], required=True)
    ap.add_argument("--benchmark-revision", required=True)
    ap.add_argument("--preflight", type=Path, default=Path("/kaggle/working/results/preflight.json"))
    ap.add_argument("--results-dir", type=Path, default=Path("/kaggle/working/results"))
    ap.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    ap.add_argument("--max-model-len", type=int, default=8192)
    args = ap.parse_args()

    if not args.preflight.is_file():
        raise SystemExit("missing Kaggle preflight artifact; run kaggle-preflight.py first")
    preflight = load_json(args.preflight)
    if not preflight.get("promotionEligibleEnvironment"):
        raise SystemExit("preflight is not a qualified real Kaggle T4x2 environment")

    roster = load_json(ROSTER)
    by_id = {row["id"]: row for row in roster["candidates"]}
    if args.candidate_id not in by_id:
        raise SystemExit(f"unknown candidate {args.candidate_id}; allowed: {', '.join(sorted(by_id))}")
    c = by_id[args.candidate_id]
    if c.get("runtime") != "vllm":
        raise SystemExit(f"candidate {args.candidate_id} uses {c.get('runtime')}, not vLLM; use its pinned vendor runtime path")

    try:
        import vllm  # noqa: F401
    except Exception as exc:
        raise SystemExit(f"vLLM prebuilt is not importable: {type(exc).__name__}: {exc}; do not compile fallback") from exc

    args.results_dir.mkdir(parents=True, exist_ok=True)
    candidate_dir = args.results_dir / args.candidate_id / args.stage
    candidate_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "schemaVersion": 1,
        "candidate": c,
        "stage": args.stage,
        "benchmarkRevision": args.benchmark_revision,
        "batchLadder": list(BATCH_LADDER),
        "attempts": [],
        "status": "running",
    }
    summary_path = candidate_dir / "summary.json"

    stable_result: str | None = None
    for attempt_no, batch in enumerate(BATCH_LADDER, start=1):
        stem = f"attempt-{attempt_no:02d}-batch-{batch}"
        result_path = candidate_dir / f"{stem}.result.json"
        log_path = candidate_dir / f"{stem}.log.txt"
        cmd = [
            sys.executable, str(RUNNER), c["repo"], str(result_path),
            "--tasks", str(args.tasks),
            "--revision", c["revision"],
            "--benchmark-revision", args.benchmark_revision,
            "--model-name", c["id"],
            "--checkpoint-type", c.get("checkpointType", "instruct"),
            "--quantization", c.get("quantization", "unknown"),
            "--prompt-mode", c.get("promptMode", "chat"),
            "--dtype", "half",
            "--max-model-len", str(args.max_model_len),
            "--tensor-parallel-size", str(c.get("tensorParallelSize", 1)),
            "--batch-size", str(batch),
        ]
        if c.get("languageModelOnly"):
            cmd.append("--language-model-only")
        if c.get("trustRemoteCode"):
            cmd.append("--trust-remote-code")
        if args.stage == "smoke":
            cmd += ["--limit", "16"]

        started = time.time()
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        elapsed = time.time() - started
        log_path.write_text(proc.stdout, encoding="utf-8", errors="replace")
        categories = [] if proc.returncode == 0 else classify(proc.stdout)
        attempt = {
            "attempt": attempt_no,
            "batchSize": batch,
            "returnCode": proc.returncode,
            "elapsedSeconds": round(elapsed, 3),
            "result": str(result_path),
            "log": str(log_path),
            "failureCategories": categories,
            "command": cmd,
        }
        summary["attempts"].append(attempt)
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

        if proc.returncode == 0:
            stable_result = str(result_path)
            summary["status"] = "completed"
            summary["stableBatchSize"] = batch
            summary["result"] = stable_result
            break

        oom = any(category in {"cuda_oom_load", "cuda_oom_generate"} for category in categories)
        if not oom:
            summary["status"] = "runtime_unqualified"
            summary["terminalFailureCategories"] = categories
            break
        if batch == 1:
            summary["status"] = "runtime_unqualified"
            summary["terminalFailureCategories"] = categories
            summary["reason"] = "same frozen model configuration cannot run even at batch 1"
            break

    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": summary["status"], "summary": str(summary_path), "result": stable_result}, indent=2))
    if summary["status"] != "completed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
