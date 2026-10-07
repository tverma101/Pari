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

import kaggle_run_checkpoint as K
import kaggle_stage_identity as STAGE

HERE = Path(__file__).resolve().parent
ROSTER = HERE / "kaggle-candidate-roster.json"
VLLM = HERE / "run-kaggle-vllm-candidate.py"
PRISM = HERE / "run-kaggle-prism-candidate.py"
BUILD_STRENGTH = HERE / "build-word-studio-strength-suite.py"
BUILD_TRANSFORM = HERE / "build-word-studio-transform-suite.py"
INSTALL_RUNTIME = HERE / "install-kaggle-prebuilt-runtime.py"
VERIFY_RUNTIME = HERE / "verify-kaggle-prebuilt-runtime.py"
SELECT_PRISM_RUNTIME = HERE / "select-kaggle-prism-runtime.py"
SYNTHETIC_SEED = HERE / "word-studio-synthetic.seed.json"
STRENGTH_TASKS = HERE / "word-studio-strength.jsonl"
TRANSFORM_TASKS = HERE / "word-studio-transform.jsonl"
PROTOCOL_SMOKE_TASKS = HERE / "kaggle-protocol-smoke.jsonl"
ENGLISH_TASKS = HERE / "english-core-fixed-screen.jsonl"
RUNTIME_DIR = Path("/kaggle/working/pari-runtimes")
VLLM_RUNTIME = "vllm-0.30.0-cu129-linux-x86_64"
BENCHMARK_RELEVANT_PREFIX = "open-local-phraser-v1/benchmarks/english-studio-v3"


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


def run_checked(cmd: list[str], label: str) -> str:
    print("+", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n", flush=True)
    if proc.returncode != 0:
        raise SystemExit(f"{label} failed rc={proc.returncode}; do not compile or improvise a fallback")
    return proc.stdout


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


def select_prism_runtime(results_dir: Path) -> str:
    selection = results_dir / "prism-runtime-selection.json"
    run_checked(
        [
            sys.executable, str(SELECT_PRISM_RUNTIME),
            "--runtime-dir", str(RUNTIME_DIR),
            "--output", str(selection),
        ],
        "Prism prebuilt compatibility selection",
    )
    report = json.loads(selection.read_text(encoding="utf-8"))
    selected = report.get("selectedArtifactId")
    if not selected:
        raise SystemExit(f"Prism runtime selector returned no compatible prebuilt; evidence={selection}")
    print(f"selected Prism prebuilt: {selected}", flush=True)
    return str(selected)


def stage_manifest(stage: str, tasks: Path | None) -> K.TaskManifest | None:
    """Resolve the frozen task manifest a stage will actually consume.

    Product task files are built by :func:`ensure_product_tasks` before this is
    called, so they exist for word-studio/transform. English-core and smoke task
    files are frozen inputs; if one is genuinely absent we degrade to a
    terminal-status-only unit rather than guessing a manifest hash.
    """
    if tasks is not None:
        identity = STAGE.resolve_stage_tasks(stage, tasks, promotion_run=False)
        path, role = Path(identity.path), "exploratory-task-override"
        print(
            f"warning: {path} is not the canonical {stage} artifact; this run is "
            "explicitly exploratory, non-promotion, and non-comparable",
            flush=True,
        )
    elif stage == "smoke":
        path, role = PROTOCOL_SMOKE_TASKS, "protocol-smoke"
    elif stage == "word-studio":
        path, role = STRENGTH_TASKS, "word-studio-strength"
    elif stage == "transform":
        path, role = TRANSFORM_TASKS, "word-studio-transform"
    else:
        path, role = ENGLISH_TASKS, "english-core-fixed-screen"
    identity = STAGE.resolve_stage_tasks(stage, Path(path))
    if not Path(path).is_file():
        print(
            f"warning: task manifest {path} is absent; durable reconciliation disabled",
            flush=True,
        )
        return None
    return K.load_task_manifest(path, role)


def summary_path_for(results_dir: Path, candidate_id: str, stage: str, runtime: str, decode: str) -> Path:
    """Mirror the per-runtime summary layout each candidate wrapper writes."""
    if runtime == "vllm":
        return results_dir / candidate_id / stage / decode / "summary.json"
    return results_dir / candidate_id / stage / "summary.json"


def result_path_from_summary(summary_path: Path) -> Path | None:
    """Read the child's chosen durable result path out of its summary."""
    if not summary_path.is_file():
        return None
    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    result = payload.get("result") if isinstance(payload, dict) else None
    return Path(result) if result else None


def build_provenance(
    *,
    candidate: dict,
    benchmark_revision: str,
    stage: str,
    decode: str,
    preflight: Path,
    runtime_artifact: str | None,
    manifest: K.TaskManifest | None,
    git_identity: K.GitIdentity | None = None,
    stage_identity: STAGE.TaskIdentity | None = None,
) -> K.Provenance:
    """Assemble the canonical Issue #33 provenance block for a candidate-stage."""
    receipt = (
        RUNTIME_DIR / f"{runtime_artifact}.receipt.json" if runtime_artifact else None
    )
    manifest_entries = (manifest.as_provenance_entry(),) if manifest else ()
    task_files = (manifest.path,) if manifest else ()
    parser_version = K.parser_code_version(
        [HERE / "protocol_output_diagnostics.py", HERE / "validate-english-core-run.py"]
    )
    return K.Provenance(
        benchmark_revision=benchmark_revision,
        candidate_id=candidate["id"],
        candidate_revision=candidate["revision"],
        candidate_config_sha256=K.sha256_json({
            "candidate": candidate,
            "stage": stage,
            "decode": decode,
            "runtimeArtifact": runtime_artifact,
        }),
        preflight_path=str(preflight),
        preflight_sha256=K.sha256_file(preflight),
        runtime_receipt_path=str(receipt) if (receipt and receipt.is_file()) else None,
        runtime_receipt_sha256=K.sha256_file(receipt),
        task_manifest_sha256s=manifest_entries,
        task_files=task_files,
        parser_code_version=parser_version,
        git_identity=git_identity.to_dict() if git_identity else None,
    )


def _terminal_exit_code(status: str) -> int:
    """Exit code for a terminal status."""
    return _terminal_exit_code_map(status)


def _terminal_exit_code_map(status: str) -> int:
    if status == "completed":
        return 0
    if status == "interrupted_resume_available":
        return 75
    return 2


def _receipt_completed(receipt) -> bool:
    """A gate receipt counts as completed only when it says so explicitly."""
    if isinstance(receipt, dict):
        return receipt.get("status") == "completed"
    return receipt == "completed"


def resolve_gate_evidence(stage: str, prior_receipts: dict, allow_unmet: bool) -> dict:
    """Resolve whether `stage`'s qualification gate may launch (Issue #49).

    The ladder is sequential, so a gate refuses to start while an earlier required
    receipt is missing or unfinished. `full`/Q4 therefore cannot launch without
    completed Q1 -> Q2 -> Q3 evidence. Earlier receipts always stay visible in the
    returned evidence even when a later gate fails.
    """
    gate = STAGE.gate_for_stage(stage)
    completed_gates = {
        str(entry["gate"])
        for entry in STAGE.QUALIFICATION_LADDER
        if _receipt_completed(prior_receipts.get(entry["receiptKey"]))
    }
    prerequisites_met, missing_gates = STAGE.gate_satisfied(gate, completed_gates)
    progress = STAGE.highest_gate_reached(prior_receipts)
    evidence = {
        "stage": stage,
        "gate": gate,
        "gateSpec": STAGE.gate_spec(gate),
        "completedPriorGates": sorted(completed_gates, key=STAGE.gate_order),
        "prerequisitesMet": prerequisites_met,
        "missingPrerequisiteGates": missing_gates,
        "ladderProgressBeforeThisGate": progress,
        "stageManifestSha256": STAGE.stage_manifest_sha256(),
        "qualificationLadder": STAGE.QUALIFICATION_LADDER,
    }
    if not prerequisites_met:
        evidence["nonComparableReason"] = (
            "prerequisite gates "
            + str(missing_gates)
            + " are not completed; this run is explicitly non-comparable"
        )
        evidence["allowed"] = bool(allow_unmet)
    else:
        evidence["allowed"] = True
    return evidence


def runtime_artifact_for(candidate: dict, stage: str) -> str | None:
    """Best-effort pinned runtime artifact identity for provenance binding.

    Returns ``None`` when the artifact is only selected later (the Prism path
    discovers a compatible prebuilt at dispatch time). In that case the
    candidate configuration digest still binds the run, and the runtime receipt
    fields are simply absent rather than guessed.
    """
    if candidate.get("runtime") == "vllm":
        return VLLM_RUNTIME
    declared = candidate.get("runtimeArtifactId")
    return str(declared) if declared else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate_id")
    ap.add_argument("--stage", choices=sorted(STAGE.STAGE_MANIFEST), required=True)
    ap.add_argument("--benchmark-revision", required=True)
    ap.add_argument("--decode", choices=["normal", "mtp", "qwen3_next_mtp"], default="normal")
    ap.add_argument("--speculative-tokens", type=int, default=1)
    ap.add_argument("--runtime-artifact-id", default=None)
    ap.add_argument("--results-dir", type=Path, default=Path("/kaggle/working/results"))
    ap.add_argument("--preflight", type=Path, default=Path("/kaggle/working/results/preflight.json"))
    ap.add_argument(
        "--preparation-receipt",
        type=Path,
        default=Path("/kaggle/working/results/benchmark-preparation.json"),
        help="hash-verified receipt for prepared generated task inputs; the only "
        "source of permission for untracked task files inside the benchmark tree",
    )
    ap.add_argument(
        "--timeout-seconds",
        type=float,
        default=None,
        help="hard cap for the model run; on expiry only the owned process group is terminated",
    )
    ap.add_argument(
        "--allow-dirty-tree",
        action="store_true",
        help="explicitly non-promotion debug mode: run against a dirty benchmark tree "
        "and label the summary as non-comparable",
    )
    ap.add_argument(
        "--exploratory-tasks",
        action="store_true",
        help="explicitly non-promotion: allow an unregistered --tasks override to resolve "
        "to an exploratory (non-comparable) task identity",
    )
    ap.add_argument(
        "--prior-receipts",
        type=Path,
        default=None,
        help=(
            "JSON object of receiptKey -> {status} from earlier qualification gates. "
            "Issue #49: a later gate refuses to launch unless its prerequisites completed."
        ),
    )
    ap.add_argument(
        "--allow-unmet-prerequisites",
        action="store_true",
        help="explicitly non-comparable: record unmet prerequisite gates and continue",
    )
    args = ap.parse_args()

    args.results_dir.mkdir(parents=True, exist_ok=True)

    # Issue #40: bind execution to the actual checked-out commit before any
    # model/runtime work. A short SHA, a disagreeing SHA, a missing .git, or a
    # dirty benchmark tree fails closed here, not after GPU work.
    repo_root = Path(K._git(HERE, "rev-parse", "--show-toplevel"))
    try:
        git_identity = K.verify_git_identity(
            repo_root,
            args.benchmark_revision,
            relevant_prefix=BENCHMARK_RELEVANT_PREFIX,
            require_clean=not args.allow_dirty_tree,
            preparation_receipt=args.preparation_receipt,
        )
    except K.CheckpointError as exc:
        # Fail closed with a readable message rather than a traceback, and
        # before any model/runtime download or load.
        raise SystemExit(f"benchmark identity guard rejected this launch: {exc}")
    print(
        f"verified benchmark identity: HEAD={git_identity.head} "
        f"tree={git_identity.tree} branch={git_identity.branch} "
        f"promotionEligible={git_identity.promotion_eligible}",
        flush=True,
    )

    ensure_product_tasks(args.stage)
    smoke_tasks: Path | None = None
    if args.stage == "smoke":
        if jsonl_count(PROTOCOL_SMOKE_TASKS) != 16:
            raise SystemExit("kaggle-protocol-smoke.jsonl must contain exactly 16 unique tasks")
        smoke_tasks = PROTOCOL_SMOKE_TASKS

    # Issue #48: resolve the stage's task identity through the one frozen
    # register before anything is launched.
    promotion_run = git_identity.promotion_eligible and not args.exploratory_tasks
    stage_identity = STAGE.resolve_stage_tasks(
        args.stage, smoke_tasks, promotion_run=promotion_run
    )
    print(
        f"stage task identity: kind={stage_identity.kind} "
        f"path={stage_identity.path} sha256={stage_identity.sha256} "
        f"batchPolicy={stage_identity.batch_policy}",
        flush=True,
    )

    # Issue #49: the ladder is sequential. A gate refuses to launch while an
    # earlier required receipt is missing or unfinished, so Q4 full screening
    # cannot start without completed Q1 -> Q2 -> Q3 evidence.
    prior_receipts: dict = {}
    if args.prior_receipts and args.prior_receipts.is_file():
        prior_receipts = json.loads(args.prior_receipts.read_text(encoding="utf-8"))
    gate_evidence = resolve_gate_evidence(
        args.stage, prior_receipts, args.allow_unmet_prerequisites
    )
    if not gate_evidence["allowed"]:
        raise SystemExit(
            "qualification gate "
            + str(gate_evidence["gate"])
            + " is not reachable: missing completed prerequisite receipts for "
            + str(gate_evidence["missingPrerequisiteGates"])
            + ". Earlier receipts stay visible in the per-gate summary files. Pass "
            "completed receipts via --prior-receipts, or use "
            "--allow-unmet-prerequisites for an explicitly non-comparable run."
        )
    print(
        "qualification gate "
        + str(gate_evidence["gate"])
        + ": prerequisitesMet="
        + str(gate_evidence["prerequisitesMet"])
        + " missing="
        + str(gate_evidence["missingPrerequisiteGates"])
        + " highestReached="
        + str(gate_evidence["ladderProgressBeforeThisGate"]["highestGateReached"]),
        flush=True,
    )

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
        if smoke_tasks is not None:
            cmd += ["--tasks", str(smoke_tasks)]
        cmd += ["--preflight", str(args.preflight)]
    elif runtime == "llama.cpp":
        if args.decode != "normal":
            raise SystemExit("this pinned Prism/Bonsai path has no validated speculative decode; use --decode normal")
        if args.runtime_artifact_id:
            runtime_artifact = args.runtime_artifact_id
            ensure_runtime(runtime_artifact)
        else:
            runtime_artifact = select_prism_runtime(args.results_dir)
        cmd = [
            sys.executable, str(PRISM), args.candidate_id,
            "--stage", args.stage,
            "--benchmark-revision", args.benchmark_revision,
            "--results-dir", str(args.results_dir),
            "--runtime-artifact-id", runtime_artifact,
        ]
        if smoke_tasks is not None:
            cmd += ["--tasks", str(smoke_tasks)]
        cmd += ["--preflight", str(args.preflight)]
    else:
        raise SystemExit(f"candidate {args.candidate_id} has unsupported canonical runtime {runtime!r}")

    print("+", " ".join(cmd), flush=True)
    manifest = stage_manifest(args.stage, smoke_tasks)
    provenance = build_provenance(
        candidate=c,
        benchmark_revision=args.benchmark_revision,
        stage=args.stage,
        decode=args.decode,
        preflight=args.preflight,
        runtime_artifact=runtime_artifact,
        manifest=manifest,
        git_identity=git_identity,
        stage_identity=stage_identity,
    )
    run_identity_extra = {
        "stageTaskIdentity": stage_identity.to_dict(),
        "stageIdentityRegisterSha256": STAGE.register_sha256(),
        "stageManifestSha256": STAGE.stage_manifest_sha256(),
        "qualificationGate": gate_evidence,
        "canonicalBatchPolicy": STAGE.canonical_batch_policy(args.stage),
        "promotionEligible": git_identity.promotion_eligible,
        "nonComparableReason": (
            None
            if (git_identity.promotion_eligible and stage_identity.comparable)
            else stage_identity.reason
        ),
    }
    unit_id = f"{args.candidate_id}/{args.stage}/{args.decode}"
    summary_path = summary_path_for(
        args.results_dir, args.candidate_id, args.stage, runtime, args.decode
    )
    try:
        outcome = K.execute_unit(
            unit_id=unit_id,
            unit_kind="candidate-stage",
            cmd=cmd,
            manifest=manifest,
            provenance=provenance,
            checkpoint_path=summary_path.with_suffix(".checkpoint.json"),
            log_path=summary_path.with_name(f"{summary_path.stem}.log.txt"),
            summary_path=summary_path,
            resolve_result_path=lambda: result_path_from_summary(summary_path),
            timeout_seconds=args.timeout_seconds,
            stage=args.stage,
            summary_extra=run_identity_extra,
        )
    except K.IncompatibleCheckpoint as exc:
        # Never splice outputs from a changed configuration.
        raise SystemExit(f"refusing to resume an incompatible checkpoint: {exc}")
    except K.CorruptCheckpoint as exc:
        raise SystemExit(f"corrupt checkpoint or durable output: {exc}")

    print(json.dumps({
        "status": outcome.status,
        "terminalReason": outcome.reason,
        "unit": unit_id,
        "summary": str(summary_path),
        "checkpoint": str(outcome.checkpoint_path),
        "result": str(outcome.durable.path) if outcome.durable else None,
        "cleanup": outcome.cleanup.to_dict(),
    }, indent=2))
    raise SystemExit(_terminal_exit_code(outcome.status))


if __name__ == "__main__":
    main()
