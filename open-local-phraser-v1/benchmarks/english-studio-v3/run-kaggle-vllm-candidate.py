#!/usr/bin/env python3
"""Mechanical Kaggle runner for pinned vLLM roster candidates.

The wrapper chooses nothing except a predeclared batch fallback on CUDA OOM. It
preserves every attempt, supports only roster-declared speculative methods, and
never mutates model identity or benchmark prompts.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from kaggle_failure_taxonomy import classify

HERE = Path(__file__).resolve().parent
ROSTER = HERE / "kaggle-candidate-roster.json"
RUNNER = HERE / "run-english-core-vllm.py"
DIAGNOSTICS = HERE / "protocol_output_diagnostics.py"
VALIDATOR = HERE / "validate-english-core-run.py"
DEFAULT_ENGLISH_TASKS = HERE / "english-core-fixed-screen.jsonl"
DEFAULT_WORD_STUDIO_TASKS = HERE / "word-studio-strength.jsonl"
BATCH_LADDER = (32, 16, 8, 4, 1)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate_id")
    ap.add_argument("--stage", choices=["smoke", "full", "word-studio"], required=True)
    ap.add_argument("--decode", choices=["normal", "mtp", "qwen3_next_mtp"], default="normal")
    ap.add_argument("--speculative-tokens", type=int, default=1)
    ap.add_argument("--benchmark-revision", required=True)
    ap.add_argument("--preflight", type=Path, default=Path("/kaggle/working/results/preflight.json"))
    ap.add_argument("--results-dir", type=Path, default=Path("/kaggle/working/results"))
    ap.add_argument("--tasks", type=Path, default=None, help="override only for a predeclared frozen task file")
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
        raise SystemExit(f"candidate {args.candidate_id} uses {c.get('runtime')}, not vLLM; use run-kaggle-prism-candidate.py")

    if args.decode != "normal":
        allowed = set(c.get("mtpMethodsToProbe") or [])
        if args.decode not in allowed:
            raise SystemExit(
                f"decode method {args.decode} is not predeclared for {args.candidate_id}; allowed probes: {sorted(allowed)}"
            )

    try:
        import vllm  # noqa: F401
    except Exception as exc:
        raise SystemExit(f"vLLM prebuilt is not importable: {type(exc).__name__}: {exc}; do not compile fallback") from exc

    if args.tasks is not None:
        tasks = args.tasks.resolve()
    elif args.stage == "word-studio":
        tasks = DEFAULT_WORD_STUDIO_TASKS
    else:
        tasks = DEFAULT_ENGLISH_TASKS
    if not tasks.is_file():
        raise SystemExit(f"missing frozen task file: {tasks}")

    args.results_dir.mkdir(parents=True, exist_ok=True)
    candidate_dir = args.results_dir / args.candidate_id / args.stage / args.decode
    candidate_dir.mkdir(parents=True, exist_ok=True)
    batch_ladder = (1,) if args.stage == "word-studio" else BATCH_LADDER
    summary = {
        "schemaVersion": 2,
        "candidate": c,
        "stage": args.stage,
        "decode": args.decode,
        "speculativeTokens": args.speculative_tokens if args.decode != "normal" else None,
        "benchmarkRevision": args.benchmark_revision,
        "tasks": str(tasks),
        "batchLadder": list(batch_ladder),
        "attempts": [],
        "status": "running",
    }
    summary_path = candidate_dir / "summary.json"
    write_json(summary_path, summary)

    stable_result: Path | None = None
    for attempt_no, batch in enumerate(batch_ladder, start=1):
        stem = f"attempt-{attempt_no:02d}-batch-{batch}"
        result_path = candidate_dir / f"{stem}.result.json"
        log_path = candidate_dir / f"{stem}.log.txt"
        cmd = [
            sys.executable, str(RUNNER), c["repo"], str(result_path),
            "--tasks", str(tasks),
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
        if args.stage == "word-studio":
            cmd += ["--max-tokens", "1200"]
        if args.decode != "normal":
            cmd += [
                "--speculative-method", args.decode,
                "--speculative-tokens", str(args.speculative_tokens),
            ]

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
        write_json(summary_path, summary)

        if proc.returncode == 0:
            stable_result = result_path
            summary["status"] = "inference_completed"
            summary["stableBatchSize"] = batch
            summary["result"] = str(stable_result)
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

    if stable_result is not None:
        diagnostics = candidate_dir / "protocol-diagnostics.json"
        diag = subprocess.run(
            [sys.executable, str(DIAGNOSTICS), str(stable_result), str(tasks), str(diagnostics)],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        (candidate_dir / "protocol-diagnostics.log.txt").write_text(diag.stdout, encoding="utf-8", errors="replace")
        if diag.returncode != 0:
            summary["status"] = "benchmark_tool_failure"
            summary["reason"] = "protocol diagnostics failed"
        else:
            summary["protocolDiagnostics"] = str(diagnostics)
            if args.stage == "full" and args.decode == "normal":
                validation_log = candidate_dir / "promotion-validation.log.txt"
                val = subprocess.run(
                    [sys.executable, str(VALIDATOR), str(stable_result), "--promotion"],
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                )
                validation_log.write_text(val.stdout, encoding="utf-8", errors="replace")
                summary["promotionValidation"] = {
                    "returnCode": val.returncode,
                    "log": str(validation_log),
                }
                if val.returncode != 0:
                    summary["status"] = "benchmark_validation_failure"
                else:
                    summary["status"] = "completed"
            else:
                summary["status"] = "completed"

    write_json(summary_path, summary)
    print(json.dumps({
        "status": summary["status"],
        "summary": str(summary_path),
        "result": str(stable_result) if stable_result else None,
    }, indent=2))
    if summary["status"] != "completed":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
