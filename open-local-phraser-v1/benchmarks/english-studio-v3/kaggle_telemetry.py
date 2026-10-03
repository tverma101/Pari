#!/usr/bin/env python3
"""Per-GPU telemetry receipts and deterministic warm-stability drift analysis.

This module is the reusable receipt/analysis half of Issue #31. It is pure CPU
and stdlib-only: it never starts a notebook, talks to the Kaggle control plane,
or reads a live accelerator. Runners own acquisition (running ``nvidia-smi``
and recording snapshots); this module owns the receipt shape and the
deterministic math so every finalist is judged by the same rule.

Two properties are load-bearing:

1. A summed memory number can never hide GPU asymmetry. Every series is keyed
   by GPU index and analyzed independently. A cross-GPU total is reported only
   as a secondary roll-up that is explicitly marked non-authoritative, and the
   asymmetry verdict is derived from the per-GPU spread, never from the total.
2. Repeated warm requests are a distribution, not a sample. Latency is
   summarized over the whole loop, and drift compares an early window against a
   late window taken in request order.

Flags are conservative engineering heuristics, not scientific leak thresholds.
Each rule carries the numbers it fired on and its justification lives in
``DRIFT_RULE_RATIONALE``, so a rule can be retuned with evidence rather than by
eyeballing logs.
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

RECEIPT_SCHEMA_VERSION = 1

# Lifecycle points the issue requires a snapshot at, in order. A partial run is
# still reportable, but missing stages are listed so a thin receipt is visible
# rather than silently passing.
SNAPSHOT_STAGES = (
    "before_start",
    "after_model_load",
    "after_warmup",
    "before_measured_loop",
    "during_measured_loop",
    "after_measured_loop",
    "after_shutdown",
)

# Requests per early/late latency window. Windows are trimmed rather than
# whole-loop so a single slow cold-start request cannot manufacture drift.
WINDOW_REQUESTS = 3

# Minimum measured-loop samples before latency drift is judged at all. Below
# this the receipt reports insufficient_samples instead of guessing.
MIN_LATENCY_SAMPLES = 4

# Absolute VRAM growth (MiB) from the warm baseline to the end of the measured
# loop that counts as material. 256 MiB is roughly one T4's worth of KV-cache
# slack for a small candidate and sits well above warmed-allocator noise, so it
# is deliberately coarse.
VRAM_DRIFT_ABS_MIB = 256.0

# Fraction of total VRAM that growth must also reach before the drift flag
# fires. Both the absolute and the relative bar must hold, so a small absolute
# wobble stays quiet regardless of card size.
VRAM_DRIFT_REL_FRACTION = 0.02

# Residual total VRAM (MiB) still held after shutdown that fails cleanup.
# Cleanup is about owned processes releasing memory, so this is checked against
# a low bar rather than demanding a byte-exact zero.
CLEANUP_RESIDUAL_MIB = 64.0

# Relative and absolute late/early latency degradation thresholds.
LATENCY_DRIFT_REL = 0.25
LATENCY_DRIFT_ABS_SECONDS = 0.05

# Per-GPU VRAM spread that counts as asymmetric occupancy.
GPU_ASYMMETRY_MIB = 512.0

# Percentiles reported for every latency metric.
PERCENTILES = (50, 95)

DRIFT_RULE_RATIONALE: dict[str, str] = {
    "vram_warm_to_end": (
        f"Fires when warm-baseline to end-of-loop VRAM growth is both "
        f">= {VRAM_DRIFT_ABS_MIB:.0f} MiB and >= {VRAM_DRIFT_REL_FRACTION:.0%} of total "
        "VRAM. A conservative engineering threshold rather than a scientific leak "
        "rate: it is set to clear warmed-allocator noise on a T4 while still "
        "catching a cache or handle that is genuinely never released."
    ),
    "vram_peak_to_end": (
        f"Fires when peak-to-end-of-loop headroom stays under {VRAM_DRIFT_ABS_MIB:.0f} MiB "
        "on a loop that also drifted warm-to-end, meaning the loop ended near its "
        "worst observed state instead of settling back."
    ),
    "vram_stepwise": (
        f"Fires on a non-decreasing in-loop series whose late-window mean is at least "
        f"{VRAM_DRIFT_ABS_MIB:.0f} MiB above its early-window mean. Catches leak-like "
        "growth that a single endpoint comparison misses when the final request "
        "happens to free memory."
    ),
    "vram_post_shutdown": (
        f"Fires when post-shutdown VRAM on any GPU stays at or above "
        f"{CLEANUP_RESIDUAL_MIB:.0f} MiB. Memory that survives a shutdown is residual "
        "evidence, not noise."
    ),
    "latency_early_vs_late": (
        f"Fires when the late p95 of a metric is both >= {LATENCY_DRIFT_REL:.0%} above and "
        f">= {LATENCY_DRIFT_ABS_SECONDS:.3f}s above the early p95. Warm-up is normal; "
        "sustained post-warm degradation is not."
    ),
    "latency_insufficient_samples": (
        f"Reported instead of a verdict when fewer than {MIN_LATENCY_SAMPLES} measured "
        "requests exist. A two-request loop cannot separate a real trend from "
        "request-to-request variance."
    ),
    "gpu_asymmetry": (
        f"Fires when any GPU's warm-baseline or end-of-loop VRAM differs from the lowest "
        f"GPU by >= {GPU_ASYMMETRY_MIB:.0f} MiB, or when the loop ends with a GPU both "
        "materially below the others and carrying no owned process. A single summed "
        "number hides both shapes."
    ),
    "cleanup": (
        "Cleanup is verified only when every owned process is gone AND residual VRAM is "
        "below the residual threshold. Anything else is reported as failed with the "
        "surviving PIDs and per-GPU residual memory, never as a silent pass."
    ),
}

#: Latency metrics summarized over the loop. Names match the Issue #29
#: progressive useful-option contract so receipts join to output rows without
#: field renaming.
LATENCY_METRICS = (
    "firstTokenLatencySeconds",
    "firstCandidateLatencySeconds",
    "firstThreeCandidatesLatencySeconds",
    "firstTenCandidatesLatencySeconds",
    "latencySeconds",
)

# Column order used by :func:`parse_nvidia_smi_csv`. Declared once so parsing
# stays a single contract rather than an inline split.
NVIDIA_SMI_COLUMNS = (
    "index",
    "uuid",
    "name",
    "memory.used",
    "memory.free",
    "memory.total",
    "utilization.gpu",
)


def _to_int(value: str) -> int | None:
    text = (value or "").strip()
    if not text or text.lower() in {"n/a", "na", "-", "none", "null"}:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _to_float(value: str) -> float | None:
    text = (value or "").strip()
    if not text or text.lower() in {"n/a", "na", "-", "none", "null"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _split_row(line: str, width: int) -> list[str]:
    """Split a CSV row to exactly ``width`` fields, tolerating commas in names."""
    parts = [part.strip() for part in line.split(",")]
    if len(parts) < width:
        return parts + [""] * (width - len(parts))
    if len(parts) > width:
        # A device name containing a comma must not shift the later columns.
        return parts[: width - 1] + [",".join(parts[width - 1 :])]
    return parts


def parse_nvidia_smi_csv(text: str, *, stage: str = "unspecified") -> list[dict[str, Any]]:
    """Parse ``nvidia-smi`` GPU CSV into per-GPU snapshot dicts.

    Tolerant by design. ``nvidia-smi`` prints ``[N/A]`` for a GPU in a
    transient state, and a partially reported row must degrade that one GPU's
    fields to ``None`` rather than abort the receipt. Rows whose index is
    unreadable are dropped; a row with a readable index but missing memory or
    utilization is kept, because "this GPU reported no memory number" is itself
    evidence.
    """
    samples: list[dict[str, Any]] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = _split_row(line, len(NVIDIA_SMI_COLUMNS))
        index = _to_int(parts[0])
        if index is None:
            continue
        samples.append(
            {
                "gpuIndex": index,
                "uuid": parts[1] or None,
                "name": parts[2] or None,
                "usedMiB": _to_int(parts[3]),
                "freeMiB": _to_int(parts[4]),
                "totalMiB": _to_int(parts[5]),
                "utilizationPercent": _to_int(parts[6]),
                "stage": stage,
            }
        )
    return samples


def parse_nvidia_smi_processes(text: str) -> list[dict[str, Any]]:
    """Parse ``nvidia-smi --query-compute-apps`` CSV rows.

    Each row is ``pid, process_name, used_gpu_memory``. Unreadable PIDs are
    dropped; a readable PID with a missing memory figure is retained so a
    surviving owned process stays visible for cleanup proof.
    """
    rows: list[dict[str, Any]] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = _split_row(line, 3)
        pid = _to_int(parts[0])
        if pid is None:
            continue
        rows.append(
            {
                "pid": pid,
                "processName": parts[1] or None,
                "usedMiB": _to_int(parts[2]),
            }
        )
    return rows


def make_snapshot(
    stage: str,
    *,
    timestamp: str | None = None,
    gpu_samples: Sequence[dict[str, Any]] | None = None,
    gpu_processes: Sequence[dict[str, Any]] | None = None,
    owned_pids: Sequence[int] | None = None,
    run_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one lifecycle snapshot with a normalized, per-GPU shape.

    ``gpu_samples`` is a list of per-GPU dicts (e.g. from
    :func:`parse_nvidia_smi_csv`). They are stored under ``gpus`` as an ordered
    list and are never collapsed into a single number. When ``gpu_processes``
    is supplied the same process list is attached to each GPU row and the owned
    subset is marked, which is what cleanup verification later reads.
    """
    owned = set(owned_pids or [])
    processes = [dict(p) for p in (gpu_processes or [])]
    gpus: list[dict[str, Any]] = []
    for sample in gpu_samples or []:
        entry = dict(sample)
        entry.setdefault("stage", stage)
        if gpu_processes is not None:
            entry["processes"] = [dict(p) for p in processes]
        entry["ownedProcessIds"] = sorted(
            {p["pid"] for p in processes if p.get("pid") in owned}
        )
        gpus.append(entry)
    snapshot: dict[str, Any] = {
        "stage": stage,
        "timestamp": timestamp,
        "gpus": gpus,
    }
    if run_identity is not None:
        snapshot["runIdentity"] = dict(run_identity)
    return snapshot


def _snapshot_order(snapshot: dict[str, Any]) -> int:
    stage = snapshot.get("stage")
    try:
        return SNAPSHOT_STAGES.index(stage)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        # Unknown stages (including free-form "during_measured_loop" repeats)
        # sort after the canonical lifecycle points, preserving input order.
        return len(SNAPSHOT_STAGES)


def _gpu_indices(snapshots: Sequence[dict[str, Any]]) -> list[int]:
    return sorted(
        {
            gpu["gpuIndex"]
            for snapshot in snapshots
            for gpu in (snapshot.get("gpus") or [])
            if isinstance(gpu.get("gpuIndex"), int) and not isinstance(gpu.get("gpuIndex"), bool)
        }
    )


def _ordered_unique(values: Iterable[Any]) -> list[Any]:
    seen: list[Any] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def build_resource_receipt(
    *,
    run_identity: dict[str, Any],
    snapshots: Sequence[dict[str, Any]],
    requests: Sequence[dict[str, Any]] | None = None,
    tensor_parallel: int = 1,
    nvidia_smi_available: bool = True,
    runtime_crashes: Sequence[dict[str, Any]] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Assemble a complete Issue #31 resource receipt.

    This only structures evidence; it renders no verdict. Call
    :func:`analyze_resource_receipt` for the machine-readable drift,
    asymmetry, distribution, and cleanup analysis that attaches to it.
    """
    ordered = sorted(snapshots, key=_snapshot_order)
    observed = _ordered_unique(s.get("stage") for s in ordered if s.get("stage"))
    receipt: dict[str, Any] = {
        "schemaVersion": RECEIPT_SCHEMA_VERSION,
        "runIdentity": dict(run_identity),
        "tensorParallel": tensor_parallel,
        "gpuCount": len(_gpu_indices(ordered)),
        "nvidiaSmiAvailable": bool(nvidia_smi_available),
        "snapshots": list(ordered),
        "requiredStages": list(SNAPSHOT_STAGES),
        "observedStages": observed,
        "missingStages": [s for s in SNAPSHOT_STAGES if s not in observed],
        "requests": [dict(r) for r in (requests or [])],
        "runtimeCrashes": [dict(c) for c in (runtime_crashes or [])],
    }
    if notes is not None:
        receipt["notes"] = notes
    return receipt


# ---------------------------------------------------------------------------
# Distributions over the warm loop
# ---------------------------------------------------------------------------


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def utc_now_iso() -> str:
    """Current UTC instant as a second-resolution ISO-8601 string.

    Shared so receipt snapshots and the #57 resource gate stamp identical
    timestamps without each rolling its own clock format.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _finite(values: Iterable[Any]) -> list[float]:
    """Keep finite numeric samples, preserving input order."""
    out: list[float] = []
    for value in values:
        if not _is_number(value):
            continue
        number = float(value)
        if math.isfinite(number):
            out.append(number)
    return out


def _percentile(sorted_values: Sequence[float], pct: float) -> float | None:
    """Linear-interpolated percentile over an already-sorted list."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (len(sorted_values) - 1) * (pct / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(sorted_values[int(rank)])
    weight = rank - low
    return float(sorted_values[low] * (1 - weight) + sorted_values[high] * weight)


def summarize_distribution(values: Iterable[Any]) -> dict[str, Any]:
    """Summarize one metric across the whole repeated-request loop.

    ``nObserved`` counts only finite numeric samples and ``nMissing`` records
    values the loop did not produce (for example an unmet first-10 threshold),
    so a loop that never reached a threshold cannot masquerade as a fast one.
    """
    raw = list(values)
    numbers = sorted(_finite(raw))
    observed = len(numbers)
    result: dict[str, Any] = {
        "nObserved": observed,
        "nMissing": len(raw) - observed,
        "minSeconds": numbers[0] if numbers else None,
        "maxSeconds": numbers[-1] if numbers else None,
        "meanSeconds": round(statistics.fmean(numbers), 6) if numbers else None,
    }
    for pct in PERCENTILES:
        result[f"p{pct}Seconds"] = round(_percentile(numbers, pct), 6) if numbers else None
    return result


def _retry_counts(requests: Sequence[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for request in requests:
        for retry in request.get("retries") or []:
            reason = str(retry.get("reason") or "unspecified")
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def warm_request_distributions(requests: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Summarize repeated warm-request behavior over the whole loop.

    Per-request-class distributions (short lexical, sentence transform, Word
    Studio multi-option, long rewrite) stay separate because mixing them would
    hide a slow class behind a fast one. The ``overall`` roll-up is reported in
    addition to, never instead of, the per-class numbers.
    """
    per_class: dict[str, dict[str, Any]] = {}
    for request in requests:
        request_class = str(request.get("requestClass") or "unclassified")
        bucket = per_class.setdefault(request_class, {"requests": 0, "metrics": {}})
        bucket["requests"] += 1
        for metric in LATENCY_METRICS:
            bucket["metrics"].setdefault(metric, []).append(request.get(metric))

    classes = {
        request_class: {
            "requests": bucket["requests"],
            "metrics": {
                metric: summarize_distribution(values)
                for metric, values in sorted(bucket["metrics"].items())
            },
        }
        for request_class, bucket in sorted(per_class.items())
    }

    failures = [r for r in requests if r.get("failed")]
    parser_failures = [r for r in failures if r.get("parserOrProtocolFailure")]
    runtime_failures = [r for r in failures if not r.get("parserOrProtocolFailure")]
    total = len(requests)
    return {
        "requestCount": total,
        "perClass": classes,
        "overall": {
            metric: summarize_distribution(r.get(metric) for r in requests)
            for metric in LATENCY_METRICS
        },
        "failures": {
            "total": len(failures),
            "rate": round(len(failures) / total, 6) if total else 0.0,
            "runtime": len(runtime_failures),
            "parserOrProtocol": len(parser_failures),
        },
        "oomCount": sum(1 for r in requests if r.get("oom")),
        "retryCountsByReason": _retry_counts(requests),
    }


# ---------------------------------------------------------------------------
# VRAM drift, per GPU
# ---------------------------------------------------------------------------


def _stage_used_series(
    snapshots: Sequence[dict[str, Any]], stage: str, gpu_index: int | None = None
) -> list[int | None]:
    """Ordered ``usedMiB`` values for one stage, optionally filtered by GPU."""
    out: list[int | None] = []
    for snapshot in snapshots:
        if snapshot.get("stage") != stage:
            continue
        for gpu in snapshot.get("gpus") or []:
            if gpu_index is not None and gpu.get("gpuIndex") != gpu_index:
                continue
            used = gpu.get("usedMiB")
            out.append(used if _is_number(used) else None)
    return out


def _in_loop_series(snapshots: Sequence[dict[str, Any]], gpu_index: int) -> list[int]:
    """Ordered in-loop ``usedMiB`` values for a single GPU."""
    out: list[int] = []
    for snapshot in snapshots:
        if snapshot.get("stage") != "during_measured_loop":
            continue
        for gpu in snapshot.get("gpus") or []:
            if gpu.get("gpuIndex") != gpu_index:
                continue
            used = gpu.get("usedMiB")
            if _is_number(used):
                out.append(int(used))
    return out


def _gpu_total_mib(snapshots: Sequence[dict[str, Any]], gpu_index: int) -> int | None:
    for snapshot in snapshots:
        for gpu in snapshot.get("gpus") or []:
            if gpu.get("gpuIndex") == gpu_index and _is_number(gpu.get("totalMiB")):
                return int(gpu["totalMiB"])
    return None


def _is_nondecreasing(values: Sequence[int]) -> bool:
    return all(b >= a for a, b in zip(values, values[1:]))


def analyze_vram_drift(receipt: dict[str, Any], gpu_index: int) -> dict[str, Any]:
    """VRAM drift analysis for one GPU.

    Called per GPU index by :func:`analyze_resource_receipt`. This is the core
    of the anti-symmetry requirement: one GPU's analysis never consults another
    GPU's numbers, so a healthy GPU 0 cannot mask a leaking GPU 1.
    """
    snapshots = receipt.get("snapshots") or []

    def first(stage: str) -> int | None:
        values = _stage_used_series(snapshots, stage, gpu_index)
        return values[0] if values else None

    warm = first("after_warmup")
    end = first("after_measured_loop")
    shutdown = first("after_shutdown")
    loop = _in_loop_series(snapshots, gpu_index)
    total_mib = _gpu_total_mib(snapshots, gpu_index)

    analysis: dict[str, Any] = {
        "gpuIndex": gpu_index,
        "warmBaselineMiB": warm,
        "maxMiB": max(loop) if loop else None,
        "endOfLoopMiB": end,
        "postShutdownMiB": shutdown,
        "totalMiB": total_mib,
        "inLoopSamples": len(loop),
        "inLoopSeriesMiB": loop,
        "absDriftMiB": None,
        "pctDriftPercent": None,
        "absPostShutdownResidualMiB": None,
        "flags": [],
        "flagsFired": False,
    }

    abs_drift: int | None = None
    if warm is not None and end is not None:
        abs_drift = end - warm
        analysis["absDriftMiB"] = abs_drift
        if warm > 0:
            analysis["pctDriftPercent"] = round(100.0 * abs_drift / warm, 4)
    if warm is not None and shutdown is not None:
        analysis["absPostShutdownResidualMiB"] = shutdown - warm

    # Rule 1: warm -> end clears both the absolute and the relative bar.
    if abs_drift is not None and abs_drift >= VRAM_DRIFT_ABS_MIB:
        relative_bar = (total_mib * VRAM_DRIFT_REL_FRACTION) if total_mib else 0.0
        if abs_drift >= relative_bar:
            analysis["flags"].append("vram_warm_to_end")

    # Rule 2: thin peak-to-end headroom on a loop that already drifted.
    peak = analysis["maxMiB"]
    if (
        peak is not None
        and end is not None
        and warm is not None
        and abs_drift is not None
        and abs_drift >= VRAM_DRIFT_ABS_MIB
        and (peak - end) < VRAM_DRIFT_ABS_MIB
    ):
        analysis["flags"].append("vram_peak_to_end")

    # Rule 3: stepwise leak-like growth visible inside the loop itself.
    if len(loop) >= 2 and _is_nondecreasing(loop):
        early = loop[:WINDOW_REQUESTS]
        late = loop[-WINDOW_REQUESTS:]
        if early and late and statistics.fmean(late) - statistics.fmean(early) >= VRAM_DRIFT_ABS_MIB:
            analysis["flags"].append("vram_stepwise")

    # Rule 4: memory survived a shutdown.
    if shutdown is not None and shutdown >= CLEANUP_RESIDUAL_MIB:
        analysis["flags"].append("vram_post_shutdown")

    analysis["flagsFired"] = bool(analysis["flags"])
    return analysis


# ---------------------------------------------------------------------------
# Latency drift, early window vs late window
# ---------------------------------------------------------------------------


def analyze_latency_drift(requests: Sequence[dict[str, Any]], metric: str) -> dict[str, Any]:
    """Compare an early window of warm requests against a late window.

    Windows are cut from the request sequence in its original order and each
    window's p95 is computed only over that window. Sorting the full series
    before slicing would guarantee a late window slower than an early one and
    manufacture drift out of request-to-request variance, so it is avoided.
    Callers pass measured-loop requests only, with warm-up requests excluded.
    """
    ordered = _finite(r.get(metric) for r in requests)
    result: dict[str, Any] = {
        "metric": metric,
        "nSamples": len(ordered),
        "windowRequests": WINDOW_REQUESTS,
        "earlyWindowSeconds": None,
        "lateWindowSeconds": None,
        "earlyP95Seconds": None,
        "lateP95Seconds": None,
        "absDeltaSeconds": None,
        "pctDeltaPercent": None,
        "insufficientSamples": len(ordered) < MIN_LATENCY_SAMPLES,
        "flags": [],
        "flagsFired": False,
        "rule": DRIFT_RULE_RATIONALE["latency_early_vs_late"],
    }
    if result["insufficientSamples"]:
        result["flags"].append("latency_insufficient_samples")
        return result

    early = ordered[:WINDOW_REQUESTS]
    late = ordered[-WINDOW_REQUESTS:]
    early_p95 = _percentile(sorted(early), 95)
    late_p95 = _percentile(sorted(late), 95)
    result["earlyWindowSeconds"] = [round(v, 6) for v in early]
    result["lateWindowSeconds"] = [round(v, 6) for v in late]
    result["earlyP95Seconds"] = round(early_p95, 6) if early_p95 is not None else None
    result["lateP95Seconds"] = round(late_p95, 6) if late_p95 is not None else None
    if early_p95 is not None and late_p95 is not None:
        abs_delta = late_p95 - early_p95
        result["absDeltaSeconds"] = round(abs_delta, 6)
        if early_p95 > 0:
            result["pctDeltaPercent"] = round(100.0 * abs_delta / early_p95, 4)
            if abs_delta >= LATENCY_DRIFT_ABS_SECONDS and abs_delta / early_p95 >= LATENCY_DRIFT_REL:
                result["flags"].append("latency_early_vs_late")
    result["flagsFired"] = "latency_early_vs_late" in result["flags"]
    return result


# ---------------------------------------------------------------------------
# GPU asymmetry and cleanup proof
# ---------------------------------------------------------------------------


def analyze_gpu_asymmetry(per_gpu: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Flag occupancy asymmetry from the per-GPU analyses.

    Reads only ``warmBaselineMiB`` / ``endOfLoopMiB`` per GPU, never a summed
    total, so the verdict survives any future addition of an aggregate field.
    """
    result: dict[str, Any] = {
        "gpuCount": len(per_gpu),
        "maxWarmBaselineSpreadMiB": None,
        "maxEndOfLoopSpreadMiB": None,
        "perGpuWarmBaselineMiB": {str(g["gpuIndex"]): g.get("warmBaselineMiB") for g in per_gpu},
        "perGpuEndOfLoopMiB": {str(g["gpuIndex"]): g.get("endOfLoopMiB") for g in per_gpu},
        "flags": [],
        "flagsFired": False,
        "rule": DRIFT_RULE_RATIONALE["gpu_asymmetry"],
    }
    for field, key in (
        ("warmBaselineMiB", "maxWarmBaselineSpreadMiB"),
        ("endOfLoopMiB", "maxEndOfLoopSpreadMiB"),
    ):
        values = [int(g[field]) for g in per_gpu if _is_number(g.get(field))]
        if len(values) >= 2:
            result[key] = max(values) - min(values)
    if (
        result["maxWarmBaselineSpreadMiB"] is not None
        and result["maxWarmBaselineSpreadMiB"] >= GPU_ASYMMETRY_MIB
    ) or (
        result["maxEndOfLoopSpreadMiB"] is not None
        and result["maxEndOfLoopSpreadMiB"] >= GPU_ASYMMETRY_MIB
    ):
        result["flags"].append("gpu_asymmetry")
    result["flagsFired"] = "gpu_asymmetry" in result["flags"]
    return result


def verify_cleanup(receipt: dict[str, Any], owned_pids: Sequence[int]) -> dict[str, Any]:
    """Prove or explicitly fail cleanup after the runtime wrapper exits.

    Cleanup is ``verified`` only when no owned PID appears in the post-shutdown
    snapshot's GPU process list and residual per-GPU VRAM is below
    :data:`CLEANUP_RESIDUAL_MIB`. Otherwise it is ``failed`` and carries the
    surviving PIDs plus per-GPU residual memory, so an unprovable cleanup is
    never reported as a pass.
    """
    owned = set(owned_pids)
    shutdown = None
    for snapshot in receipt.get("snapshots") or []:
        if snapshot.get("stage") == "after_shutdown":
            shutdown = snapshot
    if shutdown is None:
        return {
            "status": "failed",
            "reason": "no after_shutdown snapshot was recorded, so cleanup cannot be proven",
            "survivingOwnedPids": sorted(owned),
            "residualPerGpuMiB": {},
            "rule": DRIFT_RULE_RATIONALE["cleanup"],
        }

    surviving: set[int] = set()
    residual: dict[str, int | None] = {}
    for gpu in shutdown.get("gpus") or []:
        residual[str(gpu.get("gpuIndex"))] = gpu.get("usedMiB")
        for process in gpu.get("processes") or []:
            if process.get("pid") in owned:
                surviving.add(int(process["pid"]))
    heavy = {
        key: value
        for key, value in residual.items()
        if _is_number(value) and value >= CLEANUP_RESIDUAL_MIB
    }
    status = "verified" if not surviving and not heavy else "failed"
    reason: str | None = None
    if status == "failed":
        reasons = []
        if surviving:
            reasons.append(f"owned process(es) still present after shutdown: {sorted(surviving)}")
        if heavy:
            reasons.append(
                f"residual VRAM at or above {CLEANUP_RESIDUAL_MIB:.0f} MiB on GPU(s) {heavy}"
            )
        reason = "; ".join(reasons)
    return {
        "status": status,
        "reason": reason,
        "survivingOwnedPids": sorted(surviving),
        "residualPerGpuMiB": residual,
        "rule": DRIFT_RULE_RATIONALE["cleanup"],
    }


# ---------------------------------------------------------------------------
# Top-level analysis
# ---------------------------------------------------------------------------


def _total_used_series(snapshots: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    series: list[dict[str, Any]] = []
    for snapshot in snapshots:
        used = [
            int(gpu["usedMiB"])
            for gpu in (snapshot.get("gpus") or [])
            if _is_number(gpu.get("usedMiB"))
        ]
        if used:
            series.append({"stage": snapshot.get("stage"), "totalUsedMiB": sum(used)})
    return series


def analyze_resource_receipt(
    receipt: dict[str, Any], owned_pids: Sequence[int] | None = None
) -> dict[str, Any]:
    """Attach the full Issue #31 analysis to a receipt.

    Returns the per-GPU VRAM drift analyses, the GPU-asymmetry verdict, the
    warm-request distributions, the early-vs-late latency drift per metric, the
    cleanup verdict, and the runtime crash count. This returned object is the
    machine-readable artifact #28 consumes.
    """
    snapshots = receipt.get("snapshots") or []
    per_gpu = [analyze_vram_drift(receipt, index) for index in _gpu_indices(snapshots)]
    requests = receipt.get("requests") or []
    return {
        "schemaVersion": RECEIPT_SCHEMA_VERSION,
        "perGpuVramDrift": per_gpu,
        "gpuAsymmetry": analyze_gpu_asymmetry(per_gpu),
        "distributions": warm_request_distributions(requests),
        "latencyDrift": {metric: analyze_latency_drift(requests, metric) for metric in LATENCY_METRICS},
        "cleanup": verify_cleanup(receipt, owned_pids or []),
        "runtimeCrashCount": len(receipt.get("runtimeCrashes") or []),
        "totalUsedMiBSeries": _total_used_series(snapshots),
        "totalUsedMiBNote": (
            "Secondary cross-GPU roll-up for display only. It cannot substitute for "
            "perGpuVramDrift and is not an input to gpuAsymmetry."
        ),
        "driftRules": dict(DRIFT_RULE_RATIONALE),
    }


__all__ = [
    "RECEIPT_SCHEMA_VERSION",
    "SNAPSHOT_STAGES",
    "LATENCY_METRICS",
    "DRIFT_RULE_RATIONALE",
    "parse_nvidia_smi_csv",
    "parse_nvidia_smi_processes",
    "make_snapshot",
    "build_resource_receipt",
    "summarize_distribution",
    "warm_request_distributions",
    "analyze_vram_drift",
    "analyze_latency_drift",
    "analyze_gpu_asymmetry",
    "verify_cleanup",
    "analyze_resource_receipt",
]
