#!/usr/bin/env python3
"""Single entry point for a pinned Kaggle candidate run.

The candidate roster decides the runtime. This dispatcher contains no model
selection logic and does not modify prompts, quantization, or runtime identity.
Product task files and pinned binary runtimes are prepared mechanically so an
execution agent only supplies a candidate ID and stage.
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
INSTALL_RUNTIME = HERE / "install-kaggle-prebuilt-runtime.py"
VERIFY_RUNTIME = HERE / "verify-kaggle-prebuilt-runtime.py"
SYNTHETIC_SEED = HERE / "word-studio-synthetic.seed.json"
STRENGTH_TASKS = HERE / "word-studio-strength.jsonl"
TRANSFORM_TASKS = HERE / "word-studio-transform.jsonl"
RUNTIME_DIR = Path("/kaggle/working/pari-runtimes")
VLLM_RUNTIME = "vllm-0.30.0-cu129-linux-x86_64"
PRISM_RUNTIME = "prism-llamacpp-b10735-cuda12.8-linux-x86_64"


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


def run_checked(cmd: list[str], label: str) -> None:
    print("+", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n", flush=True)
    if proc.returncode != 0:
        raise SystemExit(f"{label} failed rc={proc.returncode}; do not compile or improvise a fallback")


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

    run_checked(cmd, "product task build")
    actual = jsonl_count(output)
    if actual != expected:
        raise SystemExit(f"product task build count mismatch for {output.name}: expected {expected}, got {actual}")
    print(f"verified product task build: {output.name} cases={actual}", flush=True)


def ensure_runtime(artifact_id: str) -> None:
    receipt = RUNTIME_DIR / f"{artifact_id}.receipt.json"
    if not receipt.is_file():
        run_checked(
            [sys.executable, str(INSTALL_RUNTIME), artifact_id, "--dest", str(RUNTIME_DIR)],
            "pinned prebuilt runtime install",
        )
    run_checked(
        [sys.executable, str(VERIFY_RUNTIME), artifact_id, "--runtime-dir", str(RUNTIME_DIR)],
        "pinned prebuilt runtime verification",
    )


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
        runtime_artifact = args.runtime_artifact_id or VLLM_RUNTIME
        if runtime_artifact != VLLM_RUNTIME:
            raise SystemExit(f"canonical vLLM benchmark runtime is fixed to {VLLM_RUNTIME}; alternate builds are separate experiments")
        ensure_runtime(runtime_artifact)
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
        runtime_artifact = args.runtime_artifact_id or PRISM_RUNTIME
        ensure_runtime(runtime_artifact)
        cmd = [
            sys.executable, str(PRISM), args.candidate_id,
            "--stage", args.stage,
            "--benchmark-revision", args.benchmark_revision,
            "--results-dir", str(args.results_dir),
            "--runtime-artifact-id", runtime_artifact,
        ]
    else:
        raise SystemExit(f"candidate {args.candidate_id} has unsupported canonical runtime {runtime!r}")

    print("+", " ".join(cmd), flush=True)
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
