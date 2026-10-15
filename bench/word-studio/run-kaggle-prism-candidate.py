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
from typing import Any

import requests

from kaggle_failure_taxonomy import classify
from kaggle_batch_policy import (
    CANONICAL_LADDER,
    MAX_TRANSIENT_RETRIES,
    PRODUCT_BATCH_POLICY,
    PRODUCT_STAGES,
    decide_after_attempt,
)
import kaggle_gpu_resource_gate as gpu_resource_gate
from kaggle_hub_artifact_preflight import inspect_hub_artifact
import kaggle_promotion_gate as promotion_gate
from kaggle_server_identity import owned_process_tree

HERE = Path(__file__).resolve().parent
ROSTER = HERE / "kaggle-candidate-roster.json"
CLIENT = HERE / "run-english-core-llamacpp.py"
DEFAULT_ENGLISH_TASKS = HERE / "english-core-fixed-screen.jsonl"
DEFAULT_WORD_STUDIO_TASKS = HERE / "word-studio-strength.jsonl"
DEFAULT_TRANSFORM_TASKS = HERE / "word-studio-transform.jsonl"
DEFAULT_RUNTIME_ID = "prism-llamacpp-b10735-cuda12.8-linux-x86_64"

#: Issue #47: one canonical English fallback ladder, shared with the vLLM
#: wrapper through kaggle_batch_policy. The number here is *client request
#: concurrency* (ThreadPoolExecutor max_workers in the llama.cpp client), not a
#: KV-cache allocation parameter: llama-server is started once before this loop
#: with a fixed --ctx-size and default n_parallel, so the batch cannot change
#: model construction or KV allocation. That distinction is recorded on the
#: summary as `batchParameterSemantics` so a Prism rung is never misread as the
#: vLLM generation batch ladder.
BATCH_LADDER = CANONICAL_LADDER
BATCH_PARAMETER_SEMANTICS = "llama-client-request-concurrency"


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


def pre_run_resource_gate(
    *, tensor_parallel: int, run_identity: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    state = gpu_resource_gate.sample_gpu_state()
    pre_run = gpu_resource_gate.require_clean_pre_run(
        state=state,
        tensor_parallel=tensor_parallel,
        cuda_visible_devices=[0],
        run_identity=run_identity,
    )
    return state, pre_run


def post_stage_resource_gate(
    *, tensor_parallel: int, baseline: dict[str, Any], owned_pids: list[int]
) -> dict[str, Any]:
    return gpu_resource_gate.quarantine_after_stage(
        tensor_parallel=tensor_parallel,
        baseline=baseline,
        owned_pids=owned_pids,
    )


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
    ap.add_argument("--tasks", type=Path, default=None, help="predeclared frozen task override; canonical dispatcher uses this for protocol smoke")
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
    # Dedicated alias so the shared promotion gate always binds the *runtime*
    # receipt, never a GPU-gate receipt that shares the local name in nested
    # scopes below.
    runtime_receipt_path = receipt_path
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
        "schemaVersion": 4,
        "candidate": c,
        "stage": args.stage,
        "benchmarkRevision": args.benchmark_revision,
        "runtimeReceipt": str(receipt_path),
        "runtimeArtifact": artifact,
        "attempts": [],
        "status": "starting",
    }
    write_json(summary_path, summary)

    gate_identity = {
        "runNonce": hashlib.sha256(f"{args.candidate_id}:{time.time_ns()}".encode()).hexdigest()[:24],
        "candidateId": c["id"],
        "stage": args.stage,
        "benchmarkRevision": args.benchmark_revision,
    }
    tensor_parallel = int(c.get("tensorParallelSize", 1))
    try:
        gate_state, gate_pre_run = pre_run_resource_gate(
            tensor_parallel=tensor_parallel,
            run_identity=gate_identity,
        )
    except gpu_resource_gate.GateError as exc:
        summary["status"] = gpu_resource_gate.BLOCKED_CATEGORY
        summary["terminalFailureCategories"] = [gpu_resource_gate.BLOCKED_CATEGORY]
        summary["terminalFailureStage"] = "install"
        summary["terminalFailureClass"] = "infrastructure_blocked"
        summary["reason"] = str(exc)
        receipt = gpu_resource_gate.build_gate_receipt(
            run_identity=gate_identity,
            tensor_parallel=tensor_parallel,
            pre_run=exc.evidence,
            state=gpu_resource_gate.sample_gpu_state(),
        )
        receipt_path = candidate_dir / "gpu-resource-gate.json"
        write_json(receipt_path, receipt)
        summary["resourceGateReceiptPath"] = str(receipt_path)
        summary["resourceGateReceipt"] = receipt
        summary["resourceGate"] = {"preRun": exc.evidence, "postStages": []}
        write_json(summary_path, summary)
        raise SystemExit(2)
    gate_baseline = {"perGpu": gate_pre_run.get("perGpu", [])}
    summary["resourceGate"] = {"preRun": gate_pre_run, "postStages": []}
    initial_gate_receipt = gpu_resource_gate.build_gate_receipt(
        run_identity=gate_identity,
        tensor_parallel=tensor_parallel,
        pre_run=gate_pre_run,
        state=gate_state,
    )
    gate_receipt_path = candidate_dir / "gpu-resource-gate.json"
    write_json(gate_receipt_path, initial_gate_receipt)
    summary["resourceGateReceiptPath"] = str(gate_receipt_path)
    summary["resourceGateReceipt"] = initial_gate_receipt
    write_json(summary_path, summary)

    def record_resource_gate_stage(stage: str, owned_pids: list[int]) -> dict[str, Any]:
        stage_gate = post_stage_resource_gate(
            tensor_parallel=tensor_parallel,
            baseline=gate_baseline,
            owned_pids=owned_pids,
        )
        summary["resourceGate"]["postStages"].append({"stage": stage, "receipt": stage_gate})
        receipt = gpu_resource_gate.build_gate_receipt(
            run_identity=gate_identity,
            tensor_parallel=tensor_parallel,
            pre_run=gate_pre_run,
            state=gate_state,
            post_stage=stage_gate,
            owned_pids=owned_pids,
        )
        receipt_path = candidate_dir / f"gpu-resource-gate-{len(summary['resourceGate']['postStages']):02d}.json"
        write_json(receipt_path, receipt)
        summary["resourceGateReceiptPath"] = str(receipt_path)
        summary["resourceGateReceipt"] = receipt
        write_json(summary_path, summary)
        return stage_gate

    device_probe = subprocess.run(
        [str(server), "--list-devices"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False
    )
    (candidate_dir / "device-probe.log.txt").write_text(device_probe.stdout, encoding="utf-8", errors="replace")
    if device_probe.returncode != 0 or "cuda" not in device_probe.stdout.lower():
        summary["status"] = "runtime_unqualified"
        summary["terminalFailureCategories"] = classify(device_probe.stdout, stage="install")
        summary["terminalFailureStage"] = "install"
        summary["reason"] = "pinned prebuilt did not enumerate a CUDA device"
        write_json(summary_path, summary)
        raise SystemExit(2)
    probe_gate = record_resource_gate_stage("runtime_device_probe", [])
    if not probe_gate.get("clean"):
        summary["status"] = gpu_resource_gate.BLOCKED_CATEGORY
        summary["terminalFailureCategories"] = [gpu_resource_gate.BLOCKED_CATEGORY]
        summary["terminalFailureStage"] = "cleanup"
        summary["terminalFailureClass"] = "infrastructure_blocked"
        summary["reason"] = "post-device-probe GPU resource quarantine was not clean"
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
        summary["terminalFailureCategories"] = (
            [artifact_preflight["failureCategory"]]
            if artifact_preflight.get("failureCategory")
            else classify(str(artifact_preflight.get("reason") or artifact_preflight.get("status")), stage="download")
        )
        summary["terminalFailureStage"] = "download"
        summary["reason"] = f"Hub artifact preflight failed: {artifact_preflight.get('status')}"
        write_json(summary_path, summary)
        raise SystemExit(2)
    write_json(summary_path, summary)

    try:
        model_path, expected_lfs_sha, actual_sha = hub_file(c["repo"], c["revision"], c["file"])
    except BaseException as exc:
        text = f"{type(exc).__name__}: {exc}"
        download_gate = record_resource_gate_stage("artifact_download", [])
        if not download_gate.get("clean"):
            summary["observedDownloadFailure"] = text
            summary["status"] = gpu_resource_gate.BLOCKED_CATEGORY
            summary["terminalFailureCategories"] = [gpu_resource_gate.BLOCKED_CATEGORY]
            summary["terminalFailureStage"] = "cleanup"
            summary["terminalFailureClass"] = "infrastructure_blocked"
            summary["reason"] = "post-download-failure GPU resource quarantine was not clean"
            write_json(summary_path, summary)
            raise SystemExit(2) from exc
        summary["status"] = "runtime_unqualified"
        summary["terminalFailureCategories"] = classify(text, stage="download")
        summary["terminalFailureStage"] = "download"
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
    download_gate = record_resource_gate_stage("artifact_download", [])
    if not download_gate.get("clean"):
        summary["status"] = gpu_resource_gate.BLOCKED_CATEGORY
        summary["terminalFailureCategories"] = [gpu_resource_gate.BLOCKED_CATEGORY]
        summary["terminalFailureStage"] = "cleanup"
        summary["terminalFailureClass"] = "infrastructure_blocked"
        summary["reason"] = "post-download GPU resource quarantine was not clean"
        write_json(summary_path, summary)
        raise SystemExit(2)

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
    server_owned_pids = sorted(owned_process_tree(proc.pid))
    gate_outcome = None
    try:
        healthy, health_detail = wait_for_server(proc, endpoint, args.startup_timeout)
        log_handle.flush()
        if not healthy:
            log_text = server_log.read_text(encoding="utf-8", errors="replace") if server_log.exists() else health_detail
            summary["status"] = "runtime_unqualified"
            summary["terminalFailureCategories"] = classify(log_text + "\n" + health_detail, stage="server_start")
            summary["terminalFailureStage"] = "server_start"
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

        if args.tasks is not None:
            tasks = args.tasks.resolve()
            max_tokens = 350 if args.stage == "smoke" else 1200
            limit_args: list[str] = []
            batch_ladder = BATCH_LADDER if args.stage == "smoke" else PRODUCT_BATCH_POLICY
        elif args.stage == "word-studio":
            tasks = DEFAULT_WORD_STUDIO_TASKS
            max_tokens = 1200
            limit_args = []
            batch_ladder = PRODUCT_BATCH_POLICY
        elif args.stage == "transform":
            tasks = DEFAULT_TRANSFORM_TASKS
            max_tokens = 900
            limit_args = []
            batch_ladder = PRODUCT_BATCH_POLICY
        else:
            tasks = DEFAULT_ENGLISH_TASKS
            max_tokens = 220
            limit_args = ["--limit", "16"] if args.stage == "smoke" else []
            batch_ladder = BATCH_LADDER
        if not tasks.is_file():
            raise SystemExit(f"frozen task file missing: {tasks}")
        summary["tasks"] = str(tasks)
        summary["batchLadder"] = list(batch_ladder)
        summary["canonicalLadder"] = list(CANONICAL_LADDER)
        summary["batchParameterSemantics"] = BATCH_PARAMETER_SEMANTICS
        summary["batchPolicy"] = (
            "product-single-batch"
            if args.stage in PRODUCT_STAGES
            else "canonical-concurrency-ladder"
        )
        summary["maxTransientSameConfigRetries"] = MAX_TRANSIENT_RETRIES
        write_json(summary_path, summary)

        stable_result = None
        batch_index = 0
        attempt_no = 0
        transient_retries_used = 0
        while batch_index < len(batch_ladder):
            batch = batch_ladder[batch_index]
            attempt_no += 1
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
            failure_stage = "generate"
            categories = [] if client.returncode == 0 else classify(client.stdout, stage=failure_stage)
            decision = decide_after_attempt(
                returncode=client.returncode,
                categories=categories,
                batch=batch,
                transient_retries_used=transient_retries_used,
                parameter_name="batch",
            )
            summary["attempts"].append({
                "attempt": attempt_no, "batchSize": batch, "returnCode": client.returncode,
                "elapsedSeconds": round(elapsed, 3), "result": str(result_path),
                "log": str(client_log), "failureCategories": categories,
                "failureStage": failure_stage if client.returncode != 0 else None, "command": cmd,
                "decision": decision.to_dict(),
            })
            write_json(summary_path, summary)
            if decision.action == "complete":
                stable_result = result_path
                summary["stableBatchSize"] = batch
                break
            summary["capacityFailure"] = {
                "oomClass": decision.oom_class,
                "batchSize": batch,
                "decision": decision.action,
                "parameterSemantics": BATCH_PARAMETER_SEMANTICS,
            }
            if decision.action == "step_down_batch":
                batch_index += 1
                continue
            if decision.action == "retry_same_config":
                transient_retries_used += 1
                continue
            summary["status"] = "runtime_unqualified"
            summary["terminalFailureCategories"] = categories
            summary["terminalFailureStage"] = failure_stage
            if decision.failure_class:
                summary["terminalFailureClass"] = decision.failure_class
            summary["reason"] = decision.reason
            write_json(summary_path, summary)
            raise SystemExit(2)

        if stable_result is None:
            summary["status"] = "runtime_unqualified"
            summary["terminalFailureCategories"] = ["cuda_oom_generate"]
            summary["terminalFailureClass"] = "generation_capacity"
            summary["reason"] = (
                "canonical ladder exhausted without a stable batch; generation capacity "
                "is insufficient for this frozen model configuration"
            )
            write_json(summary_path, summary)
            raise SystemExit(2)

        summary["result"] = str(stable_result)
        # Issue #62: this wrapper used to mark a full-screen result `completed`
        # straight after diagnostics, with no promotion validator at all, which
        # let a Prism result enter the candidate matrix under a weaker gate than
        # vLLM evidence. Post-inference validation and terminalization are now
        # the one shared runtime-neutral path both wrappers consume, so
        # `completed` means the same thing on both runtimes.
        gate_outcome = promotion_gate.run_post_inference_gate(
            promotion_gate.GateProvenance(
                stage=args.stage,
                decode=promotion_gate.PROMOTION_DECODE,
                candidate=c,
                benchmark_revision=args.benchmark_revision,
                result_path=stable_result,
                tasks_path=tasks,
                runtime=str(c.get("runtime") or "llama.cpp"),
                model_artifact=summary.get("modelArtifact"),
                runtime_environment={
                    "runtimeArtifactId": args.runtime_artifact_id,
                    "runtimeReceipt": str(runtime_receipt_path),
                    "serverCommand": summary.get("serverCommand"),
                    "ctxSize": args.ctx_size,
                },
                extra={
                    "stableBatchSize": summary.get("stableBatchSize"),
                    "batchParameterSemantics": BATCH_PARAMETER_SEMANTICS,
                    "gatePolicy": (
                        "the shared promotion gate is the only producer of this "
                        "wrapper's post-inference terminal statuses; see "
                        "kaggle_promotion_gate.TERMINAL_STATUSES"
                    ),
                },
            ),
            candidate_dir=candidate_dir,
        )
        summary.update(gate_outcome.summary_patch())
        summary["reason"] = gate_outcome.reason
        write_json(summary_path, summary)
    finally:
        cleanup_errors: list[dict[str, object]] = []
        server_owned_pids = sorted(set(server_owned_pids) | owned_process_tree(proc.pid))
        if proc.poll() is None:
            try:
                proc.terminate()
            except Exception as exc:
                text = f"{type(exc).__name__}: {exc}"
                cleanup_errors.append({"error": text, "failureCategories": classify(text, stage="cleanup")})
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    proc.wait(timeout=10)
                except Exception as exc:
                    text = f"{type(exc).__name__}: {exc}"
                    cleanup_errors.append({"error": text, "failureCategories": classify(text, stage="cleanup")})
        try:
            log_handle.close()
        except Exception as exc:
            text = f"{type(exc).__name__}: {exc}"
            cleanup_errors.append({"error": text, "failureCategories": classify(text, stage="cleanup")})
        summary["serverStopped"] = proc.poll() is not None
        summary["serverReturnCode"] = proc.returncode
        if cleanup_errors:
            summary["cleanupFailureStage"] = "cleanup"
            summary["cleanupFailures"] = cleanup_errors
        server_gate = record_resource_gate_stage("server_and_inference", server_owned_pids)
        if not server_gate.get("clean"):
            for attempt in summary.get("attempts", []):
                attempt["candidateEvidenceEligible"] = False
                attempt["observedCandidateFailureCategories"] = attempt.get("failureCategories", [])
                attempt["failureCategories"] = [gpu_resource_gate.BLOCKED_CATEGORY]
            summary["status"] = gpu_resource_gate.BLOCKED_CATEGORY
            summary["terminalFailureCategories"] = [gpu_resource_gate.BLOCKED_CATEGORY]
            summary["terminalFailureStage"] = "cleanup"
            summary["terminalFailureClass"] = "infrastructure_blocked"
            summary["reason"] = "post-server GPU resource quarantine was not clean"
        summary["candidateEvidenceEligible"] = False
        write_json(summary_path, summary)
    print(json.dumps({
        "status": summary["status"],
        "summary": str(summary_path),
        "result": summary.get("result"),
    }, indent=2))
    if summary["status"] == gpu_resource_gate.BLOCKED_CATEGORY:
        raise SystemExit(2)
    if gate_outcome is not None and summary["status"] != promotion_gate.COMPLETED:
        # The shared gate owns the terminal exit codes, so a Prism full-screen
        # validation failure and a Prism tooling failure are distinguishable
        # exactly as they are on the vLLM side.
        raise SystemExit(gate_outcome.exit_code)


if __name__ == "__main__":
    main()
