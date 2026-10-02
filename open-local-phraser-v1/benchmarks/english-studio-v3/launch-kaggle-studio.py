#!/usr/bin/env python3
"""Launch a benchmark-qualified TP1 model as a two-T4 Pari Studio service.

GPU0 and GPU1 run independent local vLLM replicas. The outer authenticated Studio
service fans requests into fast/diversity lanes. This launcher never builds native
code and never exposes the model servers themselves beyond loopback.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from kaggle_hub_artifact_preflight import inspect_hub_artifact

HERE = Path(__file__).resolve().parent
ROSTER = HERE / "kaggle-candidate-roster.json"
VERIFY_RUNTIME = HERE / "verify-kaggle-prebuilt-runtime.py"
RUNTIME_ID = "vllm-0.30.0-cu129-linux-x86_64"
DEFAULT_RUNTIME_DIR = Path("/kaggle/working/pari-runtimes")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def wait_health(url: str, proc: subprocess.Popen, timeout: float = 300.0) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"process exited before health check: rc={proc.returncode}")
        try:
            with urlopen(url, timeout=3) as response:
                if 200 <= response.status < 300:
                    return
                last = f"HTTP {response.status}"
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(2)
    raise RuntimeError(f"health timeout for {url}: {last}")


def gpu_used() -> dict[int, int]:
    proc = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,memory.used", "--format=csv,noheader,nounits"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    out: dict[int, int] = {}
    for line in proc.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 2:
            continue
        try:
            out[int(parts[0])] = int(parts[1])
        except ValueError:
            pass
    return out


def stop_process(proc: subprocess.Popen | None, timeout: float = 20.0) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate_id")
    ap.add_argument("--preflight", type=Path, default=Path("/kaggle/working/results/preflight.json"))
    ap.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME_DIR)
    ap.add_argument("--work-dir", type=Path, default=Path("/kaggle/working/pari-studio"))
    ap.add_argument("--fast-port", type=int, default=8000)
    ap.add_argument("--diversity-port", type=int, default=8001)
    ap.add_argument("--service-port", type=int, default=9000)
    ap.add_argument("--service-host", default="127.0.0.1")
    ap.add_argument("--max-model-len", type=int, default=8192)
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.88)
    args = ap.parse_args()

    if not args.preflight.is_file() or not load(args.preflight).get("promotionEligibleEnvironment"):
        raise SystemExit("qualified real-Kaggle T4x2 preflight is required")

    roster = load(ROSTER)
    candidate = {row["id"]: row for row in roster["candidates"]}.get(args.candidate_id)
    if candidate is None:
        raise SystemExit(f"unknown candidate {args.candidate_id}")
    if candidate.get("runtime") != "vllm":
        raise SystemExit("two-replica Studio launcher currently requires a vLLM candidate")
    if int(candidate.get("tensorParallelSize") or 1) != 1:
        raise SystemExit("two independent T4 lanes require a TP1 candidate that fits one T4")

    receipt = args.runtime_dir / f"{RUNTIME_ID}.receipt.json"
    verify = subprocess.run(
        [sys.executable, str(VERIFY_RUNTIME), RUNTIME_ID, "--runtime-dir", str(args.runtime_dir)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    if verify.returncode != 0:
        raise SystemExit(f"pinned vLLM runtime is not verified; do not compile fallback:\n{verify.stdout}")

    artifact = inspect_hub_artifact(candidate["repo"], candidate["revision"], disk_root=Path("/kaggle/working"))
    if artifact.get("status") != "qualified":
        raise SystemExit(f"model artifact preflight failed: {json.dumps(artifact, indent=2)}")

    vllm = shutil.which("vllm")
    uvicorn = shutil.which("uvicorn")
    if not vllm or not uvicorn:
        raise SystemExit("pinned serving environment must provide both vllm and uvicorn; do not source-build replacements")

    args.work_dir.mkdir(parents=True, exist_ok=True)
    baseline = gpu_used()
    common = [
        vllm, "serve", candidate["repo"],
        "--host", "127.0.0.1",
        "--revision", candidate["revision"],
        "--tokenizer-revision", candidate["revision"],
        "--served-model-name", candidate["id"],
        "--dtype", "half",
        "--tensor-parallel-size", "1",
        "--max-model-len", str(args.max_model_len),
        "--gpu-memory-utilization", str(args.gpu_memory_utilization),
        "--seed", "0",
        "--default-chat-template-kwargs", '{"enable_thinking":false}',
    ]
    if candidate.get("trustRemoteCode"):
        common.append("--trust-remote-code")
    if candidate.get("languageModelOnly"):
        common.append("--language-model-only")

    procs: list[subprocess.Popen] = []
    handles = []
    manifest = {
        "version": 1,
        "candidate": candidate,
        "runtimeReceipt": str(receipt),
        "fastEndpoint": f"http://127.0.0.1:{args.fast_port}",
        "diversityEndpoint": f"http://127.0.0.1:{args.diversity_port}",
        "serviceEndpoint": f"http://{args.service_host}:{args.service_port}",
        "serviceAuthenticated": bool(os.environ.get("PARI_STUDIO_TOKEN")),
        "status": "starting",
    }
    manifest_path = args.work_dir / "runtime-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    try:
        for gpu, port, name in ((0, args.fast_port, "fast"), (1, args.diversity_port, "diversity")):
            log_path = args.work_dir / f"vllm-{name}.log.txt"
            handle = log_path.open("w", encoding="utf-8")
            handles.append(handle)
            env = os.environ.copy()
            env["CUDA_VISIBLE_DEVICES"] = str(gpu)
            cmd = [*common, "--port", str(port)]
            proc = subprocess.Popen(cmd, stdout=handle, stderr=subprocess.STDOUT, text=True, env=env)
            procs.append(proc)
            wait_health(f"http://127.0.0.1:{port}/health", proc)

        after_models = gpu_used()
        deltas = {gpu: after_models.get(gpu, 0) - baseline.get(gpu, 0) for gpu in (0, 1)}
        if any(delta < 128 for delta in deltas.values()):
            raise RuntimeError(f"could not prove both independent T4 model replicas consume VRAM: {deltas}")
        manifest["gpuMemoryBeforeMiB"] = baseline
        manifest["gpuMemoryAfterModelsMiB"] = after_models
        manifest["gpuMemoryDeltaMiB"] = deltas

        service_log = args.work_dir / "studio-service.log.txt"
        service_handle = service_log.open("w", encoding="utf-8")
        handles.append(service_handle)
        service_env = os.environ.copy()
        service_env.update({
            "PARI_FAST_ENDPOINT": f"http://127.0.0.1:{args.fast_port}",
            "PARI_DIVERSITY_ENDPOINT": f"http://127.0.0.1:{args.diversity_port}",
            "PARI_FAST_MODEL": candidate["id"],
            "PARI_DIVERSITY_MODEL": candidate["id"],
        })
        if args.service_host in {"127.0.0.1", "localhost", "::1"} and not os.environ.get("PARI_STUDIO_TOKEN"):
            service_env["PARI_ALLOW_UNAUTHENTICATED_LOOPBACK"] = "1"
        elif not os.environ.get("PARI_STUDIO_TOKEN"):
            raise RuntimeError("PARI_STUDIO_TOKEN is mandatory when Studio service is not loopback-only")

        service_cmd = [
            uvicorn, "studio_backend.service:app",
            "--host", args.service_host,
            "--port", str(args.service_port),
            "--workers", "1",
        ]
        service = subprocess.Popen(service_cmd, cwd=HERE, stdout=service_handle, stderr=subprocess.STDOUT, text=True, env=service_env)
        procs.append(service)
        health_host = "127.0.0.1" if args.service_host == "0.0.0.0" else args.service_host
        wait_health(f"http://{health_host}:{args.service_port}/health", service, timeout=60)

        manifest["status"] = "ready"
        manifest["pids"] = [proc.pid for proc in procs]
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "ready", "manifest": str(manifest_path), "service": manifest["serviceEndpoint"]}, indent=2), flush=True)
        print("Studio is running in the foreground. Stop with Ctrl-C; this script will terminate both model replicas and the service.", flush=True)

        while True:
            time.sleep(1)
            dead = [proc.returncode for proc in procs if proc.poll() is not None]
            if dead:
                raise RuntimeError(f"Studio child process exited unexpectedly: {dead}")
    except KeyboardInterrupt:
        manifest["status"] = "stopping"
    finally:
        for proc in reversed(procs):
            stop_process(proc)
        for handle in handles:
            handle.close()
        manifest["status"] = "stopped"
        manifest["stoppedPids"] = [proc.pid for proc in procs]
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
