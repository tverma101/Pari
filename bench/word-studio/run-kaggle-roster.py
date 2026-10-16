#!/usr/bin/env python3
"""Run the frozen Kaggle candidate roster without agent decision-making.

Normal decode is always evaluated first. A candidate that fails a stage keeps its
artifacts and is skipped for later quality stages; the next roster candidate is
then attempted. The status matrix is regenerated after every stage.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import kaggle_run_checkpoint as K
import kaggle_stage_identity as STAGE
import kaggle_gpu_resource_gate as GATE
from kaggle_server_identity import (
    OwnedServer,
    PortCollision,
    allocate_loopback_port,
    http_get_json,
    owned_process_tree,
    release_port_reservation,
)

HERE = Path(__file__).resolve().parent
ROSTER = HERE / "kaggle-candidate-roster.json"
DISPATCH = HERE / "run-kaggle-candidate.py"
MATRIX = HERE / "build-kaggle-candidate-matrix.py"
VERIFY_PREP = HERE / "verify-kaggle-benchmark-preparation.py"


def _load_dispatcher():
    """Load the hyphenated dispatcher as a module.

    The roster and the dispatcher must agree on the summary layout, manifest
    resolution, and provenance shape, so they share one definition instead of
    two that can drift.
    """
    spec = importlib.util.spec_from_file_location("pari_kaggle_candidate", DISPATCH)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load candidate dispatcher module from {DISPATCH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CAND = _load_dispatcher()

Q1_RECEIPT_KEY = STAGE.gate_spec("q1")["receiptKey"]
Q0_RECEIPT_KEY = STAGE.gate_spec("q0")["receiptKey"]
Q1_STAGE = "q1-load"
DEFAULT_PRISM_ARTIFACT_ID = "prism-llamacpp-b10735-cuda12.8-linux-x86_64"
GPU_LEASE_PATH = "/kaggle/working/pari-runtimes/gpu-lease.json"

#: Q1's trivial generation is deliberately not English-quality evidence. It only
#: proves the exact runtime answered a real request and stayed alive afterwards.
Q1_TRIVIAL_PROMPT = "Reply with the single word: ready"
Q1_TRIVIAL_MAX_TOKENS = 8

PHASE_STAGES = {
    "smoke": ("smoke",),
    # Issue #49: Q3 bounded English smoke sits between the Q2 protocol smoke and
    # the Q4 full screen, so the english/product/all phases run it explicitly.
    "english": ("smoke", "benchmark-smoke", "full"),
    "product": ("smoke", "benchmark-smoke", "full", "transform", "word-studio"),
    "all": ("smoke", "benchmark-smoke", "full", "transform", "word-studio"),
}

ORCHESTRATION_SCHEMA_VERSION = 3

#: Terminal states for the roster orchestration artifact itself. The roster is a
#: supervisor, so it distinguishes "every planned unit reached a terminal state"
#: from "resume is possible" and from "a unit died without a terminal state".
ORCHESTRATION_TERMINAL = frozenset({
    "completed",
    "interrupted_resume_available",
    "infrastructure_failed",
    "benchmark_failed",
})


def rebuild_matrix(results_dir: Path, benchmark_revision: str | None = None) -> None:
    """Regenerate the status matrix. Never fatal: it is reporting, not evidence."""
    cmd = [sys.executable, str(MATRIX), "--results-dir", str(results_dir)]
    if benchmark_revision:
        cmd += ["--benchmark-revision", benchmark_revision]
    matrix = K.OwnedProcessGroup(
        cmd,
        Path(results_dir) / "orchestration-logs" / "candidate-matrix.log.txt",
    )
    matrix.start()
    matrix.wait()
    cleanup = matrix.reap()
    if cleanup.outcome != "already_exited":
        # The matrix rebuild should never hang; if it did, only its own process
        # group is torn down and the roster keeps its evidence.
        matrix.terminate_owned()
    matrix.drain_output()


def run_unit(
    *,
    unit_id: str,
    cmd: list[str],
    provenance: K.Provenance,
    log: Path,
    checkpoint_path: Path,
    manifest: K.TaskManifest | None,
    summary_path: Path | None = None,
    timeout_seconds: float | None = None,
    stage: str | None = None,
) -> K.UnitResult:
    """Execute one supervised command as a checkpointed unit."""
    print("+", " ".join(cmd), flush=True)
    started = time.time()
    try:
        outcome = K.execute_unit(
            unit_id=unit_id,
            unit_kind="candidate-stage",
            cmd=cmd,
            manifest=manifest,
            provenance=provenance,
            checkpoint_path=checkpoint_path,
            log_path=log,
            summary_path=summary_path,
            resolve_result_path=(
                (lambda: CAND.result_path_from_summary(summary_path))
                if manifest is not None and summary_path is not None
                else None
            ),
            timeout_seconds=timeout_seconds,
            stage=stage,
        )
    finally:
        elapsed = time.time() - started
        print(f"unit {unit_id} finished elapsed={elapsed:.1f}s log={log}", flush=True)
    print(json.dumps({
        "unit": unit_id,
        "status": outcome.status,
        "terminalReason": outcome.reason,
        "returnCode": outcome.returncode,
        "cleanup": outcome.cleanup.to_dict(),
    }, indent=2), flush=True)
    return outcome


def roster_provenance(
    *,
    benchmark_revision: str,
    phase: str,
    selected: list[str],
    preflight: Path,
    preparation_receipt: Path,
    candidates: dict,
    git_identity: K.GitIdentity | None = None,
) -> K.Provenance:
    """Provenance for the roster supervisor artifact itself."""
    manifest_entries = []
    task_files = []
    for path, role in (
        (CAND.PROTOCOL_SMOKE_TASKS, "protocol-smoke"),
        (CAND.ENGLISH_TASKS, "english-core-fixed-screen"),
        (CAND.STRENGTH_TASKS, "word-studio-strength"),
        (CAND.TRANSFORM_TASKS, "word-studio-transform"),
    ):
        if Path(path).is_file():
            manifest_entries.append(K.load_task_manifest(path, role).as_provenance_entry())
            task_files.append(str(path))
    return K.Provenance(
        benchmark_revision=benchmark_revision,
        candidate_id=",".join(selected),
        candidate_revision=",".join(
            str(candidates[cid].get("revision", "")) for cid in selected
        ),
        candidate_config_sha256=K.sha256_json({
            "phase": phase,
            "selectedCandidates": selected,
            "candidates": {cid: candidates[cid] for cid in selected},
        }),
        preflight_path=str(preflight),
        preflight_sha256=K.sha256_file(preflight),
        runtime_receipt_path=str(preparation_receipt),
        runtime_receipt_sha256=K.sha256_file(preparation_receipt),
        task_manifest_sha256s=tuple(manifest_entries),
        task_files=tuple(task_files),
        parser_code_version=K.parser_code_version(
            [HERE / "protocol_output_diagnostics.py", HERE / "validate-english-core-run.py"]
        ),
        git_identity=git_identity.to_dict() if git_identity else None,
    )


def stage_manifest(stage: str) -> K.TaskManifest | None:
    """Task manifest for a roster stage, or None when the file is not built yet."""
    mapping = {
        "smoke": (CAND.PROTOCOL_SMOKE_TASKS, "protocol-smoke"),
        # Q3 resolves to the same frozen artifact as the full screen; its task
        # identity is the registered ordered-ID prefix, never a --limit value.
        "benchmark-smoke": (CAND.ENGLISH_TASKS, "english-core-fixed-screen"),
        "word-studio": (CAND.STRENGTH_TASKS, "word-studio-strength"),
        "transform": (CAND.TRANSFORM_TASKS, "word-studio-transform"),
        "full": (CAND.ENGLISH_TASKS, "english-core-fixed-screen"),
    }
    path, role = mapping[stage]
    if not Path(path).is_file():
        return None
    return K.load_task_manifest(path, role)


# ---------------------------------------------------------------------------
# Issue #57: between-candidate GPU resource gate.
#
# The per-candidate wrappers (#62) run the gate inside each dispatcher process.
# The roster is the supervisor that owns the *handoff between candidates*, so it
# runs the same fail-closed gate once before every candidate and once after every
# candidate, and refuses to start the next candidate on a contaminated required
# GPU. Contamination is infrastructure, never candidate capacity: a blocked gate
# is recorded as `infrastructure_blocked_resource_contamination` and the roster
# must not dispatch a single stage, record an OOM, or mark a candidate
# runtime-unqualified because of it. Ownership evidence comes only from
# `kaggle_server_identity` (the PIDs this supervisor launched); foreign and
# unknown processes are recorded and blocked, never signalled by the roster.


def candidate_gpu_layout(candidate: dict) -> tuple[int, list[int]]:
    """Tensor-parallel degree and the physical devices this candidate requires."""
    tp = int(candidate.get("tensorParallelSize") or 1)
    return tp, ([0] if tp == 1 else [0, 1])


def q1_owned_pids(receipt: dict) -> list[int]:
    """Owned PIDs the Q1 probe recorded from server-identity evidence.

    A blocked gate must not attempt model qualification and must not be recorded
    as an OOM. The Q1 probe is the only GPU-touching child this supervisor
    spawns itself, so its owned PID set is the sole ownership evidence the roster
    is allowed to forward to the gate as "known residue from a prior canonical
    run". Nothing here widens that set.
    """
    pids = receipt.get("resourceGateOwnedPids")
    if not isinstance(pids, list):
        return []
    return sorted({int(p) for p in pids if isinstance(p, int) and not isinstance(p, bool)})


def pre_candidate_resource_gate(
    *,
    candidate: dict,
    residue_pids: list[int] | None = None,
) -> dict:
    """Require a clean GPU baseline before a candidate is allowed to qualify.

    Returns a roster-facing record. ``allowed: False`` means infrastructure
    contamination: the caller must not dispatch a stage and must not record an
    OOM or a runtime-unqualified status. ``residue_pids`` are PIDs this supervisor
    previously launched and are the only processes the gate may reap; foreign and
    unknown processes are never signalled.
    """
    tp, visible = candidate_gpu_layout(candidate)
    residue = sorted(set(residue_pids or ()))
    run_identity = {
        "candidateId": str(candidate.get("id")),
        "supervisorPid": os.getpid(),
        "stage": "pre_candidate",
    }
    state = GATE.sample_gpu_state()
    try:
        pre_run = GATE.require_clean_pre_run(
            state=state,
            tensor_parallel=tp,
            cuda_visible_devices=visible,
            residue_pids=residue,
            run_identity=run_identity,
        )
    except GATE.GateError as exc:
        return {
            "stage": "pre_candidate",
            "candidate": str(candidate.get("id")),
            "tensorParallel": tp,
            "cudaVisibleDevices": visible,
            "residuePids": residue,
            "runIdentity": run_identity,
            "allowed": False,
            "category": exc.category,
            "verdict": exc.category,
            "blockingReasons": list(exc.evidence.get("blockingReasons") or []),
            "preRun": exc.evidence,
            "candidateEvidenceEligible": False,
            "note": (
                "contaminated required GPU: no linguistic or capacity conclusion is "
                "allowed for this candidate and no stage may be dispatched"
            ),
        }
    return {
        "stage": "pre_candidate",
        "candidate": str(candidate.get("id")),
        "tensorParallel": tp,
        "cudaVisibleDevices": visible,
        "residuePids": residue,
        "runIdentity": run_identity,
        "allowed": True,
        "category": None,
        "verdict": pre_run.get("verdict"),
        "blockingReasons": [],
        "preRun": pre_run,
        # The pre-run per-GPU snapshot is the baseline the post-candidate
        # quarantine compares against, so residual memory cannot be hidden by
        # sleeping longer.
        "baseline": {"perGpu": pre_run.get("perGpu") or []},
        "candidateEvidenceEligible": True,
    }


def quarantine_candidate_handoff(
    *,
    candidate: dict,
    baseline: dict,
    owned_pids: list[int] | None = None,
    residue_pids: list[int] | None = None,
) -> dict:
    """Verify the handoff out of one candidate before the next one may start.

    A clean handoff proves owned processes exited, the driver released, and
    every required GPU returned within the residual band of its baseline. A
    non-clean handoff is recorded as infrastructure contamination and blocks the
    next candidate; it never converts the finished candidate's timing into an
    OOM. Only ``residue_pids`` (PIDs this supervisor launched) are eligible for
    the gate's cleanup; foreign and unknown processes are recorded and blocked,
    never signalled.

    ``owned_pids`` is deliberately narrow. The only GPU-touching child this
    supervisor spawns itself is the Q1 probe server, so ``owned_pids`` is that
    server's server-identity process tree and nothing more. Stage children are
    launched inside the shared checkpoint engine, which does not hand its owned
    PID set back to the supervisor, so a stage child's leftover VRAM cannot be
    proven owned here and is deliberately classified foreign/unknown: recorded,
    blocked, and never signalled. The residual-VRAM comparison against the
    pre-candidate baseline still catches that residue, so the narrower ownership
    set costs cleanup, never correctness.
    """
    tp, _ = candidate_gpu_layout(candidate)
    owned = sorted(set(owned_pids or ()))
    residue = sorted(set(residue_pids or ()))
    result = GATE.quarantine_after_stage(
        tensor_parallel=tp,
        baseline=baseline,
        owned_pids=owned,
        residue_pids=residue,
    )
    clean = bool(result.get("clean"))
    return {
        "stage": "post_candidate_quarantine",
        "candidate": str(candidate.get("id")),
        "tensorParallel": tp,
        "ownedPids": owned,
        "residuePids": residue,
        "clean": clean,
        "category": None if clean else GATE.BLOCKED_CATEGORY,
        "verdict": result.get("verdict"),
        "blockingReasons": list(result.get("blockingReasons") or []),
        "quarantine": result,
        # A dirty handoff means contamination arrived during or after this
        # candidate's measured work, so its timings are not comparable. The
        # candidate keeps its own terminal status; only admissibility changes.
        "candidateEvidenceEligible": clean,
        "cleanupPolicy": (
            "only PIDs this supervisor launched (owned, or recorded residue from a "
            "prior canonical run) are signalled; foreign and unknown processes are "
            "recorded and blocked, never killed"
        ),
    }


# ---------------------------------------------------------------------------
# Q1 load / placement / trivial-generation / runtime-alive receipt (issue #49)


def gpu_used_mib() -> dict[int, int]:
    """Per-GPU VRAM use in MiB, or an empty map when nvidia-smi is unavailable."""
    if not shutil.which("nvidia-smi"):
        return {}
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,memory.used", "--format=csv,noheader,nounits"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
    except OSError:
        return {}
    usage: dict[int, int] = {}
    for line in proc.stdout.splitlines():
        parts = [piece.strip() for piece in line.split(",")]
        if len(parts) != 2:
            continue
        try:
            usage[int(parts[0])] = int(parts[1])
        except ValueError:
            continue
    return usage


def gpu_mib_for_pid(pid: int) -> int:
    """VRAM held by one process, so placement is attributed to the owned child."""
    proc = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    total = 0
    for line in proc.stdout.splitlines():
        parts = [piece.strip() for piece in line.split(",")]
        if len(parts) != 2:
            continue
        try:
            if int(parts[0]) == pid:
                total += int(parts[1])
        except ValueError:
            continue
    return total


def resolve_gguf(candidate: dict) -> dict:
    """Resolve the pinned GGUF for a llama.cpp candidate at its exact revision."""
    filename = candidate.get("file")
    if not filename:
        raise K.CheckpointError(
            f"candidate {candidate['id']} has no pinned GGUF file in the roster"
        )
    from huggingface_hub import hf_hub_download

    path = Path(
        hf_hub_download(
            repo_id=candidate["repo"],
            filename=filename,
            revision=candidate["revision"],
        )
    )
    import hashlib

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "path": str(path),
        "sizeBytes": path.stat().st_size,
        "localSha256": digest,
        "repo": candidate["repo"],
        "revision": candidate["revision"],
        "file": filename,
    }


def build_q1_command(candidate: dict, port: int, runtime_dir: Path) -> tuple[list[str], dict]:
    """Build the exact candidate runtime server command for a Q1 probe.

    These are the same pinned flags the per-candidate wrappers use, so Q1
    exercises the real model identity, dtype, tensor-parallel size and chat
    template rather than a weaker second configuration.
    """
    served_model = str(candidate["id"])
    tp = int(candidate.get("tensorParallelSize") or 1)
    runtime = candidate.get("runtime")
    if runtime == "vllm":
        vllm_exe = shutil.which("vllm")
        if not vllm_exe:
            raise K.CheckpointError(
                "vllm console script is missing for Q1; the pinned prebuilt must be "
                "installed first and never compiled from source"
            )
        cmd = [
            vllm_exe, "serve", candidate["repo"],
            "--host", "127.0.0.1", "--port", str(port),
            "--served-model-name", served_model,
            "--revision", candidate["revision"],
            "--tokenizer-revision", candidate["revision"],
            "--dtype", "half", "--tensor-parallel-size", str(tp),
            "--gpu-memory-utilization", "0.88",
            "--seed", "0",
            "--default-chat-template-kwargs", '{"enable_thinking":false}',
        ]
        if candidate.get("trustRemoteCode"):
            cmd.append("--trust-remote-code")
        if candidate.get("languageModelOnly"):
            cmd.append("--language-model-only")
        return cmd, {
            "runtime": "vllm",
            "servedModelName": served_model,
            "tensorParallelSize": tp,
        }

    if runtime == "llama.cpp":
        artifact_id = candidate.get("runtimeArtifactId") or DEFAULT_PRISM_ARTIFACT_ID
        receipt_path = Path(runtime_dir) / f"{artifact_id}.receipt.json"
        if not receipt_path.is_file():
            raise K.CheckpointError(
                f"missing verified Prism runtime receipt {receipt_path}; Q1 never "
                "installs or compiles a runtime implicitly"
            )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt.get("sourceCompilationAllowed") is not False:
            raise K.CheckpointError("runtime receipt does not explicitly forbid source compilation")
        artifact = receipt.get("artifact") or {}
        if artifact.get("sourceCommit") != candidate.get("runtimeRevision"):
            raise K.CheckpointError(
                f"runtime commit mismatch: receipt={artifact.get('sourceCommit')} "
                f"candidate={candidate.get('runtimeRevision')}"
            )
        server_exe = Path(receipt.get("runtimeExecutable") or "")
        if not server_exe.is_file():
            raise K.CheckpointError(f"verified runtime executable missing: {server_exe}")
        model = resolve_gguf(candidate)
        cmd = [
            str(server_exe), "-m", model["path"],
            "--host", "127.0.0.1", "--port", str(port),
            "--device", "CUDA0", "--gpu-layers", "all", "--split-mode", "none",
            "--ctx-size", "8192", "--fit", "off",
        ]
        return cmd, {
            "runtime": "llama.cpp",
            "servedModelName": served_model,
            "tensorParallelSize": tp,
            "runtimeArtifactId": artifact_id,
            "runtimeArtifact": artifact,
            "modelArtifact": model,
        }

    raise K.CheckpointError(
        f"candidate {candidate['id']} has unsupported runtime {runtime!r}"
    )


def trivial_generation(endpoint: str, model: str) -> dict:
    """One bounded trivial generation proving the runtime really answered."""
    import urllib.request

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": Q1_TRIVIAL_PROMPT}],
        "max_tokens": Q1_TRIVIAL_MAX_TOKENS,
        "temperature": 0.0,
        "stream": False,
    }).encode("utf-8")
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode("utf-8", errors="replace"))
            status = int(response.status)
    except Exception as exc:
        return {
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "elapsedSeconds": round(time.monotonic() - started, 3),
        }
    choices = body.get("choices") or []
    text = ""
    finish_reason = None
    if choices and isinstance(choices[0], dict):
        finish_reason = choices[0].get("finish_reason")
        message = choices[0].get("message") or {}
        text = str(message.get("content") or choices[0].get("text") or "")
    return {
        "status": "completed" if text.strip() else "empty_output",
        "httpStatus": status,
        "outputText": text,
        "outputLengthChars": len(text),
        "finishReason": finish_reason,
        "elapsedSeconds": round(time.monotonic() - started, 3),
        "prompt": Q1_TRIVIAL_PROMPT,
        "maxTokens": Q1_TRIVIAL_MAX_TOKENS,
        "isEnglishQualityEvidence": False,
    }


def placement_evidence(candidate: dict, baseline: dict, after: dict, pid: int | None) -> dict:
    """Per-GPU placement proof plus a no-silent-CPU-fallback verdict."""
    tp = int(candidate.get("tensorParallelSize") or 1)
    delta = {
        index: after.get(index, 0) - baseline.get(index, 0)
        for index in set(after) | set(baseline)
    }
    expected = list(range(tp))
    per_device_ok = all(delta.get(index, 0) >= 64 for index in expected)
    total_ok = sum(max(0, delta.get(index, 0)) for index in expected) >= 128
    passed = bool(per_device_ok and total_ok)
    return {
        "method": "nvidia-smi-memory-delta",
        "beforeMiB": baseline,
        "afterMiB": after,
        "deltaMiB": delta,
        "expectedVisibleDeviceCount": tp,
        "childProcessGpuMemoryMiB": gpu_mib_for_pid(pid) if pid else 0,
        "perDeviceMinimumMet": per_device_ok,
        "totalMinimumMet": total_ok,
        "measurable": bool(after),
        # No verified GPU delta while the server answers means a possible CPU
        # fallback; the gate fails closed instead of assuming GPU placement.
        "silentCpuFallbackSuspected": False if passed else (None if not after else True),
        "passed": passed,
    }


def q1_config_identity(candidate: dict) -> str:
    """Identity a stored Q1 receipt must match before it may be reused."""
    return K.sha256_json({
        "candidate": candidate,
        "runtimeArtifact": CAND.runtime_artifact_for(candidate, "smoke"),
        "trivialPrompt": Q1_TRIVIAL_PROMPT,
        "trivialMaxTokens": Q1_TRIVIAL_MAX_TOKENS,
        "stageManifestSha256": STAGE.stage_manifest_sha256(),
    })


def q1_receipt_path(results_dir: Path, candidate_id: str) -> Path:
    return Path(results_dir) / str(candidate_id) / Q1_STAGE / "q1-receipt.json"


def load_reusable_q1_receipt(candidate: dict, results_dir: Path) -> dict | None:
    """Reuse a stored Q1 receipt only when it is completed for this exact config.

    A receipt from a different candidate, runtime artifact or trivial prompt is
    ignored so a resume can never inherit someone else's load proof.
    """
    path = q1_receipt_path(results_dir, str(candidate["id"]))
    if not path.is_file():
        return None
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(receipt, dict) or receipt.get("status") != "completed":
        return None
    if receipt.get("configIdentitySha256") != q1_config_identity(candidate):
        return None
    return receipt


def run_q1_load_probe(
    *,
    candidate: dict,
    results_dir: Path,
    runtime_dir: Path,
    startup_timeout: float,
) -> dict:
    """Load the exact candidate, prove placement, generate once, confirm aliveness.

    Every receipt field below is observed evidence: the owned child process, its
    loopback endpoint, and nvidia-smi. A success is never synthesised, and the
    gate fails closed when placement, identity, generation or aliveness is
    unproven.
    """
    candidate_id = str(candidate["id"])
    receipt_path = q1_receipt_path(results_dir, candidate_id)
    q1_dir = receipt_path.parent
    q1_dir.mkdir(parents=True, exist_ok=True)
    server_log = q1_dir / "q1-server.log.txt"

    receipt: dict = {
        "schemaVersion": 1,
        "receiptKey": Q1_RECEIPT_KEY,
        "gate": "q1",
        "candidate": candidate_id,
        "candidateRevision": candidate.get("revision"),
        "runtime": candidate.get("runtime"),
        "stageManifestSha256": STAGE.stage_manifest_sha256(),
        "configIdentitySha256": q1_config_identity(candidate),
        "status": "running",
        "startedAt": K.now_iso(),
        "evidence": "Q1 is runtime proof only and is never English-quality evidence",
    }
    K.atomic_write_json(receipt_path, receipt)

    baseline = gpu_used_mib()
    try:
        port, port_evidence = allocate_loopback_port(None)
    except PortCollision as collision:  # pragma: no cover - kernel allocation does not collide
        receipt.update({"status": "failed", "reason": str(collision), "portEvidence": collision.evidence})
        K.atomic_write_json(receipt_path, receipt)
        return receipt

    try:
        command, launch_identity = build_q1_command(candidate, port, Path(runtime_dir))
    except BaseException as exc:
        release_port_reservation(port_evidence)
        receipt.update({
            "status": "failed",
            "terminalFailureStage": "launch_config",
            "reason": f"{type(exc).__name__}: {exc}",
            "portEvidence": {k: v for k, v in port_evidence.items() if not k.startswith("_")},
        })
        K.atomic_write_json(receipt_path, receipt)
        return receipt

    env = os.environ.copy()
    tp = int(candidate.get("tensorParallelSize") or 1)
    env["CUDA_VISIBLE_DEVICES"] = "0" if tp == 1 else "0,1"

    server = OwnedServer(
        command,
        host="127.0.0.1",
        port=port,
        expected_model=candidate_id,
        log_path=server_log,
        env=env,
    )
    release_port_reservation(port_evidence)
    server.spawn(port_evidence)
    endpoint = f"http://127.0.0.1:{port}"
    receipt["ownedServer"] = server.ownership_receipt()
    # Issue #57: the roster's only GPU-touching child is this probe, so its
    # server-identity process tree is the ownership evidence the roster may
    # forward to the between-candidate gate. Nothing else is ever claimed.
    receipt["resourceGateOwnedPids"] = sorted(
        owned_process_tree(server.pid) if server.pid is not None else set()
    )
    receipt["launchIdentity"] = launch_identity
    receipt["endpoint"] = endpoint
    receipt["cudaVisibleDevices"] = env["CUDA_VISIBLE_DEVICES"]
    K.atomic_write_json(receipt_path, receipt)

    def fail(stage: str, reason: str) -> dict:
        receipt.update({"status": "failed", "terminalFailureStage": stage, "reason": reason})
        K.atomic_write_json(receipt_path, receipt)
        return receipt

    try:
        ready, readiness = server.wait_ready(
            startup_timeout, require_identity=True, require_ownership=False
        )
        receipt["readiness"] = readiness
        K.atomic_write_json(receipt_path, receipt)
        if not ready:
            return fail(
                "load_or_identity",
                str(readiness.get("error") or readiness.get("status") or "readiness failed"),
            )

        receipt["loadSeconds"] = round(time.monotonic() - server.started_monotonic, 3)
        placement = placement_evidence(candidate, baseline, gpu_used_mib(), server.pid)
        receipt["placement"] = placement
        K.atomic_write_json(receipt_path, receipt)
        if not placement["passed"]:
            return fail(
                "gpu_placement",
                "runtime served but produced no verified GPU placement delta; "
                "treating as a possible silent CPU fallback",
            )

        generation = trivial_generation(endpoint, candidate_id)
        receipt["trivialGeneration"] = generation
        K.atomic_write_json(receipt_path, receipt)
        if generation["status"] != "completed":
            return fail(
                "trivial_generation",
                str(generation.get("error") or f"trivial generation {generation['status']}"),
            )

        alive = server.poll() is None
        health_status, _payload, health_error = http_get_json(endpoint + "/health", timeout=10)
        receipt["runtimeAliveAfterRequest"] = {
            "processAlive": alive,
            "returnCode": server.poll(),
            "healthStatus": health_status,
            "healthError": health_error,
        }
        K.atomic_write_json(receipt_path, receipt)
        if not alive or not (health_status and 200 <= health_status < 300):
            return fail("runtime_alive", "runtime did not survive the trivial generation request")

        receipt.update({
            "status": "completed",
            "completedAt": K.now_iso(),
            "servedModelIdentity": readiness.get("servedModelIdentity"),
        })
        K.atomic_write_json(receipt_path, receipt)
        return receipt
    finally:
        # Cleanup signals only the child this probe spawned.
        # Re-scan the owned tree before terminate so the recorded ownership
        # evidence covers descendants the serving phase may have added. The
        # terminate below still signals only the Popen handle this probe owns.
        receipt["resourceGateOwnedPids"] = sorted(
            set(q1_owned_pids(receipt))
            | (owned_process_tree(server.pid) if server.pid is not None else set())
        )
        cleanup = server.terminate()
        receipt["cleanup"] = cleanup
        receipt["portReleased"] = cleanup.get("portReleased")
        K.atomic_write_json(receipt_path, receipt)
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark-revision", required=True)
    ap.add_argument("--phase", choices=sorted(PHASE_STAGES), default="all")
    ap.add_argument("--candidate", action="append", default=[], help="optional exact candidate id; repeat to choose a subset")
    ap.add_argument("--results-dir", type=Path, default=Path("/kaggle/working/results"))
    ap.add_argument("--preflight", type=Path, default=Path("/kaggle/working/results/preflight.json"))
    ap.add_argument("--preparation-receipt", type=Path, default=Path("/kaggle/working/results/benchmark-preparation.json"))
    ap.add_argument(
        "--runtime-dir",
        type=Path,
        default=CAND.RUNTIME_DIR,
        help="directory of verified pinned runtime receipts; Q1 never installs one",
    )
    ap.add_argument(
        "--q1-startup-timeout",
        type=float,
        default=300.0,
        help="cap for the Q1 load/identity probe; expiry fails the gate closed",
    )
    ap.add_argument(
        "--skip-q1",
        action="store_true",
        help="explicitly non-promotion debug mode: do not run the Q1 load gate",
    )
    ap.add_argument(
        "--gpu-lease-path",
        default=None,
        help=(
            "exclusive GPU lease file held for the duration of canonical execution; "
            "defaults to <results-dir>/gpu-lease.json so the lease file is always writable"
        ),
    )
    ap.add_argument(
        "--no-gpu-lease",
        action="store_true",
        help="explicitly non-comparable debug mode: skip the exclusive GPU lease",
    )
    ap.add_argument(
        "--no-resource-gate",
        action="store_true",
        help=(
            "explicitly non-comparable debug mode: skip the fail-closed GPU "
            "resource-cleanliness gate between candidates"
        ),
    )
    ap.add_argument("--probe-mtp-smoke", action="store_true", help="after ordinary smoke success, probe only roster-declared MTP methods")
    ap.add_argument(
        "--timeout-seconds",
        type=float,
        default=None,
        help="per-candidate-stage cap; on expiry only the owned process group is terminated",
    )
    ap.add_argument(
        "--allow-dirty-tree",
        action="store_true",
        help="explicitly non-promotion debug mode; summaries are labeled non-comparable",
    )
    ap.add_argument(
        "--exploratory-tasks",
        action="store_true",
        help="explicitly non-promotion: allow unregistered stage task overrides",
    )
    args = ap.parse_args()

    args.results_dir.mkdir(parents=True, exist_ok=True)

    # Issue #40: bind the whole sweep to the actual checked-out commit before
    # any model/runtime work happens in any child stage.
    repo_root = Path(K._git(HERE, "rev-parse", "--show-toplevel"))
    try:
        git_identity = K.verify_git_identity(
            repo_root,
            args.benchmark_revision,
            relevant_prefix=CAND.BENCHMARK_RELEVANT_PREFIX,
            require_clean=not args.allow_dirty_tree,
            preparation_receipt=args.preparation_receipt,
        )
    except K.CheckpointError as exc:
        raise SystemExit(f"benchmark identity guard rejected this sweep: {exc}")
    print(
        f"verified sweep identity: HEAD={git_identity.head} "
        f"promotionEligible={git_identity.promotion_eligible}",
        flush=True,
    )

    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    available = [row["id"] for row in roster["candidates"]]
    selected = args.candidate or available
    unknown = [x for x in selected if x not in available]
    if unknown:
        raise SystemExit(f"unknown candidates: {unknown}; allowed={available}")

    by_id = {row["id"]: row for row in roster["candidates"]}
    provenance = roster_provenance(
        benchmark_revision=args.benchmark_revision,
        phase=args.phase,
        selected=selected,
        preflight=args.preflight,
        preparation_receipt=args.preparation_receipt,
        candidates=by_id,
        git_identity=git_identity,
    )

    orchestration_path = args.results_dir / "roster-orchestration.json"
    # The roster checkpoint is what stops a killed sweep from re-running (or
    # reordering) candidate-stages it already finished.
    roster_checkpoint_path = args.results_dir / "roster-orchestration.checkpoint.json"

    def publish(state: str, *, terminal: bool, reason: str | None = None) -> None:
        orchestration["status"] = state
        orchestration["terminal"] = terminal
        if reason:
            orchestration["terminalReason"] = reason
        orchestration["updatedAt"] = K.now_iso()
        K.atomic_write_json(orchestration_path, orchestration)

    # Fail once, before model/runtime downloads, if the task corpus is stale or partial.
    prep_log = args.results_dir / "benchmark-preparation-verification.log.txt"
    prep_outcome = run_unit(
        unit_id="benchmark-preparation-verification",
        cmd=[
            sys.executable, str(VERIFY_PREP),
            "--receipt", str(args.preparation_receipt),
            "--benchmark-revision", args.benchmark_revision,
        ],
        provenance=provenance,
        log=prep_log,
        checkpoint_path=args.results_dir / "benchmark-preparation-verification.checkpoint.json",
        manifest=None,
        summary_path=None,
    )
    if prep_outcome.returncode != 0:
        raise SystemExit(
            "prepared benchmark verification failed; do not start model evaluation "
            f"(terminal={prep_outcome.status})"
        )

    if not args.preflight.is_file():
        raise SystemExit(f"missing real-Kaggle T4 preflight {args.preflight}; do not start model evaluation")
    preflight = json.loads(args.preflight.read_text(encoding="utf-8"))
    if not preflight.get("promotionEligibleEnvironment"):
        raise SystemExit("Kaggle preflight is not promotion-eligible; do not start model evaluation")

    # The roster's own preflight check is the Q0 environment gate. Record it as
    # the q0 receipt so the ladder has a real upstream receipt to point at.
    q0_receipt = {
        "schemaVersion": 1,
        "receiptKey": Q0_RECEIPT_KEY,
        "gate": "q0",
        "status": "completed" if preflight.get("promotionEligibleEnvironment") else "failed",
        "preflight": str(args.preflight),
        "preflightSha256": K.sha256_file(args.preflight),
        "evidence": "promotionEligibleEnvironment from the real-Kaggle preflight artifact",
        "recordedAt": K.now_iso(),
    }
    K.atomic_write_json(args.results_dir / "q0-receipt.json", q0_receipt)

    # Canonical execution is sequential by design, so the GPU set is held under an
    # exclusive lease for the whole sweep. The lease is advisory across our own
    # processes; the real nvidia-smi check still runs underneath it. Acquisition
    # failure is a hard stop, and the lease is always released in `finally`.
    gpu_lease = None
    # Default the lease file under the results directory so it is always writable
    # and always co-located with the receipts this sweep produces.
    lease_path = Path(args.gpu_lease_path) if args.gpu_lease_path else (
        args.results_dir / "gpu-lease.json"
    )
    # A host with no CUDA driver cannot run any candidate stage, so there is no GPU
    # to lease. That is the only honest "non-GPU local path" branch: it is detected
    # from the driver rather than assumed, and a GPU host never skips the lease.
    gpu_present = bool(gpu_used_mib())
    gpu_lease_evidence: dict = {
        "acquired": False,
        "path": str(lease_path),
        "gpuDetected": gpu_present,
    }
    if args.no_gpu_lease:
        gpu_lease_evidence["skipped"] = "explicit --no-gpu-lease debug mode (non-comparable)"
        print(
            "WARNING skipping exclusive GPU lease; this sweep is not comparable",
            flush=True,
        )
    elif not gpu_present:
        gpu_lease_evidence["skipped"] = (
            "no CUDA device detected, so there is no GPU to lease (non-GPU local path)"
        )
        print(
            "no CUDA device detected; skipping the exclusive GPU lease (non-GPU local path)",
            flush=True,
        )
    else:
        from kaggle_gpu_resource_gate import GpuLease, LeaseUnavailable

        gpu_lease = GpuLease(path=lease_path)
        try:
            gpu_lease.acquire(owner=f"roster-{os.getpid()}")
        except LeaseUnavailable as unavailable:
            raise SystemExit(
                f"canonical execution refuses to start without the exclusive GPU lease: "
                f"{unavailable}"
            )
        gpu_lease_evidence = {
            "acquired": True,
            "path": str(lease_path),
            "gpuDetected": gpu_present,
            "owner": gpu_lease.owner,
            "holder": gpu_lease.metadata,
            "acquiredAt": K.now_iso(),
        }
        print(
            f"acquired exclusive GPU lease: {gpu_lease_evidence['path']}",
            flush=True,
        )

    # Issue #57: the exclusive lease above is advisory across our own processes;
    # this gate is the real nvidia-smi evidence and runs independently of it,
    # because unrelated notebook code can launch CUDA work without ever taking
    # the lease. The gate is skipped only where there is provably no GPU to
    # check, or under an explicit non-comparable debug flag -- never silently.
    if args.no_resource_gate:
        resource_gate_enabled = False
        resource_gate_skip_reason = "explicit --no-resource-gate debug mode (non-comparable)"
    elif not gpu_present:
        resource_gate_enabled = False
        resource_gate_skip_reason = (
            "no CUDA device detected, so there is no GPU resource to gate (non-GPU local path)"
        )
    else:
        resource_gate_enabled = True
        resource_gate_skip_reason = None
    resource_gate_evidence = {
        "enabled": resource_gate_enabled,
        "leasePath": str(lease_path),
        "leaseAcquired": bool(gpu_lease_evidence.get("acquired")),
        "blockedCategory": GATE.BLOCKED_CATEGORY,
        "foreignProcessPolicy": "recorded and blocked, never signalled by the roster",
        "ownershipEvidenceSource": (
            "kaggle_server_identity.owned_process_tree over PIDs this supervisor launched"
        ),
    }
    if resource_gate_skip_reason:
        resource_gate_evidence["skipped"] = resource_gate_skip_reason
        print(f"WARNING {resource_gate_skip_reason}", flush=True)

    orchestration = {
        "schemaVersion": ORCHESTRATION_SCHEMA_VERSION,
        "checkpointSchemaVersion": K.SCHEMA_VERSION,
        "benchmarkRevision": args.benchmark_revision,
        "preparationReceipt": str(args.preparation_receipt),
        "preparationVerificationLog": str(prep_log),
        "preflight": str(args.preflight),
        "phase": args.phase,
        "selectedCandidates": selected,
        "stages": list(PHASE_STAGES[args.phase]),
        "q0Receipt": str(args.results_dir / "q0-receipt.json"),
        "q0ReceiptKey": Q0_RECEIPT_KEY,
        "gpuLease": gpu_lease_evidence,
        "resourceGate": resource_gate_evidence,
        "q1Enabled": not args.skip_q1,
        "provenance": provenance.to_dict(),
        "status": "running",
        "terminal": False,
        "createdAt": K.now_iso(),
        "candidates": [],
    }
    orchestration["updatedAt"] = orchestration["createdAt"]

    # Resume support: a prior roster artifact is authoritative for which units
    # already reached a terminal state, so a killed sweep continues rather than
    # re-running completed candidates.
    prior_records: dict[str, dict] = {}
    if orchestration_path.is_file():
        try:
            prior = json.loads(orchestration_path.read_text(encoding="utf-8"))
            if isinstance(prior, dict):
                if prior.get("schemaVersion") != ORCHESTRATION_SCHEMA_VERSION:
                    raise SystemExit(
                        f"roster-orchestration.json has schemaVersion "
                        f"{prior.get('schemaVersion')!r}, expected {ORCHESTRATION_SCHEMA_VERSION}; "
                        "refusing to resume"
                    )
                if prior.get("provenance") != provenance.to_dict():
                    raise SystemExit(
                        "existing roster-orchestration.json provenance does not match this "
                        "run; refusing to resume"
                    )
                for record in prior.get("candidates") or []:
                    candidate_id = record.get("candidate")
                    for entry in list(record.get("stages") or []) + list(record.get("mtpSmoke") or []):
                        key = (candidate_id, entry.get("stage"), entry.get("decode", "normal"),
                               entry.get("method"))
                        prior_records[str(key)] = entry
                orchestration["createdAt"] = prior.get("createdAt") or orchestration["createdAt"]
                print(
                    f"resuming roster sweep from existing {orchestration_path}",
                    flush=True,
                )
        except json.JSONDecodeError:
            preserved = orchestration_path.with_name(orchestration_path.name + ".corrupt")
            orchestration_path.replace(preserved)
            print(
                f"existing orchestration artifact was unreadable; preserved at {preserved}",
                flush=True,
            )
    publish("running", terminal=False)

    resume_available = False
    incomplete_reason: str | None = None

    # Issue #57 sweep state. `known_owned_pids` is the set of PIDs this
    # supervisor provably launched for the candidate now in flight: the Q1
    # probe's server-identity process tree plus each stage unit's reported owned
    # process group. It is forwarded to that candidate's post-candidate
    # quarantine so its own residue is attributable rather than foreign.
    # Everything else on the GPU is foreign/unknown: recorded, never signalled.
    # `handoff_blocker` is set by a candidate whose post-candidate quarantine was
    # not clean, and blocks the *next* candidate before any model work, because
    # leftover VRAM would otherwise resurface as the next candidate's false OOM.
    known_owned_pids: set[int] = set()
    handoff_blocker: dict | None = None
    gate_blocked_sweep = False

    for candidate_id in selected:
        candidate = by_id[candidate_id]
        record = {"candidate": candidate_id, "stages": [], "mtpSmoke": [], "gates": {}}
        orchestration["candidates"].append(record)
        publish("running", terminal=False)

        ordinary_smoke_passed = False
        candidate_blocked = False

        # --- Issue #57: prove a clean handoff *into* this candidate ----------
        # Nothing model-related may run until the required GPUs are clean. A
        # blocked gate is infrastructure contamination, never candidate
        # capacity, so this candidate is skipped and recorded with the
        # contamination category rather than dispatched and reported as an OOM.
        gate_record: dict
        if not resource_gate_enabled:
            gate_record = {
                "status": "skipped",
                "reason": resource_gate_skip_reason,
                "allowed": True,
            }
        elif handoff_blocker is not None:
            gate_record = {
                "status": "blocked",
                "category": GATE.BLOCKED_CATEGORY,
                "allowed": False,
                "blockingReasons": [
                    "previous_candidate_handoff_not_clean:"
                    f"{handoff_blocker.get('candidate')}"
                ],
                "inheritedFrom": {
                    "candidate": handoff_blocker.get("candidate"),
                    "verdict": handoff_blocker.get("verdict"),
                    "blockingReasons": handoff_blocker.get("blockingReasons"),
                },
                "candidateEvidenceEligible": False,
                "note": (
                    "the previous candidate did not hand back a clean GPU, so this "
                    "candidate is not attempted; no capacity conclusion is allowed"
                ),
            }
        else:
            gate_record = pre_candidate_resource_gate(
                candidate=candidate,
                residue_pids=[],
            )
            gate_record["status"] = "passed" if gate_record["allowed"] else "blocked"
        record["resourceGate"] = {"preCandidate": gate_record}
        gate_artifact = args.results_dir / candidate_id / "resource-gate.json"
        K.atomic_write_json(
            gate_artifact,
            {
                "candidate": candidate_id,
                "blockedCategory": GATE.BLOCKED_CATEGORY,
                "resourceGate": record["resourceGate"],
            },
        )
        # The forwarded residue set applies to exactly one gate evaluation.
        known_owned_pids = set()
        handoff_blocker = None
        if not gate_record.get("allowed", True):
            candidate_blocked = True
            gate_blocked_sweep = True
            print(
                f"resource gate blocked {candidate_id}: "
                f"category={gate_record.get('category')} "
                f"reasons={gate_record.get('blockingReasons')}; no stage is dispatched "
                "and no candidate capacity conclusion is recorded",
                flush=True,
            )
        elif gate_record.get("status") == "passed":
            print(
                f"resource gate clean before {candidate_id} "
                f"(TP={gate_record.get('tensorParallel')})",
                flush=True,
            )

        # Issue #49: the Q1 load/placement/trivial-generation/runtime-alive gate
        # runs per candidate before any stage. A Q1 failure blocks that candidate
        # from Q2 onward, and the real receipt is passed forward so the
        # dispatcher resolves its prerequisite rather than failing closed.
        prior_receipts = {Q0_RECEIPT_KEY: q0_receipt}
        reusable_q1 = None
        if args.skip_q1:
            q1_receipt = {
                "status": "skipped",
                "reason": "explicit --skip-q1 debug mode (non-comparable)",
            }
        else:
            reusable_q1 = load_reusable_q1_receipt(candidate, args.results_dir)
            if reusable_q1 is not None:
                print(
                    f"reusing completed Q1 receipt for {candidate_id}: "
                    f"{q1_receipt_path(args.results_dir, candidate_id)}",
                    flush=True,
                )
            q1_receipt = reusable_q1 or run_q1_load_probe(
                candidate=candidate,
                results_dir=args.results_dir,
                runtime_dir=args.runtime_dir,
                startup_timeout=args.q1_startup_timeout,
            )
        record["gates"][Q1_RECEIPT_KEY] = q1_receipt
        record["q1"] = {
            "status": q1_receipt.get("status"),
            "terminalFailureStage": q1_receipt.get("terminalFailureStage"),
            "reason": q1_receipt.get("reason"),
            "loadSeconds": q1_receipt.get("loadSeconds"),
            "placementPassed": (q1_receipt.get("placement") or {}).get("passed"),
            "trivialGenerationStatus": (q1_receipt.get("trivialGeneration") or {}).get("status"),
            "runtimeAliveAfterRequest": (q1_receipt.get("runtimeAliveAfterRequest") or {}).get("processAlive"),
            "receipt": str(q1_receipt_path(args.results_dir, candidate_id)),
            "reused": reusable_q1 is not None,
        }
        prior_receipts_file = args.results_dir / "orchestration-logs" / f"{candidate_id}-gate-receipts.json"
        K.atomic_write_json(prior_receipts_file, prior_receipts)
        publish("running", terminal=False)
        # Only a real Q1 failure blocks later gates. `--skip-q1` is an explicit
        # non-comparable debug mode: it proceeds with the gate marked skipped so it
        # can never read as either a passed or a failed gate.
        q1_skipped = q1_receipt.get("status") == "skipped"
        if q1_receipt.get("status") != "completed" and not q1_skipped:
            candidate_blocked = True
            print(
                f"Q1 gate not met for {candidate_id}: status={q1_receipt.get('status')} "
                f"stage={q1_receipt.get('terminalFailureStage')}; later gates are blocked",
                flush=True,
            )
        # Issue #57: ownership evidence for the post-candidate quarantine is
        # exactly the PIDs this candidate launched -- the Q1 probe's
        # server-identity process tree, plus every stage unit's reported owned
        # process group. Everything else stays foreign/unknown and is only ever
        # recorded and blocked, never signalled.
        known_owned_pids = set(q1_owned_pids(q1_receipt))

        for stage in PHASE_STAGES[args.phase]:
            if candidate_blocked:
                record["stages"].append({"stage": stage, "terminalStatus": "skipped_due_to_prior_failure"})
                publish("running", terminal=False)
                continue
            log = args.results_dir / "orchestration-logs" / f"{candidate_id}-{stage}.log.txt"
            cmd = [
                sys.executable, str(DISPATCH), candidate_id,
                "--stage", stage,
                "--benchmark-revision", args.benchmark_revision,
                "--results-dir", str(args.results_dir),
            ]
            if args.allow_dirty_tree:
                cmd.append("--allow-dirty-tree")
            if args.exploratory_tasks:
                cmd.append("--exploratory-tasks")
            # Pass the real Q0/Q1 receipts so the dispatcher resolves this
            # stage's gate prerequisites instead of refusing to launch.
            cmd += ["--prior-receipts", str(prior_receipts_file)]
            if q1_skipped:
                # Debug mode only: proceed past the deliberately skipped gate and
                # let the dispatcher record the run as non-comparable.
                cmd.append("--allow-unmet-prerequisites")
            runtime = candidate.get("runtime")
            manifest = stage_manifest(stage)
            summary_path = CAND.summary_path_for(
                args.results_dir, candidate_id, stage, runtime, "normal"
            )
            stage_provenance = CAND.build_provenance(
                candidate=candidate,
                benchmark_revision=args.benchmark_revision,
                stage=stage,
                decode="normal",
                preflight=args.preflight,
                runtime_artifact=CAND.runtime_artifact_for(candidate, stage),
                manifest=manifest,
                git_identity=git_identity,
            )
            outcome = run_unit(
                unit_id=f"{candidate_id}/{stage}/normal",
                cmd=cmd,
                provenance=stage_provenance,
                log=log,
                checkpoint_path=summary_path.with_suffix(".checkpoint.json"),
                manifest=manifest,
                summary_path=summary_path,
                timeout_seconds=args.timeout_seconds,
                stage=stage,
            )
            entry = {
                "stage": stage,
                "terminalStatus": outcome.status,
                "terminalReason": outcome.reason,
                "returnCode": outcome.returncode,
                "log": str(log),
                "checkpoint": str(outcome.checkpoint_path),
                "cleanup": outcome.cleanup.to_dict(),
                # Issue #57: the exact PIDs this stage launched. The
                # between-candidate quarantine forwards them to the GPU gate so
                # owned residue can be reaped while every other GPU process
                # stays foreign, recorded, and never signalled.
                "ownedPids": sorted(outcome.owned_pids),
            }
            record["stages"].append(entry)
            known_owned_pids |= set(outcome.owned_pids)
            rebuild_matrix(args.results_dir, args.benchmark_revision)
            publish("running", terminal=False)
            if stage == "smoke" and outcome.status == "completed":
                ordinary_smoke_passed = True
            if outcome.status == "interrupted_resume_available":
                resume_available = True
                incomplete_reason = incomplete_reason or f"{candidate_id}/{stage}: {outcome.reason}"
            elif outcome.status != "completed":
                candidate_blocked = True

        if args.probe_mtp_smoke and ordinary_smoke_passed and candidate.get("runtime") == "vllm":
            for method in candidate.get("mtpMethodsToProbe") or []:
                log = args.results_dir / "orchestration-logs" / f"{candidate_id}-smoke-{method}.log.txt"
                cmd = [
                    sys.executable, str(DISPATCH), candidate_id,
                    "--stage", "smoke", "--decode", method,
                    "--speculative-tokens", "1",
                    "--benchmark-revision", args.benchmark_revision,
                    "--results-dir", str(args.results_dir),
                ]
                if args.allow_dirty_tree:
                    cmd.append("--allow-dirty-tree")
                if args.exploratory_tasks:
                    cmd.append("--exploratory-tasks")
                smoke_manifest = stage_manifest("smoke")
                smoke_summary = CAND.summary_path_for(
                    args.results_dir, candidate_id, "smoke", "vllm", method
                )
                mtp_provenance = CAND.build_provenance(
                    candidate=candidate,
                    benchmark_revision=args.benchmark_revision,
                    stage="smoke",
                    decode=method,
                    preflight=args.preflight,
                    runtime_artifact=CAND.runtime_artifact_for(candidate, "smoke"),
                    manifest=smoke_manifest,
                    git_identity=git_identity,
                )
                outcome = run_unit(
                    unit_id=f"{candidate_id}/smoke/{method}",
                    cmd=cmd,
                    provenance=mtp_provenance,
                    log=log,
                    checkpoint_path=smoke_summary.with_suffix(".checkpoint.json"),
                    manifest=smoke_manifest,
                    summary_path=smoke_summary,
                    timeout_seconds=args.timeout_seconds,
                    stage="smoke",
                )
                record["mtpSmoke"].append({
                    "method": method,
                    "terminalStatus": outcome.status,
                    "terminalReason": outcome.reason,
                    "returnCode": outcome.returncode,
                    "log": str(log),
                    "checkpoint": str(outcome.checkpoint_path),
                    "cleanup": outcome.cleanup.to_dict(),
                    "ownedPids": sorted(outcome.owned_pids),
                })
                known_owned_pids |= set(outcome.owned_pids)
                rebuild_matrix(args.results_dir, args.benchmark_revision)
                publish("running", terminal=False)

        # --- Issue #57: verify the handoff *out of* this candidate ----------
        # Runs whether or not the candidate itself passed, because contamination
        # can arrive mid-run and invalidate this candidate's timings. The result
        # decides whether the next candidate may start at all, and is never
        # turned into this candidate's OOM/capacity story.
        if resource_gate_enabled:
            quarantine = quarantine_candidate_handoff(
                candidate=candidate,
                baseline=gate_record.get("baseline") or {},
                owned_pids=sorted(known_owned_pids),
                # Never carry owned PIDs forward to a later candidate. A PID from
                # an earlier candidate can be recycled by an unrelated process,
                # and forwarding it would let the gate classify that unrelated
                # process as reapable residue and signal it. This candidate's
                # own PIDs are also not promoted to residue: the gate reports a
                # surviving one as still-owned and blocks the next candidate,
                # which fails closed without ever signalling a stranger.
                residue_pids=[],
            )
            known_owned_pids = set()
            record.setdefault("resourceGate", {})["postCandidate"] = quarantine
            K.atomic_write_json(
                gate_artifact,
                {
                    "candidate": candidate_id,
                    "blockedCategory": GATE.BLOCKED_CATEGORY,
                    "resourceGate": record["resourceGate"],
                },
            )
            if quarantine["clean"]:
                print(
                    f"resource quarantine clean after {candidate_id}",
                    flush=True,
                )
            else:
                gate_blocked_sweep = True
                handoff_blocker = {
                    "candidate": candidate_id,
                    "verdict": quarantine.get("verdict"),
                    "blockingReasons": quarantine.get("blockingReasons"),
                }
                record["terminalStatus"] = GATE.BLOCKED_CATEGORY
                record["terminalFailureClass"] = "infrastructure_blocked"
                print(
                    f"resource quarantine NOT clean after {candidate_id}: "
                    f"reasons={quarantine.get('blockingReasons')}; the next candidate "
                    "is blocked and this candidate's timings are not comparable",
                    flush=True,
                )
        publish("running", terminal=False)

    try:
        rebuild_matrix(args.results_dir, args.benchmark_revision)
        if resume_available:
            final_status = "interrupted_resume_available"
            reason = incomplete_reason or "one or more candidate stages are resumable"
        elif gate_blocked_sweep:
            # A contaminated required GPU is an infrastructure failure, never a
            # benchmark result: the sweep never measured the candidates it
            # planned, so it can be neither completed nor resumable work.
            final_status = "infrastructure_failed"
            reason = f"resource gate blocked qualification with {GATE.BLOCKED_CATEGORY}"
        else:
            final_status = "completed"
            reason = "every planned candidate-stage reached a terminal state"
        orchestration["complete"] = final_status == "completed"
        publish(final_status, terminal=True, reason=reason)
        print(json.dumps({
            "status": final_status,
            "terminal": True,
            "terminalReason": reason,
            "artifact": str(orchestration_path),
            "checkpoint": str(roster_checkpoint_path),
        }, indent=2))
        if final_status != "completed":
            raise SystemExit(75 if final_status == "interrupted_resume_available" else 2)
    finally:
        # The GPU lease is released on every exit path, including a failure or a
        # KeyboardInterrupt, so a crashed sweep never leaves the GPU locked.
        if gpu_lease is not None:
            released = gpu_lease.release()
            orchestration["gpuLease"] = {**orchestration.get("gpuLease", {}), "released": released}
            try:
                K.atomic_write_json(orchestration_path, orchestration)
            except Exception:
                pass
            print(f"released GPU lease: {released}", flush=True)


if __name__ == "__main__":
    main()
