#!/usr/bin/env python3
"""Mechanical Kaggle runner for pinned vLLM roster candidates.

The wrapper chooses nothing except a predeclared batch fallback on CUDA OOM. It
preserves every attempt, supports only roster-declared speculative methods, and
never mutates model identity or benchmark prompts.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kaggle_failure_taxonomy import classify
from kaggle_batch_policy import CANONICAL_LADDER
import kaggle_gpu_resource_gate as gpu_resource_gate
from kaggle_hub_artifact_preflight import inspect_hub_artifact
import kaggle_promotion_gate as promotion_gate
from kaggle_server_identity import command_identity, owned_process_tree, utc_now
from kaggle_stage_identity import PRODUCT_STAGES, classify_oom

HERE = Path(__file__).resolve().parent
ROSTER = HERE / "kaggle-candidate-roster.json"
RUNNER = HERE / "run-english-core-vllm.py"
DEFAULT_ENGLISH_TASKS = HERE / "english-core-fixed-screen.jsonl"
DEFAULT_WORD_STUDIO_TASKS = HERE / "word-studio-strength.jsonl"
DEFAULT_TRANSFORM_TASKS = HERE / "word-studio-transform.jsonl"

#: The one canonical English-screen generation-batch ladder (Issue #47).
#:
#: Frozen before any candidate result was observed. `64` is deliberately
#: omitted: batch size here is vLLM `max_num_seqs`, so 64 concurrent sequences at
#: the frozen 8192-token context bound exceed the 16 GB T4 KV-cache budget for
#: every roster candidate. Starting there would spend one extra model-load plus
#: generation cycle to learn nothing that a 32-way attempt does not. This
#: constant is the single source of truth: the hardening document and
#: `test_kaggle_batch_policy.py` both consume it, so docs and code cannot
#: disagree. It is generation-only; load feasibility is a separate state.
CANONICAL_GENERATION_LADDER = (32, 16, 8, 4, 1)

if tuple(CANONICAL_GENERATION_LADDER) != tuple(CANONICAL_LADDER):
    # The literal above stays so the runbook-consistency test can read the
    # documented source; this guard keeps it from drifting away from the shared
    # policy both wrappers consume.
    raise SystemExit(
        "canonical ladder drift: this wrapper declares "
        f"{list(CANONICAL_GENERATION_LADDER)} but kaggle_batch_policy declares "
        f"{list(CANONICAL_LADDER)}"
    )

#: Product stages are pinned to a single batch and never traverse the English
#: screen ladder (Issue #47). Recorded explicitly so a product run cannot be
#: mistaken for one that "stepped down" the ladder.
PRODUCT_BATCH_POLICY = (1,)

#: Transient allocator/runtime faults that are eligible for one exact-config
#: retry after cleanup. This is explicitly NOT batch fallback: the retry keeps
#: the same frozen configuration and both attempts stay in the record.
TRANSIENT_RETRY_CATEGORIES = frozenset({
    "cuda_memory_fragmentation",
    "runtime_crash",
})

#: How many exact-config transient retries are permitted before the attempt is
#: treated as a deterministic capacity failure.
MAX_TRANSIENT_RETRIES = 1


def load_progressive_contract() -> Any:
    """Load the canonical progressive timing contract from the core vLLM runner.

    Runner filenames are hyphenated CLI scripts and cannot be imported by name, so
    the core runner is loaded by path. Both the wrapper summary and the child
    runner then read one definition of the first-1/3/10 usable-option schema.
    """
    path = Path(__file__).resolve().parent / "run-english-core-vllm.py"
    spec = importlib.util.spec_from_file_location("pari_english_core_vllm_runner", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load the shared progressive timing contract from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROGRESSIVE = load_progressive_contract()
RUNTIME_DIR = Path("/kaggle/working/pari-runtimes")
VLLM_RUNTIME = "vllm-0.30.0-cu129-linux-x86_64"


def resolve_isolated_runtime(
    runtime_dir: Path,
    artifact_id: str,
) -> tuple[Path, dict[str, str], dict[str, Any]]:
    """Resolve the dedicated venv interpreter and env for the frozen runtime.

    Issue #41: the child must execute with the isolated interpreter recorded in
    the install receipt, never ``sys.executable``, so a mutable Kaggle global
    torch/vLLM cannot shadow the frozen dependency closure. This fails closed: a
    missing receipt, a receipt without a ``dedicated_venv`` environment, a
    missing interpreter, or an interpreter resolving outside the recorded venv
    root all stop the run before any model work.
    """
    receipt_path = Path(runtime_dir) / (artifact_id + ".receipt.json")
    if not receipt_path.is_file():
        raise SystemExit(
            "missing runtime receipt " + str(receipt_path)
            + "; run install-kaggle-prebuilt-runtime.py and"
            " verify-kaggle-prebuilt-runtime.py before any model work"
        )
    receipt = load_json(receipt_path)
    environment = receipt.get("environment") or {}
    if environment.get("kind") != "dedicated_venv":
        raise SystemExit(
            "runtime receipt " + str(receipt_path)
            + " does not record a dedicated_venv environment; the canonical vLLM"
            " path refuses to execute against a mutable global environment"
        )
    python_exe = environment.get("pythonExecutable") or ""
    venv_root = environment.get("venvPath") or ""
    if not python_exe or not venv_root:
        raise SystemExit(
            "runtime receipt " + str(receipt_path) + " omits the venv interpreter identity"
        )
    python_path = Path(python_exe)
    if not python_path.is_file():
        raise SystemExit("isolated interpreter from receipt is missing: " + str(python_path))
    if not os.path.realpath(python_path).startswith(os.path.realpath(venv_root)):
        raise SystemExit(
            "isolated interpreter " + str(python_path)
            + " resolves outside the recorded venv " + str(venv_root)
            + "; refusing to execute"
        )
    child_env = dict(os.environ)
    child_env["VIRTUAL_ENV"] = venv_root
    child_env["PATH"] = str(python_path.parent) + os.pathsep + child_env.get("PATH", "")
    child_env["PYTHONNOUSERSITE"] = "1"
    child_env.pop("PYTHONPATH", None)
    return python_path, child_env, receipt


def run_owned_child(
    cmd: list[str],
    *,
    timeout: float | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, str, dict[str, Any]]:
    """Run the child runner we spawned and record ownership evidence for it.

    Issue #42: this wrapper owns exactly one child at a time, so it launches with
    its own process group and records PID/PGID/command identity. On timeout the
    cleanup signals only that handle — never a process found by name or port — so
    an unrelated server is never killed.
    """
    started_at = utc_now()
    started_monotonic = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
    )
    receipt: dict[str, Any] = {
        "schemaVersion": 1,
        "runNonce": RUN_NONCE,
        "childPid": proc.pid,
        "ownProcessGroup": True,
        "command": list(cmd),
        "commandIdentitySha256": command_identity(cmd),
        "startedAt": started_at,
        "startMonotonicSeconds": started_monotonic,
        "signalledPids": [],
        "cleanupPolicy": "only the Popen handle created by this wrapper is signalled",
    }
    try:
        receipt["childPgid"] = os.getpgid(proc.pid)
    except OSError:
        receipt["childPgid"] = None
    receipt["ownedPids"] = sorted(owned_process_tree(proc.pid))
    timed_out = False
    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        receipt["signalledPids"].append(proc.pid)
        receipt["signal"] = "SIGKILL"
        try:
            child_pgid = receipt.get("childPgid")
            if child_pgid is not None and child_pgid != os.getpgid(0):
                import signal as signal_module

                os.killpg(child_pgid, signal_module.SIGKILL)
            else:
                proc.kill()
        except OSError as exc:
            receipt["signalError"] = f"{type(exc).__name__}: {exc}"
        stdout, _ = proc.communicate()
    receipt["returnCode"] = proc.returncode
    receipt["ownedPids"] = sorted(set(receipt["ownedPids"]) | owned_process_tree(proc.pid))
    receipt["timedOut"] = timed_out
    receipt["elapsedSeconds"] = round(time.monotonic() - started_monotonic, 3)
    receipt["finishedAt"] = utc_now()
    return int(proc.returncode or 0), stdout or "", receipt


RUN_NONCE = uuid.uuid4().hex


@dataclass(frozen=True)
class AttemptDecision:
    """What the wrapper must do after one batch attempt.

    Kept as a pure function of the attempt outcome so the retry taxonomy is
    testable without a GPU and so the ladder logic has exactly one definition.
    """

    action: str
    reason: str
    oom_class: str | None = None
    transient_retry: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "oomClass": self.oom_class,
            "transientRetry": self.transient_retry,
        }


def decide_after_attempt(
    *,
    returncode: int,
    categories: list[str],
    batch: int,
    transient_retries_used: int,
) -> AttemptDecision:
    """Classify one attempt outcome into exactly one next action.

    The load/generation distinction is the whole point of Issue #47:

    * ``cuda_oom_load`` stops the configuration outright. Batch size is a
      generation parameter and does not change model construction, so walking
      the ladder after a load OOM would reload an identical failing model and
      burn GPU time to learn nothing.
    * ``cuda_oom_generate`` alone walks the frozen generation ladder, and only
      until it is exhausted.
    * A transient allocator/runtime fault earns one exact-config retry, which
      keeps every frozen setting identical and is recorded separately from any
      batch step-down.
    """
    if returncode == 0:
        return AttemptDecision("complete", "child exited 0", oom_class=None)

    oom_class = classify_oom(list(categories))
    if oom_class == "load":
        return AttemptDecision(
            "stop_load_capacity",
            (
                "model load OOM at batch %d; batch size does not affect model "
                "construction, so this frozen configuration is not feasible. "
                "A configuration-level fallback (for example an explicitly "
                "roster-declared TP2 candidate) is required instead." % batch
            ),
            oom_class="load",
        )

    if oom_class == "generate":
        if batch == 1:
            return AttemptDecision(
                "stop_generation_capacity",
                (
                    "generation OOM at batch 1; the generation ladder is exhausted, "
                    "so this frozen model configuration cannot run on this GPU"
                ),
                oom_class="generate",
            )
        return AttemptDecision(
            "step_down_batch",
            "generation OOM at batch %d; step down the frozen generation ladder" % batch,
            oom_class="generate",
        )

    if set(categories) & TRANSIENT_RETRY_CATEGORIES and transient_retries_used < MAX_TRANSIENT_RETRIES:
        return AttemptDecision(
            "retry_same_config",
            (
                "transient allocator/runtime fault at batch %d; retry the identical "
                "frozen configuration once after cleanup (not a batch step-down)" % batch
            ),
            oom_class=None,
            transient_retry=True,
        )

    return AttemptDecision(
        "stop_runtime_failure",
        "non-OOM runtime failure at batch %d: %s" % (batch, list(categories)),
        oom_class=None,
    )


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def classify_child_failure(text: str) -> tuple[str, list[str]]:
    """Classify a combined child-runner failure with an explicit safe stage.

    The child emits a load boundary before constructing vLLM and emits completed
    batch checkpoints only after generation. When the failure is before the
    first completed batch, default to load: retrying the batch ladder without
    proof of a generation-stage OOM would reload the same model repeatedly.
    """
    lowered = text.lower()
    if "completed " in lowered or "done status=" in lowered or any(
        marker in lowered for marker in ("during generation", "kv cache", "request output")
    ):
        stage = "generate"
    else:
        stage = "load"
    return stage, classify(text, stage=stage)


def pre_run_resource_gate(
    *, tensor_parallel: int, run_identity: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Require a clean physical GPU baseline before loading a candidate."""
    state = gpu_resource_gate.sample_gpu_state()
    pre_run = gpu_resource_gate.require_clean_pre_run(
        state=state,
        tensor_parallel=tensor_parallel,
        run_identity=run_identity,
    )
    return state, pre_run


def post_stage_resource_gate(
    *, tensor_parallel: int, baseline: dict[str, Any], owned_pids: list[int]
) -> dict[str, Any]:
    """Quarantine one completed owned child attempt against the clean baseline."""
    return gpu_resource_gate.quarantine_after_stage(
        tensor_parallel=tensor_parallel,
        baseline=baseline,
        owned_pids=owned_pids,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate_id")
    ap.add_argument("--stage", choices=["smoke", "full", "word-studio", "transform"], required=True)
    ap.add_argument("--decode", choices=["normal", "mtp", "qwen3_next_mtp"], default="normal")
    ap.add_argument("--speculative-tokens", type=int, default=1)
    ap.add_argument("--benchmark-revision", required=True)
    ap.add_argument("--preflight", type=Path, default=Path("/kaggle/working/results/preflight.json"))
    ap.add_argument("--results-dir", type=Path, default=Path("/kaggle/working/results"))
    ap.add_argument("--tasks", type=Path, default=None, help="override only for a predeclared frozen task file")
    ap.add_argument("--max-model-len", type=int, default=8192)
    ap.add_argument(
        "--runtime-dir",
        type=Path,
        default=RUNTIME_DIR,
        help="directory holding the pinned prebuilt runtime receipts and venvs",
    )
    ap.add_argument(
        "--runtime-artifact-id",
        default=VLLM_RUNTIME,
        help="pinned prebuilt runtime artifact whose receipt defines the executing interpreter",
    )
    ap.add_argument(
        "--streaming",
        choices=["off", "concurrent", "sequential"],
        default="off",
        help=(
            "ask the child vLLM runner for progressive first-1/3/10 usable-option timing; "
            "the frozen offline batch path is unchanged"
        ),
    )
    args = ap.parse_args()

    # Issue #41: resolve the isolated interpreter BEFORE the import smoke, so the
    # smoke below also runs inside the frozen closure rather than the Kaggle base
    # environment. Fails closed when the receipt or venv is absent.
    runtime_python, runtime_env, runtime_receipt = resolve_isolated_runtime(
        args.runtime_dir, args.runtime_artifact_id
    )

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
        detail = f"vLLM prebuilt is not importable: {type(exc).__name__}: {exc}; do not compile fallback"
        categories = classify(detail, stage="install")
        raise SystemExit(f"{detail}; failureCategories={categories}") from exc

    # The import smoke above only proves this wrapper's environment. Confirm the
    # isolated interpreter can import the runtime too, so a global-package
    # success cannot mask a broken frozen closure.
    smoke = subprocess.run(
        [
            str(runtime_python), "-I", "-c",
            "import json, sys; import vllm; print(json.dumps({'vllm': getattr(vllm, '__version__', 'unknown'), 'prefix': sys.prefix}))",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=runtime_env,
    )
    if smoke.returncode != 0:
        categories = classify(smoke.stdout or "isolated vLLM import smoke failed", stage="install")
        raise SystemExit(
            "isolated vLLM import smoke failed inside "
            + str(runtime_python)
            + f"; treat as runtime_unqualified, do not compile a fallback; failureCategories={categories}:\n"
            + (smoke.stdout or "")
        )
    runtime_import_smoke = (smoke.stdout or "").strip()

    if args.tasks is not None:
        tasks = args.tasks.resolve()
    elif args.stage == "word-studio":
        tasks = DEFAULT_WORD_STUDIO_TASKS
    elif args.stage == "transform":
        tasks = DEFAULT_TRANSFORM_TASKS
    else:
        tasks = DEFAULT_ENGLISH_TASKS
    if not tasks.is_file():
        raise SystemExit(f"missing frozen task file: {tasks}")

    args.results_dir.mkdir(parents=True, exist_ok=True)
    candidate_dir = args.results_dir / args.candidate_id / args.stage / args.decode
    candidate_dir.mkdir(parents=True, exist_ok=True)
    # Issue #47: load feasibility and generation-batch feasibility are separate
    # states with separate policies. Product stages are pinned to batch 1 and
    # never traverse the English-screen ladder.
    is_product_stage = args.stage in PRODUCT_STAGES
    batch_ladder = PRODUCT_BATCH_POLICY if is_product_stage else CANONICAL_GENERATION_LADDER
    summary = {
        "schemaVersion": 3,
        "candidate": c,
        "stage": args.stage,
        "decode": args.decode,
        "speculativeTokens": args.speculative_tokens if args.decode != "normal" else None,
        "benchmarkRevision": args.benchmark_revision,
        "tasks": str(tasks),
        "batchLadder": list(batch_ladder),
        "batchPolicy": (
            "product-single-batch" if is_product_stage else "english-generation-ladder"
        ),
        "canonicalGenerationLadder": list(CANONICAL_GENERATION_LADDER),
        "productBatchPolicy": list(PRODUCT_BATCH_POLICY),
        "maxTransientSameConfigRetries": MAX_TRANSIENT_RETRIES,
        "runtimeEnvironment": {
            "artifactId": args.runtime_artifact_id,
            "pythonExecutable": str(runtime_python),
            "venvPath": runtime_receipt["environment"].get("venvPath"),
            "kind": runtime_receipt["environment"].get("kind"),
            "pythonExecutableSha256": runtime_receipt["environment"].get("pythonExecutableSha256"),
            "importSmoke": runtime_import_smoke,
            "executedInIsolatedEnvironment": True,
        },
        "streamingMode": args.streaming,
        "runNonce": RUN_NONCE,
        "childOwnershipPolicy": (
            "each attempt runs one owned child in its own process group; cleanup signals "
            "only that handle and never a process found by port or name"
        ),
        "attempts": [],
        "status": "running",
    }
    summary_path = candidate_dir / "summary.json"
    write_json(summary_path, summary)

    gate_identity = {
        "runNonce": RUN_NONCE,
        "candidateId": c["id"],
        "stage": args.stage,
        "decode": args.decode,
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
        summary["terminalFailureClass"] = "infrastructure_blocked"
        summary["reason"] = str(exc)
        summary["resourceGate"] = {"preRun": exc.evidence, "postStages": []}
        receipt = gpu_resource_gate.build_gate_receipt(
            run_identity=gate_identity,
            tensor_parallel=tensor_parallel,
            pre_run=exc.evidence,
            state=gpu_resource_gate.sample_gpu_state(),
        )
        receipt_path = candidate_dir / "gpu-resource-gate.json"
        write_json(receipt_path, receipt)
        summary["resourceGateReceiptPath"] = str(receipt_path)
        write_json(summary_path, summary)
        print(json.dumps({"status": summary["status"], "summary": str(summary_path)}, indent=2))
        raise SystemExit(2)
    summary["resourceGate"] = {"preRun": gate_pre_run, "postStages": []}
    summary["resourceGateBaseline"] = {"perGpu": gate_pre_run.get("perGpu", [])}
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

    artifact_preflight = inspect_hub_artifact(c["repo"], c["revision"], disk_root=Path("/kaggle/working"))
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
        summary["reason"] = f"Hub artifact preflight failed: {artifact_preflight.get('status')}"
        write_json(summary_path, summary)
        print(json.dumps({"status": summary["status"], "summary": str(summary_path)}, indent=2))
        raise SystemExit(2)
    write_json(summary_path, summary)

    stable_result: Path | None = None
    batch_index = 0
    attempt_no = 0
    transient_retries_used = 0
    while batch_index < len(batch_ladder):
        batch = batch_ladder[batch_index]
        attempt_no += 1
        stem = f"attempt-{attempt_no:02d}-batch-{batch}"
        result_path = candidate_dir / f"{stem}.result.json"
        log_path = candidate_dir / f"{stem}.log.txt"
        cmd = [
            str(runtime_python), str(RUNNER), c["repo"], str(result_path),
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
        if args.stage == "transform":
            cmd += ["--max-tokens", "900"]
        if args.decode != "normal":
            cmd += [
                "--speculative-method", args.decode,
                "--speculative-tokens", str(args.speculative_tokens),
            ]
        if args.streaming != "off":
            cmd += ["--streaming", args.streaming]

        returncode, child_stdout, ownership = run_owned_child(cmd, env=runtime_env)
        log_path.write_text(child_stdout, encoding="utf-8", errors="replace")
        failure_stage, failure_categories = classify_child_failure(child_stdout) if returncode != 0 else (None, [])
        categories = failure_categories
        stage_gate = post_stage_resource_gate(
            tensor_parallel=tensor_parallel,
            baseline=summary["resourceGateBaseline"],
            owned_pids=ownership.get("ownedPids", []),
        )
        summary["resourceGate"]["postStages"].append({
            "attempt": attempt_no,
            "stage": "inference_attempt",
            "receipt": stage_gate,
        })
        gate_receipt = gpu_resource_gate.build_gate_receipt(
            run_identity=gate_identity,
            tensor_parallel=tensor_parallel,
            pre_run=gate_pre_run,
            state=gate_state,
            post_stage=stage_gate,
            owned_pids=ownership.get("ownedPids", []),
        )
        gate_receipt_path = candidate_dir / f"gpu-resource-gate-attempt-{attempt_no:02d}.json"
        write_json(gate_receipt_path, gate_receipt)
        summary["resourceGateReceiptPath"] = str(gate_receipt_path)
        summary["resourceGateReceipt"] = gate_receipt
        attempt = {
            "attempt": attempt_no,
            "batchSize": batch,
            "returnCode": returncode,
            "elapsedSeconds": ownership["elapsedSeconds"],
            "result": str(result_path),
            "log": str(log_path),
            "failureCategories": categories,
            "failureStage": failure_stage,
            "resourceGate": stage_gate,
            "command": cmd,
            "ownedChild": ownership,
        }
        if not stage_gate.get("clean"):
            attempt["candidateEvidenceEligible"] = False
            attempt["observedCandidateFailureCategories"] = categories
            attempt["failureCategories"] = [gpu_resource_gate.BLOCKED_CATEGORY]
            attempt["failureStage"] = "cleanup"
            summary["attempts"].append(attempt)
            summary["status"] = gpu_resource_gate.BLOCKED_CATEGORY
            summary["terminalFailureCategories"] = [gpu_resource_gate.BLOCKED_CATEGORY]
            summary["terminalFailureClass"] = "infrastructure_blocked"
            summary["reason"] = "post-attempt GPU resource quarantine was not clean"
            write_json(summary_path, summary)
            break
        attempt["candidateEvidenceEligible"] = True
        decision = decide_after_attempt(
            returncode=returncode,
            categories=categories,
            batch=batch,
            transient_retries_used=transient_retries_used,
        )
        attempt["decision"] = decision.to_dict()
        summary["attempts"].append(attempt)
        write_json(summary_path, summary)

        if decision.action == "complete":
            stable_result = result_path
            summary["status"] = "inference_completed"
            summary["stableBatchSize"] = batch
            summary["result"] = str(stable_result)
            break

        # Every terminal ladder state records which kind of capacity failed, so
        # #28/#34 can distinguish load capacity from generation capacity.
        summary["capacityFailure"] = {
            "oomClass": decision.oom_class,
            "batchSize": batch,
            "decision": decision.action,
        }

        if decision.action == "stop_load_capacity":
            summary["status"] = "runtime_unqualified"
            summary["terminalFailureCategories"] = categories
            summary["terminalFailureClass"] = "load_capacity"
            summary["reason"] = decision.reason
            break
        if decision.action == "stop_generation_capacity":
            summary["status"] = "runtime_unqualified"
            summary["terminalFailureCategories"] = categories
            summary["terminalFailureClass"] = "generation_capacity"
            summary["reason"] = decision.reason
            break
        if decision.action == "retry_same_config":
            transient_retries_used += 1
            # Same frozen configuration: batch index is unchanged on purpose.
            continue
        if decision.action == "step_down_batch":
            batch_index += 1
            continue
        if decision.action == "stop_runtime_failure":
            summary["status"] = "runtime_unqualified"
            summary["terminalFailureCategories"] = categories
            summary["terminalFailureClass"] = "runtime_failure"
            summary["reason"] = decision.reason
            break
        raise SystemExit(f"unhandled attempt decision: {decision.to_dict()}")

    gate_outcome = None
    if stable_result is not None:
        result_payload = load_json(stable_result)
        progressive = PROGRESSIVE.summarize_progressive_option_timing(result_payload.get("outputs") or [])
        runtime_contract = (result_payload.get("runtime") or {}).get("progressiveOptionTiming")
        progressive["childRuntimeContract"] = runtime_contract
        progressive["requestedStreamingMode"] = args.streaming
        if args.streaming == "off" and progressive["applicableRows"]:
            progressive["limitation"] = (
                "progressive useful-option timing requires --streaming; this run used the "
                "offline batch path and its threshold fields are null"
            )
        summary["progressiveOptionTiming"] = progressive
        # Issue #62: post-inference validation/terminalization is the one shared,
        # runtime-neutral path. The Prism wrapper calls the same gate, so
        # `completed` cannot mean "vLLM also passed the promotion validator" here
        # while meaning "diagnostics passed" there. The gate itself owns the
        # terminal status; this wrapper only records it.
        gate_outcome = promotion_gate.run_post_inference_gate(
            promotion_gate.GateProvenance(
                stage=args.stage,
                decode=args.decode,
                candidate=c,
                benchmark_revision=args.benchmark_revision,
                result_path=stable_result,
                tasks_path=tasks,
                runtime=str(c.get("runtime") or "vllm"),
                model_artifact=summary.get("modelArtifact"),
                runtime_environment=summary.get("runtimeEnvironment"),
                extra={
                    "stableBatchSize": summary.get("stableBatchSize"),
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
    print(json.dumps({
        "status": summary["status"],
        "summary": str(summary_path),
        "result": str(stable_result) if stable_result else None,
    }, indent=2))
    if summary["status"] != promotion_gate.COMPLETED:
        # Terminal exit codes are defined once, by the shared gate: 0 is
        # reserved for `completed`, and the three failure states stay
        # distinguishable by exit code as well as by status string.
        raise SystemExit(gate_outcome.exit_code if gate_outcome is not None else 2)


if __name__ == "__main__":
    main()
