#!/usr/bin/env python3
"""Fail-closed GPU resource-cleanliness gate and single-owner GPU lease (Issue #57).

`kaggle-preflight.py` already records low free VRAM and pre-existing GPU compute
processes, but treats them as warnings because preflight is environment
discovery. This module is the fail-closed gate that runs immediately before and
after every candidate/runtime stage: a candidate may not be judged while a
required GPU is contaminated by an unrelated or leftover workload, because that
contamination surfaces as the *next* candidate's `cuda_oom_*` and becomes false
evidence about model capacity.

Rules the tests pin down:

* Contamination is infrastructure, not candidate capacity. A blocked gate emits
  `infrastructure_blocked_resource_contamination` and the caller must not attempt
  model qualification. A clean gate followed by a real OOM stays candidate and
  runtime evidence.
* Foreign and unknown processes are never killed. Only processes provably owned
  by this orchestrator are eligible, and only as residue from a prior canonical
  run. Anything unrecognized is recorded and blocked, never reaped.
* Thresholds are predeclared and immutable at runtime. They are module constants
  with rationale attached, passed in explicitly, and never recomputed from an
  observed failure. `assert_thresholds_unmodified` catches a caller trying to
  relax them after seeing a failure.
* A file lock alone is not enough. The lease stops cooperating benchmark workers;
  the real `nvidia-smi` process check still runs, because unrelated notebook code
  can launch CUDA work without taking the lease.
* TP1 and TP2 differ. For TP1 only GPU0 is required, so contamination on the
  unused GPU1 is recorded as a warning rather than a block. For TP2 both GPUs
  must satisfy the gate.
* Waiting longer is not cleanup. Quarantine resnapshots and compares against the
  pre-run baseline, so persistent residual memory above threshold stays reported
  as still contaminated.

Standard library only, so it imports on Kaggle before any ML dependency exists.
Every `nvidia-smi` invocation, sleep, and process signal goes through an injected
callable, so the whole gate is exercisable with mocked data and never touches a
real accelerator from tests.
"""
from __future__ import annotations

import errno
import json
import os
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from kaggle_telemetry import (
    RECEIPT_SCHEMA_VERSION,
    make_snapshot,
    parse_nvidia_smi_csv,
    parse_nvidia_smi_processes,
    utc_now_iso,
)

SCHEMA_VERSION = 1

#: Gate outcome that must never be rewritten into a model/runtime failure.
BLOCKED_CATEGORY = "infrastructure_blocked_resource_contamination"

#: Ownership classes for a GPU compute process. These three values are the whole
#: vocabulary; nothing is ever silently treated as safe.
OWNED = "owned_by_current_run"
KNOWN_RESIDUE = "known_residue_from_prior_canonical_run"
FOREIGN_UNKNOWN = "foreign_or_unknown"

OWNERSHIP_CLASSES = (OWNED, KNOWN_RESIDUE, FOREIGN_UNKNOWN)

#: Process-name fragments that make a process *provably* orchestrator-owned when
#: the caller cannot supply an explicit owned PID set. This is an allowlist, not
#: a denylist: an unrecognized name is always FOREIGN_UNKNOWN, which blocks but
#: is never killed.
ORCHESTRATOR_PROCESS_NAME_FRAGMENTS = ("pari_bench_",)

# A foreign compute process may hold up to this much memory on a required GPU
# before the gate blocks. This is the "small documented baseline": it absorbs a
# few MiB of driver/context residue while catching any real workload. A process
# at or above this value blocks; below it the presence is still recorded.
FOREIGN_COMPUTE_MIB_BASELINE = 256

# A required GPU must expose this much free VRAM before model load. Kaggle's 2xT4
# gives 16384 MiB per card, so this demands a genuinely idle device. Declared
# here, not derived from a candidate's observed OOM.
MIN_FREE_VRAM_MIB = 14_000

# Residual VRAM above this over the pre-run baseline keeps the next candidate
# blocked, even if the owned process already exited.
MAX_POST_STAGE_RESIDUAL_MIB = 512

# Bounded cooldown and poll interval used while waiting for driver allocations to
# release after an owned process exits.
COOLDOWN_SECONDS = 30.0
COOLDOWN_POLL_SECONDS = 1.0

# Signal escalation for owned residue only.
OWNED_TERMINATE_SIGNAL = signal.SIGTERM
OWNED_KILL_SIGNAL = signal.SIGKILL
OWNED_TERM_GRACE_SECONDS = 10.0

THRESHOLD_RATIONALE: dict[str, str] = {
    "foreignComputeMiBBaseline": (
        f"A foreign/unknown compute process holding >= {FOREIGN_COMPUTE_MIB_BASELINE} MiB on "
        "a required GPU blocks the stage. The baseline absorbs a few MiB of driver/context "
        "residue while catching any real workload. Predeclared before the run; never relaxed "
        "after observing a failure."
    ),
    "minFreeVramMiB": (
        f"A required GPU must expose >= {MIN_FREE_VRAM_MIB} MiB free before model load. On a "
        "16 GiB T4 this means a genuinely idle device, so a contaminated GPU cannot be "
        "misreported as candidate capacity."
    ),
    "maxPostStageResidualMiB": (
        f"After a stage, residual VRAM above {MAX_POST_STAGE_RESIDUAL_MIB} MiB over the pre-run "
        "baseline keeps the next candidate blocked, even if the owned process already exited."
    ),
}


class GateError(RuntimeError):
    """The gate refused to proceed, carrying the evidence that justified it."""

    def __init__(self, message: str, evidence: dict[str, Any], category: str = BLOCKED_CATEGORY):
        super().__init__(message)
        self.evidence = evidence
        self.category = category


class LeaseUnavailable(RuntimeError):
    """Another owner holds the GPU lease."""

    def __init__(self, message: str, evidence: dict[str, Any]):
        super().__init__(message)
        self.evidence = evidence


@dataclass(frozen=True)
class GateThresholds:
    """Immutable, predeclared gate thresholds.

    Frozen so a runner cannot widen a bar in place after a candidate fails to
    load. A genuinely different policy needs a different explicit object, which
    then shows up in the receipt instead of hiding inside a retry loop.
    """

    foreign_compute_mib_baseline: int = FOREIGN_COMPUTE_MIB_BASELINE
    min_free_vram_mib: int = MIN_FREE_VRAM_MIB
    max_post_stage_residual_mib: int = MAX_POST_STAGE_RESIDUAL_MIB

    def as_dict(self) -> dict[str, Any]:
        return {
            "foreignComputeMiBBaseline": self.foreign_compute_mib_baseline,
            "minFreeVramMiB": self.min_free_vram_mib,
            "maxPostStageResidualMiB": self.max_post_stage_residual_mib,
        }


DEFAULT_THRESHOLDS = GateThresholds()


def assert_thresholds_unmodified(thresholds: GateThresholds) -> None:
    """Fail closed if a caller relaxed a predeclared threshold.

    The issue forbids relaxing the free-VRAM threshold after observing a failure.
    Comparing against the module defaults catches the common case where a runner
    loosens a bar to get past a contaminated or failing GPU.

    Each field has a direction: `min_free_vram_mib` is a floor, so a *higher*
    value is stricter, while the two ceilings are stricter when *lower*. A
    change in the permissive direction is refused; a change in the strict
    direction is allowed.
    """
    for name, default_value, higher_is_stricter in (
        ("foreign_compute_mib_baseline", FOREIGN_COMPUTE_MIB_BASELINE, False),
        ("min_free_vram_mib", MIN_FREE_VRAM_MIB, True),
        ("max_post_stage_residual_mib", MAX_POST_STAGE_RESIDUAL_MIB, False),
    ):
        value = getattr(thresholds, name)
        relaxed = value < default_value if higher_is_stricter else value > default_value
        if relaxed:
            raise GateError(
                f"threshold {name} was relaxed from {default_value} to {value}; gate "
                "thresholds are predeclared and may only be tightened",
                {
                    "threshold": name,
                    "predeclared": default_value,
                    "requested": value,
                    "rationale": THRESHOLD_RATIONALE,
                },
                category="infrastructure_blocked_threshold_relaxation",
            )


#: Column contract reused verbatim from the #31 telemetry module so a gate
#: snapshot and a finalist stability receipt describe the same GPU fields.
QUERY_GPU_FIELDS = "index,uuid,name,memory.used,memory.free,memory.total,utilization.gpu"


def default_smi_runner(argv: Sequence[str]) -> tuple[int, str, str]:
    """Run an `nvidia-smi` argv and return ``(returncode, stdout, stderr)``.

    This is the only place that touches the real driver, which keeps the blast
    radius obvious and makes every test able to mock it.
    """
    import subprocess

    proc = subprocess.run(
        list(argv), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    return proc.returncode, proc.stdout, proc.stderr


def sample_gpu_state(
    smi_runner: Callable[[Sequence[str]], tuple[int, str, str]] = default_smi_runner,
) -> dict[str, Any]:
    """Read per-GPU memory/utilization plus compute processes.

    Returns ``{"available": bool, "gpus": [...], "processesByGpu": {...}}``.
    Per-GPU memory stays an array of gpu objects and is never collapsed, so a
    contaminated GPU 1 cannot be averaged into a healthy-looking total. A driver
    read failure degrades to ``available: False`` with the raw error preserved
    rather than throwing, so the gate can fail closed on missing evidence instead
    of crashing the runner.
    """
    state: dict[str, Any] = {
        "available": False,
        "gpus": [],
        "processesByGpu": {},
        "errors": [],
    }

    rc, out, err = smi_runner(
        ["nvidia-smi", f"--query-gpu={QUERY_GPU_FIELDS}", "--format=csv,noheader,nounits"]
    )
    if rc != 0:
        state["errors"].append(
            {"query": "gpu", "returncode": rc, "stderr": (err or "").strip()[:500]}
        )
        return state

    gpus = parse_nvidia_smi_csv(out, stage="resource_gate")
    if not gpus:
        state["errors"].append(
            {"query": "gpu", "returncode": rc, "stderr": "no parsable GPU rows"}
        )
        return state
    state["gpus"] = gpus

    index_by_uuid = {gpu["uuid"]: gpu["gpuIndex"] for gpu in gpus if gpu.get("uuid")}

    proc_rc, proc_out, proc_err = smi_runner(
        [
            "nvidia-smi",
            "--query-compute-apps=gpu_uuid,pid,process_name,used_memory",
            "--format=csv,noheader,nounits",
        ]
    )
    if proc_rc != 0:
        # Not automatically fatal: an empty process table is the common clean
        # case and some drivers refuse this query when nothing is running.
        state["errors"].append(
            {"query": "compute-apps", "returncode": proc_rc, "stderr": (proc_err or "").strip()[:500]}
        )
        state["available"] = True
        return state

    for line in (proc_out or "").splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 4:
            continue
        gpu_uuid = parts[0]
        pid_text = parts[1]
        name = parts[2]
        used_text = ",".join(parts[3:])
        # A compute app on a UUID we could not map is unattributed contamination
        # evidence, recorded under index -1 rather than dropped.
        gpu_index = index_by_uuid.get(gpu_uuid, -1)
        for row in parse_nvidia_smi_processes(f"{pid_text}, {name}, {used_text}"):
            row["gpuUuid"] = gpu_uuid or None
            state["processesByGpu"].setdefault(gpu_index, []).append(row)

    state["available"] = True
    return state


def classify_process(
    process: dict[str, Any],
    *,
    owned_pids: set[int],
    residue_pids: set[int],
) -> str:
    """Classify one GPU compute process into exactly one ownership class.

    Order matters: the current run's own PIDs win, then explicitly registered
    residue from a prior canonical run, and everything else is FOREIGN_UNKNOWN.
    There is no path returning a "safe to ignore" value, because a name this
    module does not recognize is exactly the case where it must not guess.
    """
    pid = process.get("pid")
    if not isinstance(pid, int):
        return FOREIGN_UNKNOWN
    if pid in owned_pids:
        return OWNED
    if pid in residue_pids:
        return KNOWN_RESIDUE
    name = (process.get("processName") or "").lower()
    if any(fragment.lower() in name for fragment in ORCHESTRATOR_PROCESS_NAME_FRAGMENTS):
        # Name-matched orchestrator process with no live handle in this run: it is
        # residue from a prior canonical run, so it is reapable. It is never
        # promoted to OWNED, because this run cannot prove it started it.
        return KNOWN_RESIDUE
    return FOREIGN_UNKNOWN


def classify_gpu_processes(
    state: dict[str, Any],
    *,
    owned_pids: set[int] | None = None,
    residue_pids: set[int] | None = None,
) -> dict[str, Any]:
    """Attach an ``ownership`` label to every observed compute process."""
    owned = set(owned_pids or ())
    residue = set(residue_pids or ())
    classified: dict[str, Any] = {}
    for gpu_index, processes in (state.get("processesByGpu") or {}).items():
        rows = []
        for process in processes:
            row = dict(process)
            row["ownership"] = classify_process(process, owned_pids=owned, residue_pids=residue)
            rows.append(row)
        classified[str(gpu_index)] = rows
    return classified


# ---------------------------------------------------------------------------
# Required-GPU sets: TP1 vs TP2
# ---------------------------------------------------------------------------


def required_gpu_indices(
    tensor_parallel: int, *, cuda_visible_devices: Sequence[int] | None = None
) -> list[int]:
    """Return the GPU indices a candidate actually needs.

    TP1 needs exactly the first visible device; TP2 needs the first two. When a
    run restricts ``CUDA_VISIBLE_DEVICES``, the logical TP degree is mapped onto
    physical indices so the gate still knows which devices block the stage.
    """
    if tensor_parallel not in (1, 2):
        raise ValueError(
            f"unsupported tensor_parallel {tensor_parallel!r}; this gate models TP1 and TP2"
        )
    if cuda_visible_devices is None:
        return list(range(tensor_parallel))
    visible = [int(i) for i in cuda_visible_devices]
    if len(visible) < tensor_parallel:
        raise ValueError(
            f"tensor_parallel {tensor_parallel} needs {tensor_parallel} visible devices, got {visible}"
        )
    return sorted(visible[:tensor_parallel])


def _foreign_compute_mib(classified: dict[str, Any], index: int) -> tuple[int, list[dict[str, Any]]]:
    """Sum compute memory held by processes this run may not touch."""
    total = 0
    rows: list[dict[str, Any]] = []
    for row in classified.get(str(index)) or []:
        if row.get("ownership") == OWNED:
            continue
        used = row.get("usedMiB")
        if isinstance(used, int) and not isinstance(used, bool):
            total += used
            rows.append(row)
    return total, rows


# ---------------------------------------------------------------------------
# Pre-run gate
# ---------------------------------------------------------------------------


def evaluate_pre_run_gate(
    state: dict[str, Any],
    *,
    tensor_parallel: int,
    thresholds: GateThresholds = DEFAULT_THRESHOLDS,
    owned_pids: Sequence[int] | None = None,
    residue_pids: Sequence[int] | None = None,
    cuda_visible_devices: Sequence[int] | None = None,
    run_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate the fail-closed pre-run gate without side effects.

    Pure, so a caller can inspect the verdict before committing to it. Use
    :func:`require_clean_pre_run` when you want a blocked verdict to raise.
    """
    assert_thresholds_unmodified(thresholds)
    required = required_gpu_indices(tensor_parallel, cuda_visible_devices=cuda_visible_devices)
    classified = classify_gpu_processes(
        state, owned_pids=set(owned_pids or ()), residue_pids=set(residue_pids or ())
    )

    per_gpu: list[dict[str, Any]] = []
    warnings: list[str] = []
    blocking: list[str] = []

    for gpu in state.get("gpus") or []:
        index = gpu.get("gpuIndex")
        is_required = index in required
        foreign_mib, foreign_rows = _foreign_compute_mib(classified, index)
        free = gpu.get("freeMiB")
        processes = classified.get(str(index)) or []

        reasons: list[str] = []
        if foreign_mib >= thresholds.foreign_compute_mib_baseline:
            reasons.append(
                f"foreign_or_unknown_compute_mib_{foreign_mib}_at_or_above_"
                f"{thresholds.foreign_compute_mib_baseline}"
            )
        if is_required:
            # Fail closed on missing evidence too: an unreadable free-VRAM field
            # is not proof of a clean device. Treating unknown as "fine" would
            # let a GPU in a transient driver state pass the gate.
            if not isinstance(free, int) or isinstance(free, bool):
                reasons.append("free_vram_unknown_cannot_prove_clean_baseline")
            elif free < thresholds.min_free_vram_mib:
                reasons.append(f"free_vram_mib_{free}_below_{thresholds.min_free_vram_mib}")
        if not is_required and foreign_mib > 0:
            # TP1 on an unused GPU1: recorded and warned, but not blocking.
            warnings.append(
                f"gpu{index}_unused_gpu_has_{foreign_mib}MiB_foreign_compute; recorded for the "
                "receipt and does not block a TP1 candidate"
            )

        # Known residue is reapable but is not clean until removed, so it blocks
        # the stage while naming the exact cleanup path.
        residue_rows = [r for r in processes if r.get("ownership") == KNOWN_RESIDUE]
        if residue_rows and is_required:
            reasons.append(
                "known_residue_processes_present:"
                + ",".join(str(r.get("pid")) for r in residue_rows)
            )

        if reasons and is_required:
            blocking.extend(f"gpu{index}:{reason}" for reason in reasons)
        per_gpu.append(
            {
                "gpuIndex": index,
                "required": is_required,
                "usedMiB": gpu.get("usedMiB"),
                "freeMiB": gpu.get("freeMiB"),
                "totalMiB": gpu.get("totalMiB"),
                "utilizationPercent": gpu.get("utilizationPercent"),
                "foreignOrUnknownComputeMiB": foreign_mib,
                "processes": processes,
                "reasons": reasons if is_required else [],
                "blocked": bool(reasons) and is_required,
            }
        )

    if not state.get("available"):
        # Missing driver evidence is not clean evidence. Fail closed.
        blocking.append("nvidia_smi_unavailable_cannot_prove_clean_baseline")

    return {
        "schemaVersion": SCHEMA_VERSION,
        "telemetrySchemaVersion": RECEIPT_SCHEMA_VERSION,
        "timestamp": utc_now_iso(),
        "runIdentity": dict(run_identity or {}),
        "tensorParallel": tensor_parallel,
        "requiredGpuIndices": required,
        "thresholds": thresholds.as_dict(),
        "thresholdRationale": THRESHOLD_RATIONALE,
        "nvidiaSmiAvailable": bool(state.get("available")),
        "perGpu": per_gpu,
        "warnings": warnings,
        "blockingReasons": blocking,
        "allowed": not blocking,
        "verdict": "clean" if not blocking else BLOCKED_CATEGORY,
    }


def require_clean_pre_run(**kwargs: Any) -> dict[str, Any]:
    """Evaluate the pre-run gate and raise :class:`GateError` when blocked.

    A raised :class:`GateError` means the caller must not attempt model
    qualification and must not record an OOM or runtime-unqualified status for
    this attempt. That distinction is the whole point of the gate: contamination
    is infrastructure, never candidate capacity.
    """
    result = evaluate_pre_run_gate(**kwargs)
    if not result["allowed"]:
        raise GateError(
            "pre-run GPU gate blocked candidate qualification: "
            + "; ".join(result["blockingReasons"]),
            result,
        )
    return result


# ---------------------------------------------------------------------------
# Owned-residue cleanup (never foreign/unknown)
# ---------------------------------------------------------------------------


def reapable_residue_pids(classified: dict[str, Any]) -> set[int]:
    """PIDs classified as prior-canonical-run residue, which are reapable."""
    return {
        row["pid"]
        for rows in classified.values()
        for row in rows
        if row.get("ownership") == KNOWN_RESIDUE and isinstance(row.get("pid"), int)
    }


def terminate_owned_residue(
    pids: Sequence[int],
    *,
    classified: dict[str, Any],
    signal_sender: Callable[[int, int], None] = os.kill,
    sleep: Callable[[float], None] = time.sleep,
    grace_seconds: float = OWNED_TERM_GRACE_SECONDS,
) -> dict[str, Any]:
    """Terminate only processes proven to be orchestrator-owned residue.

    ``pids`` is intersected against the classified process table; anything
    classified FOREIGN_UNKNOWN is skipped and reported as
    ``not_killed_foreign_or_unknown``. This is the enforcement point for the
    issue's "never kill a foreign process automatically merely to make a
    benchmark pass" rule, and it is deliberately the only function in this
    module that sends a signal.
    """
    reapable = reapable_residue_pids(classified)
    skipped: list[dict[str, Any]] = []
    terminated: list[dict[str, Any]] = []

    for pid in pids:
        if pid not in reapable:
            observed = next(
                (row for rows in classified.values() for row in rows if row.get("pid") == pid),
                None,
            )
            skipped.append(
                {
                    "pid": pid,
                    "reason": "not_killed_foreign_or_unknown",
                    "observedOwnership": (observed or {}).get("ownership"),
                }
            )
            continue

        entry: dict[str, Any] = {"pid": pid, "signals": []}
        for sig, label in ((OWNED_TERMINATE_SIGNAL, "SIGTERM"), (OWNED_KILL_SIGNAL, "SIGKILL")):
            try:
                signal_sender(pid, sig)
                entry["signals"].append({"signal": label, "delivered": True})
            except ProcessLookupError:
                entry["signals"].append(
                    {"signal": label, "delivered": False, "error": "already_exited"}
                )
                break
            except OSError as exc:
                entry["signals"].append(
                    {
                        "signal": label,
                        "delivered": False,
                        "error": f"{type(exc).__name__}: {exc}",
                        "errno": errno.errorcode.get(exc.errno),
                    }
                )
                break
            if label == "SIGTERM":
                # Bounded grace before escalating. Never unbounded.
                sleep(grace_seconds)
        terminated.append(entry)

    return {
        "attempted": [t["pid"] for t in terminated],
        "terminated": terminated,
        "notKilled": skipped,
        "policy": (
            "Only processes classified as known residue from a prior canonical run are "
            "signalled. Foreign, unknown, and unrecognized PIDs are recorded and never "
            "killed."
        ),
    }


# ---------------------------------------------------------------------------
# Between-candidate quarantine
# ---------------------------------------------------------------------------


def quarantine_after_stage(
    *,
    tensor_parallel: int,
    baseline: dict[str, Any],
    smi_runner: Callable[[Sequence[str]], tuple[int, str, str]] = default_smi_runner,
    thresholds: GateThresholds = DEFAULT_THRESHOLDS,
    owned_pids: Sequence[int] | None = None,
    residue_pids: Sequence[int] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    cooldown_seconds: float = COOLDOWN_SECONDS,
    signal_sender: Callable[[int, int], None] = os.kill,
    terminate_grace_seconds: float = OWNED_TERM_GRACE_SECONDS,
) -> dict[str, Any]:
    """Verify handoff between candidates: owned exit, cooldown, resnapshot, compare.

    The comparison is against ``baseline`` (the pre-run snapshot), not against
    the newest reading, so residual memory cannot be hidden by sleeping longer.
    Returns ``clean`` only when owned processes are gone and every required GPU
    is back within the residual band of its baseline.
    """
    assert_thresholds_unmodified(thresholds)
    required = required_gpu_indices(tensor_parallel)
    owned = set(owned_pids or ())
    residue = set(residue_pids or ())
    baseline_used = {
        row["gpuIndex"]: row.get("usedMiB")
        for row in (baseline.get("perGpu") or [])
        if isinstance(row.get("gpuIndex"), int)
    }

    cleanup_attempt: dict[str, Any] | None = None
    observations: list[dict[str, Any]] = []
    residue_cleared = False

    deadline = clock() + cooldown_seconds
    while True:
        current = sample_gpu_state(smi_runner)
        classified = classify_gpu_processes(current, owned_pids=owned, residue_pids=residue)
        surviving_owned = sorted(
            row["pid"]
            for rows in classified.values()
            for row in rows
            if row.get("ownership") == OWNED
        )
        residue_present = sorted(reapable_residue_pids(classified))
        observations.append(
            {
                "timestamp": utc_now_iso(),
                "survivingOwnedPids": surviving_owned,
                "residuePids": residue_present,
                "perGpu": [
                    {"gpuIndex": g.get("gpuIndex"), "usedMiB": g.get("usedMiB")}
                    for g in current.get("gpus") or []
                ],
            }
        )

        if residue_present and cleanup_attempt is None:
            # Owned residue from a prior run: reap it once under the cleanup
            # contract, then keep polling until it is gone or cooldown expires.
            cleanup_attempt = terminate_owned_residue(
                residue_present,
                classified=classified,
                signal_sender=signal_sender,
                sleep=sleep,
                grace_seconds=terminate_grace_seconds,
            )
            residue_cleared = True
        elif residue_present:
            residue_cleared = False
        else:
            residue_cleared = True

        if not surviving_owned and not residue_present:
            break
        if clock() >= deadline:
            break
        sleep(COOLDOWN_POLL_SECONDS)

    final = sample_gpu_state(smi_runner)
    classified_final = classify_gpu_processes(final, owned_pids=owned, residue_pids=residue)
    surviving_owned = sorted(
        row["pid"]
        for rows in classified_final.values()
        for row in rows
        if row.get("ownership") == OWNED
    )
    final_residue = sorted(reapable_residue_pids(classified_final))

    residual: list[dict[str, Any]] = []
    for gpu in final.get("gpus") or []:
        index = gpu.get("gpuIndex")
        if index not in required:
            continue
        used = gpu.get("usedMiB")
        base = baseline_used.get(index)
        delta: int | None = None
        if isinstance(used, int) and not isinstance(used, bool) and isinstance(base, int) and not isinstance(base, bool):
            delta = used - base
        # Missing baseline or observation cannot prove a clean handoff, so it is
        # treated as a residual worth reporting instead of silently passing.
        unknown_memory = delta is None
        if surviving_owned or unknown_memory or (delta is not None and delta > thresholds.max_post_stage_residual_mib):
            residual.append(
                {
                    "gpuIndex": index,
                    "baselineUsedMiB": base,
                    "observedUsedMiB": used,
                    "residualMiB": delta,
                    "exceedsThreshold": bool(
                        unknown_memory or delta > thresholds.max_post_stage_residual_mib
                    ),
                }
            )

    blocking: list[str] = []
    if surviving_owned:
        blocking.append(f"owned_processes_still_running:{surviving_owned}")
    if final_residue:
        blocking.append(f"known_residue_still_running:{final_residue}")
    for row in residual:
        if row["exceedsThreshold"]:
            if row["residualMiB"] is None:
                blocking.append(
                    f"gpu{row['gpuIndex']}:residual_vram_unknown_cannot_prove_clean_handoff"
                )
            else:
                blocking.append(
                    f"gpu{row['gpuIndex']}:residual_vram_mib_{row['residualMiB']}_above_"
                    f"{thresholds.max_post_stage_residual_mib}"
                )

    return {
        "schemaVersion": SCHEMA_VERSION,
        "timestamp": utc_now_iso(),
        "tensorParallel": tensor_parallel,
        "requiredGpuIndices": required,
        "thresholds": thresholds.as_dict(),
        "cleanupAttempt": cleanup_attempt,
        "observations": observations,
        "survivingOwnedPids": surviving_owned,
        "finalResiduePids": final_residue,
        "residueCleared": residue_cleared,
        "residualPerGpu": residual,
        "blockingReasons": blocking,
        "clean": not blocking,
        "verdict": "clean_handoff" if not blocking else BLOCKED_CATEGORY,
        "note": (
            "Residual memory is compared against the pre-run baseline; a longer sleep cannot "
            "make a contaminated handoff pass."
        ),
    }


# ---------------------------------------------------------------------------
# Mid-run contamination
# ---------------------------------------------------------------------------


def detect_mid_run_contamination(
    state: dict[str, Any],
    *,
    tensor_parallel: int,
    thresholds: GateThresholds = DEFAULT_THRESHOLDS,
    owned_pids: Sequence[int] | None = None,
    cuda_visible_devices: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Flag a required GPU gaining unattributed compute memory mid-run.

    A clean pre-run gate plus contamination appearing during the measured loop
    invalidates timing comparability, so the caller must discard those timings
    rather than report them as the candidate's latency.
    """
    required = required_gpu_indices(tensor_parallel, cuda_visible_devices=cuda_visible_devices)
    classified = classify_gpu_processes(state, owned_pids=set(owned_pids or ()))
    contaminated: list[dict[str, Any]] = []
    for index in required:
        foreign_mib, foreign_rows = _foreign_compute_mib(classified, index)
        if foreign_mib >= thresholds.foreign_compute_mib_baseline:
            contaminated.append(
                {
                    "gpuIndex": index,
                    "foreignOrUnknownComputeMiB": foreign_mib,
                    "processes": foreign_rows,
                }
            )
    return {
        "schemaVersion": SCHEMA_VERSION,
        "timestamp": utc_now_iso(),
        "requiredGpuIndices": required,
        "contaminatedRequiredGpus": contaminated,
        "contaminationDetected": bool(contaminated),
        "timingComparabilityValid": not contaminated,
        "verdict": BLOCKED_CATEGORY if contaminated else "no_mid_run_contamination",
    }


# ---------------------------------------------------------------------------
# Single-owner GPU lease
# ---------------------------------------------------------------------------


@dataclass
class GpuLease:
    """An exclusive, single-owner lease over the canonical GPU set.

    Canonical roster execution is sequential by default. The lease makes that
    explicit across processes so two individually correct runners cannot both
    observe a clean GPU and start at once. It deliberately does not replace the
    `nvidia-smi` check: unrelated notebook code can launch CUDA work without ever
    taking this lease, so the real process check still runs underneath it.
    """

    path: Path
    owner: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    _acquired: bool = field(default=False, repr=False)

    def acquire(self, *, owner: str | None = None, steal_stale_after: float | None = None) -> "GpuLease":
        """Take the lease exclusively, or raise :class:`LeaseUnavailable`.

        ``O_CREAT | O_EXCL`` is the atomic primitive: exactly one racing process
        can create the file, so there is no advisory-lock window in which both
        workers believe they hold the GPU.

        ``steal_stale_after`` opts into stale-holder recovery. ``0.0`` reclaims a
        lease whose owning process is provably gone as soon as it is seen, which
        is the deliberate post-crash recovery path. Any positive value also
        requires the lease file to be at least that many seconds old, so a
        holder that just started is never reclaimed out from under itself. A
        live holder is never reclaimed regardless of this setting.
        """
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # An owner supplied at construction is kept; an explicit `owner=` wins.
        self.owner = owner or self.owner or f"pid-{os.getpid()}"
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "owner": self.owner,
            "pid": os.getpid(),
            "acquiredAt": utc_now_iso(),
        }
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            holder = self.read_holder()
            if steal_stale_after is not None and holder is not None and self._holder_is_dead(holder):
                age = time.time() - holder.get("mtime", time.time())
                if age >= steal_stale_after:
                    self.steal()
                    return self.acquire(owner=owner, steal_stale_after=0.0)
            raise LeaseUnavailable(
                f"GPU lease already held at {self.path} by "
                f"{(holder or {}).get('owner', 'unknown')}",
                {"path": str(self.path), "holder": holder},
            )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        self.metadata = payload
        self._acquired = True
        return self

    def release(self) -> dict[str, Any]:
        """Release the lease if this object holds it. Idempotent."""
        if not self._acquired:
            return {"released": False, "reason": "not_held_by_this_object"}
        holder = self.read_holder()
        if holder is not None and holder.get("pid") not in (None, os.getpid()):
            # Someone else's lease replaced ours; do not delete their file.
            return {"released": False, "reason": "holder_changed", "holder": holder}
        try:
            self.path.unlink()
            released, reason = True, None
        except FileNotFoundError:
            released, reason = False, "already_removed"
        self._acquired = False
        return {"released": released, "reason": reason, "path": str(self.path)}

    def steal(self) -> dict[str, Any]:
        """Remove a lease whose owning process is provably gone.

        Only used for stale-lease recovery. A live holder is never stolen from.
        """
        holder = self.read_holder()
        if holder is not None and not self._holder_is_dead(holder):
            raise LeaseUnavailable(
                f"refusing to steal a live GPU lease held by {holder.get('owner')}",
                {"path": str(self.path), "holder": holder},
            )
        try:
            self.path.unlink()
            return {"stolen": True, "previousHolder": holder}
        except FileNotFoundError:
            return {"stolen": False, "previousHolder": None}

    def read_holder(self) -> dict[str, Any] | None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
            return None
        try:
            holder = json.loads(raw)
        except json.JSONDecodeError:
            return {"owner": None, "pid": None, "unparsable": True, "mtime": self.path.stat().st_mtime}
        if isinstance(holder, dict):
            holder.setdefault("mtime", self.path.stat().st_mtime)
        return holder

    @staticmethod
    def _holder_is_dead(holder: dict[str, Any]) -> bool:
        pid = holder.get("pid")
        if not isinstance(pid, int):
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            # Exists but belongs to another user: treat as alive.
            return False
        return False

    @property
    def held(self) -> bool:
        return self._acquired

    def __enter__(self) -> "GpuLease":
        if not self._acquired:
            self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.release()


# ---------------------------------------------------------------------------
# Receipt assembly (reusing the #31 contract)
# ---------------------------------------------------------------------------


def build_gate_receipt(
    *,
    run_identity: dict[str, Any],
    tensor_parallel: int,
    pre_run: dict[str, Any],
    state: dict[str, Any],
    post_stage: dict[str, Any] | None = None,
    owned_pids: Sequence[int] | None = None,
    thresholds: GateThresholds = DEFAULT_THRESHOLDS,
) -> dict[str, Any]:
    """Assemble a #31-shaped receipt for the gate's before/after evidence.

    The snapshot is built with :func:`kaggle_telemetry.make_snapshot`, so gate
    evidence and finalist stability evidence share one per-GPU shape and the same
    schema describes both.
    """
    classified = classify_gpu_processes(state, owned_pids=set(owned_pids or ()))
    processes = [row for rows in classified.values() for row in rows]
    snapshot = make_snapshot(
        "before_measured_loop",
        timestamp=utc_now_iso(),
        gpu_samples=state.get("gpus") or [],
        gpu_processes=processes,
        owned_pids=list(owned_pids or ()),
        run_identity=run_identity,
    )
    return {
        "schemaVersion": RECEIPT_SCHEMA_VERSION,
        "runIdentity": dict(run_identity),
        "tensorParallel": tensor_parallel,
        "gpuCount": len(state.get("gpus") or []),
        "nvidiaSmiAvailable": bool(state.get("available")),
        "snapshots": [snapshot],
        "requests": [],
        "resourceGate": {
            "preRun": pre_run,
            "postStage": post_stage,
            "thresholds": thresholds.as_dict(),
            "thresholdRationale": THRESHOLD_RATIONALE,
        },
    }


__all__ = [
    "SCHEMA_VERSION",
    "BLOCKED_CATEGORY",
    "OWNED",
    "KNOWN_RESIDUE",
    "FOREIGN_UNKNOWN",
    "OWNERSHIP_CLASSES",
    "GateThresholds",
    "DEFAULT_THRESHOLDS",
    "GateError",
    "LeaseUnavailable",
    "GpuLease",
    "assert_thresholds_unmodified",
    "sample_gpu_state",
    "classify_process",
    "classify_gpu_processes",
    "required_gpu_indices",
    "evaluate_pre_run_gate",
    "require_clean_pre_run",
    "reapable_residue_pids",
    "terminate_owned_residue",
    "quarantine_after_stage",
    "detect_mid_run_contamination",
    "build_gate_receipt",
]
