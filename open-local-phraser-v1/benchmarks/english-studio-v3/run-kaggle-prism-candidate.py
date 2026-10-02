#!/usr/bin/env python3
"""Mechanical Kaggle runner for pinned Prism/Bonsai GGUF candidates.

Uses only a verified vendor prebuilt llama-server receipt. It downloads the exact
GGUF at the roster revision, proves CUDA placement, runs the frozen client, and
preserves all failures. It never compiles llama.cpp or changes quantization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

from kaggle_failure_taxonomy import classify
from kaggle_hub_artifact_preflight import inspect_hub_artifact

HERE = Path(__file__).resolve().parent
ROSTER = HERE / "kaggle-candidate-roster.json"
CLIENT = HERE / "run-english-core-llamacpp.py"
DIAGNOSTICS = HERE / "protocol_output_diagnostics.py"
DEFAULT_ENGLISH_TASKS = HERE / "english-core-fixed-screen.jsonl"
DEFAULT_WORD_STUDIO_TASKS = HERE / "word-studio-strength.jsonl"
DEFAULT_TRANSFORM_TASKS = HERE / "word-studio-transform.jsonl"
DEFAULT_RUNTIME_ID = "prism-llamacpp-b10735-cuda12.8-linux-x86_64"
BATCH_LADDER = (16, 8, 4, 1)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def gpu_memory_for_pid(pid: int) -> int:
    proc = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid,used_gpu_memory", "--format=csv,noheader,nounits"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    total = 0
    for line in proc.stdout.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            if int(parts[0]) == pid:
                total += int(re.sub(r"[^0-9]", "", parts[1]) or "0")
        except ValueError:
            continue
    return total


def wait_for_server(proc: subprocess.Popen, endpoint: str, timeout: float) -> tuple[bool, str]:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            return False, f"server exited early with {proc.returncode}"
        try:
            response = requests.get(endpoint + "/health", timeout=3)
            if response.ok:
                return True, "healthy"
            last = f"health HTTP {response.status_code}"
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(2)
    return False, f"health timeout: {last}"


def hub_file(repo: str, revision: str, filename: str) -> tuple[Path, str | None, str]:
    try:
        from huggingface_hub import HfApi, hf_hub_download
    except Exception as exc:
        raise SystemExit(f"huggingface_hub unavailable: {type(exc).__name__}: {exc}; do not install from source") from exc
    info = HfApi().model_info(repo, revision=revision, files_metadata=True)
    if info.sha != revision:
        raise SystemExit(f"Hub resolved {repo}@{revision} to unexpected commit {info.sha}")
    expected = None
    for sibling in info.siblings or []:
        if getattr(sibling, "rfilename", None) != filename:
            continue
        lfs = getattr(sibling, "lfs", None)
        expected = getattr(lfs, "oid", None) if lfs else None
        if isinstance(lfs, dict):
            expected = lfs.get("oid") or lfs.get("sha256")
        break
    local = Path(hf_hub_download(repo_id=repo, filename=filename, revision=revision)).resolve()
    actual = sha256_file(local)
    if expected and re.fullmatch(r"[0-9a-fA-F]{64}", str(expected)) and actual.lower() != str(expected).lower():
        raise SystemExit(f"GGUF SHA256 mismatch: expected Hub LFS {expected}, got {actual}")
    return local, str(expected) if expected else None, actual


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate_id")
    ap.add_argument("--stage", choices=["smoke", "full", "word-studio", "transform"], required=True)
    ap.add_argument("--benchmark-revision", required=True)
    ap.add_argument("--runtime-artifact-id", default=DEFAULT_RUNTIME_ID)
    ap.add_argument("--runtime-dir", type=Path, default=Path("/kaggle/working/pari-runtimes"))
    ap.add_argument("--preflight", type=Path, default=Path("/kaggle/working/results/preflight.json"))
    ap.add_argument("--results-dir", type=Path, default=Path("/kaggle/working/results"))
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--startup-timeout", type=float, default=180.0)
    ap.add_argument("--ctx-size", type=int, default=8192)
    args = ap.parse_args()

    if not args.preflight.is_file():
        raise SystemExit("missing Kaggle preflight artifact; run kaggle-preflight.py first")
    preflight = load_json(args.preflight)
    if not preflight.get("promotionEligibleEnvironment"):
        raise SystemExit("preflight is not a qualified real Kaggle T4x2 environment")

    roster = load_json(ROSTER)
    by_id = {row["id"]: row for row in roster["candidates"]}
    c = by_id.get(args.candidate_id)
    if c is None:
        raise SystemExit(f"unknown candidate {args.candidate_id}")
    if c.get("runtime") != "llama.cpp":
        raise SystemExit(f"candidate {args.candidate_id} is not a llama.cpp candidate")
    if not c.get("file"):
        raise SystemExit("GGUF candidate has no pinned file in roster")

    receipt_path = args.runtime_dir / f"{args.runtime_artifact_id}.receipt.json"
    if not receipt_path.is_file():
        raise SystemExit(
            f"missing verified runtime receipt {receipt_path}; run install-kaggle-prebuilt-runtime.py first; do not compile"
        )
    receipt = load_json(receipt_path)
    artifact = receipt.get("artifact") or {}
    if receipt.get("sourceCompilationAllowed") is not False:
        raise SystemExit("runtime receipt does not explicitly forbid source compilation")
    if artifact.get("runtime") != "PrismML-Eng/llama.cpp":
        raise SystemExit("runtime receipt is not the pinned Prism llama.cpp runtime")
    if artifact.get("sourceCommit") != c.get("runtimeRevision"):
        raise SystemExit(
            f"runtime commit mismatch: receipt={artifact.get('sourceCommit')} candidate={c.get('runtimeRevision')}"
        )
    server = Path(receipt.get("runtimeExecutable") or "")
    if not server.is_file():
        raise SystemExit(f"verified runtime executable missing: {server}")

    candidate_dir = args.results_dir / args.candidate_id / args.stage
    candidate_dir.mkdir(parents=True, exist_ok=True)
    summary_path = candidate_dir / "summary.json"
    server_log = candidate_dir / "llama-server.log.txt"
    summary = {
        "schemaVersion": 3,
        "candidate": c,
        "stage": args.stage,
        "benchmarkRevision": args.benchmark_revision,
        "runtimeReceipt": str(receipt_path),
        "runtimeArtifact": artifact,
        "attempts": [],
        "status": "starting",
    }
    write_json(summary_path, summary)

    device_probe = subprocess.run(
        [str(server), "--list-devices"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False
    )
    (candidate_dir / "device-probe.log.txt").write_text(device_probe.stdout, encoding="utf-8", errors="replace")
    if device_probe.returncode != 0 or "cuda" not in device_probe.stdout.lower():
        summary["status"] = "runtime_unqualified"
        summary["terminalFailureCategories"] = classify(device_probe.stdout)
        summary["reason"] = "pinned prebuilt did not enumerate a CUDA device"
        write_json(summary_path, summary)
        raise SystemExit(2)

    artifact_preflight = inspect_hub_artifact(
        c["repo"], c["revision"], filename=c["file"], disk_root=Path("/kaggle/working")
    )
    artifact_preflight_path = candidate_dir / "hub-artifact-preflight.json"
    write_json(artifact_preflight_path, artifact_preflight)
    summary["hubArtifactPreflight"] = str(artifact_preflight_path)
    summary["expectedHubBytes"] = artifact_preflight.get("selectedBytes")
    if artifact_preflight.get("status") != "qualified":
        summary["status"] = "runtime_unqualified"
        summary["terminalFailureCategories"] = [artifact_preflight.get("failureCategory") or "artifact_size_unknown"]
        summary["reason"] = f"Hub artifact preflight failed: {artifact_preflight.get('status')}"
        write_json(summary_path, summary)
        raise SystemExit(2)
    write_json(summary_path, summary)

    try:
        model_path, expected_lfs_sha, actual_sha = hub_file(c["repo"], c["revision"], c["file"])
    except BaseException as exc:
        text = f"{type(exc).__name__}: {exc}"
        summary["status"] = "runtime_unqualified"
        summary["terminalFailureCategories"] = classify(text)
        summary["reason"] = text
        write_json(summary_path, summary)
        raise

    summary["modelArtifact"] = {
        "path": str(model_path),
        "hubLfsSha256": expected_lfs_sha,
        "localSha256": actual_sha,
        "sizeBytes": model_path.stat().st_size,
    }
    write_json(summary_path, summary)

    endpoint = f"http://127.0.0.1:{args.port}"
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "0"
    server_cmd = [
        str(server), "-m", str(model_path),
        "--host", "127.0.0.1", "--port", str(args.port),
        "--device", "CUDA0", "--gpu-layers", "all", "--split-mode", "none",
        "--ctx-size", str(args.ctx_size), "--fit", "off", "--verbose",
    ]
    summary["serverCommand"] = server_cmd
    write_json(summary_path, summary)

    log_handle = server_log.open("w", encoding="utf-8")
    proc = subprocess.Popen(server_cmd, stdout=log_handle, stderr=subprocess.STDOUT, text=True, env=env)
    try:
        healthy, health_detail = wait_for_server(proc, endpoint, args.startup_timeout)
        log_handle.flush()
        if not healthy:
            log_text = server_log.read_text(encoding="utf-8", errors="replace") if server_log.exists() else health_detail
            summary["status"] = "runtime_unqualified"
            summary["terminalFailureCategories"] = classify(log_text + "\n" + health_detail)
            summary["reason"] = health_detail
            write_json(summary_path, summary)
            raise SystemExit(2)

        gpu_mib = gpu_memory_for_pid(proc.pid)
        summary["serverPid"] = proc.pid
        summary["gpuPlacementEvidence"] = {
            "cudaDeviceProbe": True,
            "serverGpuMemoryMiB": gpu_mib,
            "passed": gpu_mib >= 128,
        }
        if gpu_mib < 128:
            summary["status"] = "runtime_unqualified"
            summary["terminalFailureCategories"] = ["gpu_offload_unverified"]
            summary["reason"] = f"server healthy but nvidia-smi reports only {gpu_mib} MiB for server pid"
            write_json(summary_path, summary)
            raise SystemExit(2)

        if args.stage == "word-studio":
            tasks = DEFAULT_WORD_STUDIO_TASKS
            max_tokens = 1200
            limit_args: list[str] = []
            batch_ladder = (1,)
        elif args.stage == "transform":
            tasks = DEFAULT_TRANSFORM_TASKS
            max_tokens = 900
            limit_args = []
            batch_ladder = (1,)
        else:
            tasks = DEFAULT_ENGLISH_TASKS
            max_tokens = 220
            limit_args = ["--limit", "16"] if args.stage == "smoke" else []
            batch_ladder = BATCH_LADDER
        if not tasks.is_file():
            raise SystemExit(f"frozen task file missing: {tasks}")

        stable_result = None
        for attempt_no, batch in enumerate(batch_ladder, start=1):
            stem = f"attempt-{attempt_no:02d}-batch-{batch}"
            result_path = candidate_dir / f"{stem}.result.json"
            client_log = candidate_dir / f"{stem}.client.log.txt"
            cmd = [
                sys.executable, str(CLIENT), c["repo"], str(model_path), str(result_path),
                "--tasks", str(tasks), "--revision", c["revision"],
                "--benchmark-revision", args.benchmark_revision,
                "--model-name", c["id"], "--runtime-build", str(c["runtimeRevision"]),
                "--quantization", c.get("quantization", "unknown"),
                "--checkpoint-type", c.get("checkpointType", "instruct"),
                "--prompt-mode", "chat", "--endpoint", endpoint,
                "--batch-size", str(batch), "--max-tokens", str(max_tokens),
                *limit_args,
            ]
            started = time.time()
            client = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            elapsed = time.time() - started
            client_log.write_text(client.stdout, encoding="utf-8", errors="replace")
            categories = [] if client.returncode == 0 else classify(client.stdout)
            summary["attempts"].append({
                "attempt": attempt_no, "batchSize": batch, "returnCode": client.returncode,
                "elapsedSeconds": round(elapsed, 3), "result": str(result_path),
                "log": str(client_log), "failureCategories": categories, "command": cmd,
            })
            write_json(summary_path, summary)
            if client.returncode == 0:
                stable_result = result_path
                summary["stableBatchSize"] = batch
                break
            oom = any(x in {"cuda_oom_load", "cuda_oom_generate"} for x in categories)
            if not oom:
                summary["status"] = "runtime_unqualified"
                summary["terminalFailureCategories"] = categories
                write_json(summary_path, summary)
                raise SystemExit(2)

        if stable_result is None:
            summary["status"] = "runtime_unqualified"
            summary["terminalFailureCategories"] = ["cuda_oom_generate"]
            write_json(summary_path, summary)
            raise SystemExit(2)

        diagnostics = candidate_dir / "protocol-diagnostics.json"
        diag = subprocess.run(
            [sys.executable, str(DIAGNOSTICS), str(stable_result), str(tasks), str(diagnostics)],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        (candidate_dir / "protocol-diagnostics.log.txt").write_text(diag.stdout, encoding="utf-8", errors="replace")
        if diag.returncode != 0:
            summary["status"] = "benchmark_tool_failure"
            summary["reason"] = "protocol diagnostics failed"
            write_json(summary_path, summary)
            raise SystemExit(3)

        summary["status"] = "completed"
        summary["result"] = str(stable_result)
        summary["protocolDiagnostics"] = str(diagnostics)
        write_json(summary_path, summary)
        print(json.dumps({"status": "completed", "summary": str(summary_path), "result": str(stable_result)}, indent=2))
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
        log_handle.close()
        summary["serverStopped"] = proc.poll() is not None
        summary["serverReturnCode"] = proc.returncode
        write_json(summary_path, summary)


if __name__ == "__main__":
    main()
