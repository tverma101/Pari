#!/usr/bin/env python3
"""Run a pinned vLLM candidate as a local streaming server on Kaggle T4.

This is a finalist/product-latency probe, not the common English-quality runner.
It uses the verified prebuilt vLLM wheel, refuses source-build workarounds, proves
GPU memory use, streams Word Studio tasks, and shuts the server down.
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

import requests

from kaggle_failure_taxonomy import classify

HERE = Path(__file__).resolve().parent
ROSTER = HERE / "kaggle-candidate-roster.json"
CLIENT = HERE / "run-word-studio-openai-stream.py"
DEFAULT_RUNTIME_ID = "vllm-0.30.0-cu129-linux-x86_64"
DEFAULT_TRANSFORM_TASKS = HERE / "word-studio-transform.jsonl"
DEFAULT_WORD_STUDIO_TASKS = HERE / "word-studio-strength.jsonl"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def gpu_used_mib() -> dict[int, int]:
    proc = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,memory.used", "--format=csv,noheader,nounits"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    out: dict[int, int] = {}
    for line in proc.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 2:
            continue
        try:
            out[int(parts[0])] = int(parts[1])
        except ValueError:
            pass
    return out


def wait_health(proc: subprocess.Popen, endpoint: str, timeout: float) -> tuple[bool, str]:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            return False, f"server exited early rc={proc.returncode}"
        try:
            response = requests.get(endpoint + "/health", timeout=3)
            if response.ok:
                return True, "healthy"
            last = f"HTTP {response.status_code}"
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(2)
    return False, f"health timeout: {last}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate_id")
    ap.add_argument("--stage", choices=["word-studio", "transform"], required=True)
    ap.add_argument("--benchmark-revision", required=True)
    ap.add_argument("--decode", choices=["normal", "mtp", "qwen3_next_mtp"], default="normal")
    ap.add_argument("--speculative-tokens", type=int, default=1)
    ap.add_argument("--tasks", type=Path, default=None)
    ap.add_argument("--runtime-artifact-id", default=DEFAULT_RUNTIME_ID)
    ap.add_argument("--runtime-dir", type=Path, default=Path("/kaggle/working/pari-runtimes"))
    ap.add_argument("--preflight", type=Path, default=Path("/kaggle/working/results/preflight.json"))
    ap.add_argument("--results-dir", type=Path, default=Path("/kaggle/working/results"))
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--startup-timeout", type=float, default=300.0)
    ap.add_argument("--max-model-len", type=int, default=8192)
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.88)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    if not args.preflight.is_file() or not load(args.preflight).get("promotionEligibleEnvironment"):
        raise SystemExit("qualified real-Kaggle T4x2 preflight is required")

    roster = load(ROSTER)
    candidates = {row["id"]: row for row in roster["candidates"]}
    c = candidates.get(args.candidate_id)
    if c is None:
        raise SystemExit(f"unknown candidate {args.candidate_id}")
    if c.get("runtime") != "vllm":
        raise SystemExit(f"{args.candidate_id} is not a vLLM candidate")
    if args.decode != "normal" and args.decode not in set(c.get("mtpMethodsToProbe") or []):
        raise SystemExit(f"{args.decode} is not a predeclared speculative method for {args.candidate_id}")

    receipt_path = args.runtime_dir / f"{args.runtime_artifact_id}.receipt.json"
    if not receipt_path.is_file():
        raise SystemExit(f"missing verified vLLM receipt {receipt_path}; install pinned prebuilt, never compile")
    receipt = load(receipt_path)
    artifact = receipt.get("artifact") or {}
    if receipt.get("sourceCompilationAllowed") is not False or artifact.get("runtime") != "vllm":
        raise SystemExit("runtime receipt is not the approved binary-only vLLM artifact")
    if artifact.get("version") != "0.30.0":
        raise SystemExit(f"unexpected vLLM build {artifact.get('version')}; benchmark pins 0.30.0")

    vllm_exe = shutil.which("vllm")
    if not vllm_exe:
        raise SystemExit("vllm console script missing after pinned wheel installation; do not compile fallback")

    help_proc = subprocess.run(
        [vllm_exe, "serve", "--help=all"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False
    )
    required_flags = {
        "--revision", "--tokenizer-revision", "--dtype", "--tensor-parallel-size",
        "--max-model-len", "--gpu-memory-utilization", "--served-model-name",
        "--default-chat-template-kwargs",
    }
    if c.get("languageModelOnly"):
        required_flags.add("--language-model-only")
    if args.decode != "normal":
        required_flags.add("--speculative-config")
    missing = sorted(flag for flag in required_flags if flag not in help_proc.stdout)
    if help_proc.returncode != 0 or missing:
        raise SystemExit(f"pinned vLLM CLI contract mismatch; missing flags={missing}; do not improvise or rebuild")

    tasks = args.tasks.resolve() if args.tasks else (
        DEFAULT_TRANSFORM_TASKS if args.stage == "transform" else DEFAULT_WORD_STUDIO_TASKS
    )
    if not tasks.is_file():
        raise SystemExit(f"missing frozen product tasks {tasks}; build the declared suite first")

    out_dir = args.results_dir / args.candidate_id / f"latency-{args.stage}" / args.decode
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "summary.json"
    server_log = out_dir / "vllm-server.log.txt"
    stream_result = out_dir / "streaming-result.json"
    summary = {
        "version": 1,
        "candidate": c,
        "stage": f"latency-{args.stage}",
        "decode": args.decode,
        "benchmarkRevision": args.benchmark_revision,
        "runtimeReceipt": str(receipt_path),
        "tasks": str(tasks),
        "status": "starting",
    }
    write(summary_path, summary)

    tp = int(c.get("tensorParallelSize") or 1)
    visible = "0" if tp == 1 else "0,1"
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = visible
    endpoint = f"http://127.0.0.1:{args.port}"
    server_cmd = [
        vllm_exe, "serve", c["repo"],
        "--host", "127.0.0.1", "--port", str(args.port),
        "--served-model-name", c["id"],
        "--revision", c["revision"], "--tokenizer-revision", c["revision"],
        "--dtype", "half", "--tensor-parallel-size", str(tp),
        "--max-model-len", str(args.max_model_len),
        "--gpu-memory-utilization", str(args.gpu_memory_utilization),
        "--seed", "0",
        "--default-chat-template-kwargs", '{"enable_thinking":false}',
        "--enable-per-request-metrics",
    ]
    if c.get("trustRemoteCode"):
        server_cmd.append("--trust-remote-code")
    if c.get("languageModelOnly"):
        server_cmd.append("--language-model-only")
    if args.decode != "normal":
        server_cmd += [
            "--speculative-config",
            json.dumps({"method": args.decode, "num_speculative_tokens": args.speculative_tokens}, separators=(",", ":")),
        ]

    baseline_gpu = gpu_used_mib()
    summary["serverCommand"] = server_cmd
    summary["cudaVisibleDevices"] = visible
    summary["gpuMemoryBeforeMiB"] = baseline_gpu
    write(summary_path, summary)

    log_handle = server_log.open("w", encoding="utf-8")
    proc = subprocess.Popen(server_cmd, stdout=log_handle, stderr=subprocess.STDOUT, text=True, env=env)
    try:
        healthy, detail = wait_health(proc, endpoint, args.startup_timeout)
        log_handle.flush()
        if not healthy:
            log_text = server_log.read_text(encoding="utf-8", errors="replace") if server_log.exists() else detail
            summary["status"] = "runtime_unqualified"
            summary["terminalFailureCategories"] = classify(log_text + "\n" + detail)
            summary["reason"] = detail
            write(summary_path, summary)
            raise SystemExit(2)

        after_gpu = gpu_used_mib()
        delta = {index: after_gpu.get(index, 0) - baseline_gpu.get(index, 0) for index in set(after_gpu) | set(baseline_gpu)}
        expected_devices = list(range(tp))
        placement_ok = all(delta.get(index, 0) >= 64 for index in expected_devices) and sum(max(0, delta.get(i, 0)) for i in expected_devices) >= 128
        summary["gpuPlacementEvidence"] = {
            "beforeMiB": baseline_gpu,
            "afterMiB": after_gpu,
            "deltaMiB": delta,
            "expectedVisibleDeviceCount": tp,
            "passed": placement_ok,
        }
        if not placement_ok:
            summary["status"] = "runtime_unqualified"
            summary["terminalFailureCategories"] = ["gpu_offload_unverified"]
            summary["reason"] = "healthy vLLM server did not produce expected T4 VRAM delta"
            write(summary_path, summary)
            raise SystemExit(2)

        client_cmd = [
            sys.executable, str(CLIENT),
            "--endpoint", endpoint, "--model", c["id"],
            "--tasks", str(tasks), "--output", str(stream_result),
        ]
        if args.limit is not None:
            client_cmd += ["--limit", str(args.limit)]
        client = subprocess.run(client_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out_dir / "streaming-client.log.txt").write_text(client.stdout, encoding="utf-8", errors="replace")
        if client.returncode != 0:
            summary["status"] = "runtime_unqualified"
            summary["terminalFailureCategories"] = classify(client.stdout)
            summary["reason"] = "streaming product probe failed"
            write(summary_path, summary)
            raise SystemExit(2)

        summary["status"] = "completed"
        summary["result"] = str(stream_result)
        write(summary_path, summary)
        print(json.dumps({"status": "completed", "summary": str(summary_path), "result": str(stream_result)}, indent=2))
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
        log_handle.close()
        summary["serverStopped"] = proc.poll() is not None
        summary["serverReturnCode"] = proc.returncode
        if server_log.exists():
            log_text = server_log.read_text(encoding="utf-8", errors="replace")
            if "building wheel for" in log_text.lower() or "cmake" in log_text.lower() or "ninja" in log_text.lower():
                summary["sourceBuildIndicatorDetected"] = True
                summary["status"] = "runtime_unqualified"
                summary["terminalFailureCategories"] = list(dict.fromkeys([
                    *(summary.get("terminalFailureCategories") or []), "source_build_attempt_forbidden"
                ]))
        write(summary_path, summary)


if __name__ == "__main__":
    main()
