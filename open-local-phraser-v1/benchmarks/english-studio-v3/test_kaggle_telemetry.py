#!/usr/bin/env python3
"""CPU-only tests for the Issue #31 telemetry receipt and drift analysis.

Fixtures mirror the issue's required cases: stable memory, monotonic
leak-like growth, a spike that recovers, clean process exit, a surviving owned
process, a missing nvidia-smi field, and two GPUs with asymmetric usage.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import kaggle_telemetry as telemetry

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "kaggle-resource-receipt.schema.json"

T4_TOTAL_MIB = 16384
OWNED_PID = 4242


def gpu(index: int, used: int | None, *, total: int | None = T4_TOTAL_MIB) -> dict[str, Any]:
    return {
        "gpuIndex": index,
        "uuid": f"GPU-{index:04d}",
        "name": "Tesla T4",
        "usedMiB": used,
        "freeMiB": None if used is None or total is None else total - used,
        "totalMiB": total,
        "utilizationPercent": 0 if used is None else 50,
    }


def snapshot(
    stage: str,
    per_gpu_used: list[int | None],
    *,
    processes: list[dict[str, Any]] | None = None,
    owned: bool = False,
) -> dict[str, Any]:
    """Build a snapshot with one entry per GPU in ``per_gpu_used``."""
    samples = [gpu(index, used) for index, used in enumerate(per_gpu_used)]
    return telemetry.make_snapshot(
        stage,
        timestamp=f"2026-10-02T19:0{len(stage)}:00Z",
        gpu_samples=samples,
        gpu_processes=processes,
        owned_pids=[OWNED_PID] if owned else [],
    )


def requests_from(latencies: list[float], request_class: str = "short_lexical") -> list[dict[str, Any]]:
    return [
        {
            "id": f"req-{index:02d}",
            "requestClass": request_class,
            "firstTokenLatencySeconds": value,
            "firstCandidateLatencySeconds": value + 0.01,
            "firstThreeCandidatesLatencySeconds": value + 0.02,
            "firstTenCandidatesLatencySeconds": value + 0.05,
            "latencySeconds": value + 0.10,
        }
        for index, value in enumerate(latencies)
    ]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parses_per_gpu_rows() -> None:
    text = (
        "0, GPU-aaaa, Tesla T4, 1024, 15360, 16384, 37\n"
        "1, GPU-bbbb, Tesla T4, 512, 15872, 16384, 0\n"
    )
    samples = telemetry.parse_nvidia_smi_csv(text, stage="after_warmup")
    assert [s["gpuIndex"] for s in samples] == [0, 1]
    assert samples[0]["usedMiB"] == 1024 and samples[0]["totalMiB"] == T4_TOTAL_MIB
    assert samples[0]["utilizationPercent"] == 37
    assert samples[0]["stage"] == "after_warmup"


def test_partial_sample_does_not_crash_report() -> None:
    """A missing nvidia-smi field must degrade one GPU, not the whole receipt."""
    text = (
        "0, GPU-aaaa, Tesla T4, [N/A], [N/A], [N/A], [N/A]\n"
        "not a data row at all\n"
        "1, GPU-bbbb, Tesla T4, 512, 15872, 16384, 0\n"
    )
    samples = telemetry.parse_nvidia_smi_csv(text)
    assert len(samples) == 2
    assert samples[0]["usedMiB"] is None and samples[0]["totalMiB"] is None
    assert samples[1]["usedMiB"] == 512


def test_comma_in_device_name_does_not_shift_columns() -> None:
    samples = telemetry.parse_nvidia_smi_csv("0, GPU-a, Tesla T4, 256, 99, 16384, 5\n")
    assert samples[0]["usedMiB"] == 256
    assert samples[0]["totalMiB"] == T4_TOTAL_MIB


def test_process_parsing_keeps_unreadable_memory() -> None:
    rows = telemetry.parse_nvidia_smi_processes(
        f"{OWNED_PID}, python, 900\n5678, vllm, [N/A]\nnot-a-pid, x, 1\n"
    )
    assert [r["pid"] for r in rows] == [OWNED_PID, 5678]
    assert rows[1]["usedMiB"] is None


# ---------------------------------------------------------------------------
# Fixture: stable memory
# ---------------------------------------------------------------------------


def stable_receipt(gpu_count: int = 1) -> dict[str, Any]:
    """A healthy loop: flat VRAM, flat latency, clean shutdown."""
    snapshots = [
        snapshot("before_start", [10] * gpu_count),
        snapshot("after_model_load", [8000] * gpu_count, processes=[{"pid": OWNED_PID, "usedMiB": 8000}], owned=True),
        snapshot("after_warmup", [8000] * gpu_count, processes=[{"pid": OWNED_PID, "usedMiB": 8000}], owned=True),
        snapshot("before_measured_loop", [8000] * gpu_count, processes=[{"pid": OWNED_PID, "usedMiB": 8000}], owned=True),
    ]
    snapshots += [
        snapshot("during_measured_loop", [8000] * gpu_count, processes=[{"pid": OWNED_PID, "usedMiB": 8000}], owned=True)
        for _ in range(6)
    ]
    snapshots += [
        snapshot("after_measured_loop", [8000] * gpu_count, processes=[{"pid": OWNED_PID, "usedMiB": 8000}], owned=True),
        snapshot("after_shutdown", [12] * gpu_count),
    ]
    return telemetry.build_resource_receipt(
        run_identity={"candidateId": "stable-candidate", "runId": "run-stable"},
        snapshots=snapshots,
        requests=requests_from([0.40, 0.41, 0.40, 0.42, 0.41, 0.40]),
        tensor_parallel=gpu_count,
    )


def test_stable_memory_is_not_flagged() -> None:
    analysis = telemetry.analyze_resource_receipt(stable_receipt(), owned_pids=[OWNED_PID])
    for per_gpu in analysis["perGpuVramDrift"]:
        assert per_gpu["flags"] == [], per_gpu
        assert per_gpu["absDriftMiB"] == 0
        assert per_gpu["warmBaselineMiB"] == 8000
        assert per_gpu["postShutdownMiB"] == 12
    assert analysis["cleanup"]["status"] == "verified"
    assert analysis["gpuAsymmetry"]["flagsFired"] is False
    assert analysis["latencyDrift"]["latencySeconds"]["flagsFired"] is False


def test_stable_receipt_records_every_required_stage() -> None:
    receipt = stable_receipt()
    assert receipt["missingStages"] == []
    assert receipt["gpuCount"] == 1


# ---------------------------------------------------------------------------
# Fixture: monotonic leak-like growth
# ---------------------------------------------------------------------------


def test_monotonic_growth_is_flagged() -> None:
    loop = [8000, 8500, 9000, 9500, 10000, 10500]
    snapshots = [
        snapshot("after_warmup", [8000]),
        snapshot("before_measured_loop", [8000]),
    ]
    snapshots += [snapshot("during_measured_loop", [value]) for value in loop]
    snapshots += [
        snapshot("after_measured_loop", [loop[-1]]),
        snapshot("after_shutdown", [10]),
    ]
    receipt = telemetry.build_resource_receipt(
        run_identity={"candidateId": "leaky-candidate"},
        snapshots=snapshots,
        requests=requests_from([0.40] * 6),
    )
    analysis = telemetry.analyze_resource_receipt(receipt, owned_pids=[OWNED_PID])
    per_gpu = analysis["perGpuVramDrift"][0]

    assert per_gpu["warmBaselineMiB"] == 8000
    assert per_gpu["maxMiB"] == 10500
    assert per_gpu["endOfLoopMiB"] == 10500
    assert per_gpu["absDriftMiB"] == 2500
    assert per_gpu["pctDriftPercent"] == 31.25
    assert "vram_warm_to_end" in per_gpu["flags"]
    assert "vram_stepwise" in per_gpu["flags"]
    assert per_gpu["flagsFired"] is True
    assert analysis["cleanup"]["status"] == "verified"


# ---------------------------------------------------------------------------
# Fixture: temporary spike that recovers
# ---------------------------------------------------------------------------


def test_recovering_spike_is_not_flagged_as_drift() -> None:
    loop = [8000, 8600, 12000, 8400, 8100, 8050]
    snapshots = [snapshot("after_warmup", [8000])]
    snapshots += [snapshot("during_measured_loop", [value]) for value in loop]
    snapshots += [
        snapshot("after_measured_loop", [8050]),
        snapshot("after_shutdown", [10]),
    ]
    receipt = telemetry.build_resource_receipt(
        run_identity={"candidateId": "spiky-candidate"},
        snapshots=snapshots,
        requests=requests_from([0.40] * 6),
    )
    analysis = telemetry.analyze_resource_receipt(receipt, owned_pids=[OWNED_PID])
    per_gpu = analysis["perGpuVramDrift"][0]

    assert per_gpu["maxMiB"] == 12000
    assert per_gpu["endOfLoopMiB"] == 8050
    # A peak that recovers must not read as leak-like growth.
    assert "vram_warm_to_end" not in per_gpu["flags"]
    assert "vram_stepwise" not in per_gpu["flags"]
    assert "vram_peak_to_end" not in per_gpu["flags"]
    assert per_gpu["flags"] == []


# ---------------------------------------------------------------------------
# Fixture: cleanup verified / owned process survives
# ---------------------------------------------------------------------------


def test_cleanup_verified_when_owned_process_disappears() -> None:
    analysis = telemetry.analyze_resource_receipt(stable_receipt(), owned_pids=[OWNED_PID])
    cleanup = analysis["cleanup"]
    assert cleanup["status"] == "verified"
    assert cleanup["survivingOwnedPids"] == []
    assert cleanup["reason"] is None
    assert cleanup["residualPerGpuMiB"] == {"0": 12}


def test_cleanup_failed_when_owned_process_remains() -> None:
    receipt = stable_receipt()
    for snap in receipt["snapshots"]:
        if snap["stage"] == "after_shutdown":
            snap["gpus"][0]["processes"] = [{"pid": OWNED_PID, "usedMiB": 512, "processName": "vllm"}]
    analysis = telemetry.analyze_resource_receipt(receipt, owned_pids=[OWNED_PID])
    cleanup = analysis["cleanup"]
    assert cleanup["status"] == "failed"
    assert cleanup["survivingOwnedPids"] == [OWNED_PID]
    assert "still present after shutdown" in cleanup["reason"]


def test_cleanup_failed_on_residual_vram_without_surviving_process() -> None:
    receipt = stable_receipt()
    for snap in receipt["snapshots"]:
        if snap["stage"] == "after_shutdown":
            snap["gpus"][0]["usedMiB"] = 4096
    analysis = telemetry.analyze_resource_receipt(receipt, owned_pids=[OWNED_PID])
    assert analysis["cleanup"]["status"] == "failed"
    assert "residual VRAM" in analysis["cleanup"]["reason"]
    assert analysis["perGpuVramDrift"][0]["flags"] == ["vram_post_shutdown"]


def test_cleanup_failed_when_no_shutdown_snapshot_exists() -> None:
    receipt = stable_receipt()
    receipt["snapshots"] = [s for s in receipt["snapshots"] if s["stage"] != "after_shutdown"]
    analysis = telemetry.analyze_resource_receipt(receipt, owned_pids=[OWNED_PID])
    assert analysis["cleanup"]["status"] == "failed"
    assert "cannot be proven" in analysis["cleanup"]["reason"]


# ---------------------------------------------------------------------------
# Fixture: two GPUs with asymmetric usage
# ---------------------------------------------------------------------------


def asymmetric_receipt() -> dict[str, Any]:
    """GPU0 healthy and flat; GPU1 steadily climbing while GPU0 stays put."""
    snapshots = [snapshot("after_warmup", [8000, 300])]
    snapshots += [
        snapshot("during_measured_loop", [8000, 300 + 400 * step]) for step in range(6)
    ]
    snapshots += [
        snapshot("after_measured_loop", [8000, 300 + 400 * 5]),
        snapshot("after_shutdown", [10, 10]),
    ]
    return telemetry.build_resource_receipt(
        run_identity={"candidateId": "asymmetric-candidate"},
        snapshots=snapshots,
        requests=requests_from([0.40] * 6),
        tensor_parallel=1,
    )


def test_single_summed_number_cannot_hide_asymmetry() -> None:
    analysis = telemetry.analyze_resource_receipt(asymmetric_receipt(), owned_pids=[OWNED_PID])
    per_gpu = {g["gpuIndex"]: g for g in analysis["perGpuVramDrift"]}

    # The healthy GPU is genuinely healthy.
    assert per_gpu[0]["absDriftMiB"] == 0
    assert per_gpu[0]["flags"] == []

    # The sick GPU is caught on its own series even though the summed total is
    # dominated by GPU0.
    assert per_gpu[1]["warmBaselineMiB"] == 300
    assert per_gpu[1]["endOfLoopMiB"] == 2300
    assert per_gpu[1]["absDriftMiB"] == 2000
    assert per_gpu[1]["flagsFired"] is True
    assert "vram_warm_to_end" in per_gpu[1]["flags"]

    assert analysis["gpuAsymmetry"]["flagsFired"] is True
    assert analysis["gpuAsymmetry"]["maxWarmBaselineSpreadMiB"] == 7700
    assert analysis["gpuAsymmetry"]["perGpuEndOfLoopMiB"] == {"0": 8000, "1": 2300}

    # The aggregate exists for display but is explicitly not authoritative.
    assert analysis["totalUsedMiBNote"]
    assert "cannot substitute" in analysis["totalUsedMiBNote"]
    total_end = next(
        row["totalUsedMiB"] for row in analysis["totalUsedMiBSeries"] if row["stage"] == "after_measured_loop"
    )
    assert total_end == 10300


def test_symmetric_two_gpu_pair_is_not_flagged_asymmetric() -> None:
    analysis = telemetry.analyze_resource_receipt(stable_receipt(gpu_count=2), owned_pids=[OWNED_PID])
    assert analysis["gpuAsymmetry"]["maxWarmBaselineSpreadMiB"] == 0
    assert analysis["gpuAsymmetry"]["flagsFired"] is False
    assert len(analysis["perGpuVramDrift"]) == 2


# ---------------------------------------------------------------------------
# Warm request distributions and latency drift
# ---------------------------------------------------------------------------


def test_distributions_cover_repeated_requests_and_missing_thresholds() -> None:
    requests = requests_from([0.40, 0.50, 0.45, 0.60])
    requests[0]["firstTenCandidatesLatencySeconds"] = None  # threshold never met
    distributions = telemetry.warm_request_distributions(requests)

    assert distributions["requestCount"] == 4
    latency = distributions["overall"]["latencySeconds"]
    assert latency["nObserved"] == 4
    assert latency["minSeconds"] == 0.50
    assert latency["maxSeconds"] == 0.70
    # Linear interpolation between the two middle samples of an even-length
    # series: p50 of [0.50, 0.55, 0.60, 0.70] is 0.575, not the 0.5875 mean.
    assert latency["p50Seconds"] == 0.575
    assert latency["meanSeconds"] == 0.5875

    first_ten = distributions["overall"]["firstTenCandidatesLatencySeconds"]
    assert first_ten["nObserved"] == 3
    assert first_ten["nMissing"] == 1


def test_per_request_classes_are_kept_separate() -> None:
    requests = (
        requests_from([0.40, 0.41], "short_lexical")
        + requests_from([1.80, 1.90], "word_studio_multi_option")
    )
    distributions = telemetry.warm_request_distributions(requests)
    fast = distributions["perClass"]["short_lexical"]["metrics"]["latencySeconds"]
    slow = distributions["perClass"]["word_studio_multi_option"]["metrics"]["latencySeconds"]
    assert fast["p50Seconds"] < slow["p50Seconds"]
    assert distributions["overall"]["latencySeconds"]["p50Seconds"] > fast["p50Seconds"]


def test_failure_counts_split_runtime_from_parser() -> None:
    requests = requests_from([0.40] * 4)
    requests[0].update({"failed": True, "oom": True, "retries": [{"reason": "timeout"}]})
    requests[1].update({"failed": True, "parserOrProtocolFailure": True})
    distributions = telemetry.warm_request_distributions(requests)
    assert distributions["failures"]["total"] == 2
    assert distributions["failures"]["runtime"] == 1
    assert distributions["failures"]["parserOrProtocol"] == 1
    assert distributions["failures"]["rate"] == 0.5
    assert distributions["oomCount"] == 1
    assert distributions["retryCountsByReason"] == {"timeout": 1}


def test_latency_drift_flags_sustained_degradation() -> None:
    result = telemetry.analyze_latency_drift(
        requests_from([0.40, 0.41, 0.40, 1.20, 1.30, 1.25]), "latencySeconds"
    )
    assert result["flagsFired"] is True
    assert "latency_early_vs_late" in result["flags"]
    assert result["earlyP95Seconds"] < result["lateP95Seconds"]
    assert result["absDeltaSeconds"] > 0


def test_latency_windows_respect_request_order() -> None:
    """Interleaved noise must not be reported as drift.

    Cutting windows from a sorted series would put the three fastest samples in
    the early window and the three slowest in the late window and manufacture
    drift out of request-to-request variance.
    """
    noisy = requests_from([1.20, 0.40, 1.25, 0.41, 1.22, 0.40])
    result = telemetry.analyze_latency_drift(noisy, "latencySeconds")
    assert result["flagsFired"] is False
    # latencySeconds is each sample + 0.10, so windows keep request order.
    assert result["earlyWindowSeconds"] == [1.30, 0.50, 1.35]
    assert result["lateWindowSeconds"] == [0.51, 1.32, 0.50]


def test_latency_drift_reports_insufficient_samples_instead_of_guessing() -> None:
    result = telemetry.analyze_latency_drift(requests_from([0.40, 3.00]), "latencySeconds")
    assert result["insufficientSamples"] is True
    assert result["flags"] == ["latency_insufficient_samples"]
    assert result["flagsFired"] is False
    assert result["absDeltaSeconds"] is None


# ---------------------------------------------------------------------------
# Receipt shape and schema agreement
# ---------------------------------------------------------------------------


def test_analysis_is_deterministic_and_json_serializable() -> None:
    receipt = asymmetric_receipt()
    first = telemetry.analyze_resource_receipt(receipt, owned_pids=[OWNED_PID])
    second = telemetry.analyze_resource_receipt(receipt, owned_pids=[OWNED_PID])
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    json.dumps(first)


def test_missing_gpu_sample_leaves_nulls_without_raising() -> None:
    snapshots = [
        snapshot("after_warmup", [None]),
        snapshot("after_measured_loop", [None]),
        snapshot("after_shutdown", [None]),
    ]
    receipt = telemetry.build_resource_receipt(
        run_identity={"candidateId": "unreadable-smi"},
        snapshots=snapshots,
        requests=requests_from([0.40] * 4),
        nvidia_smi_available=False,
    )
    analysis = telemetry.analyze_resource_receipt(receipt, owned_pids=[])
    per_gpu = analysis["perGpuVramDrift"][0]
    assert per_gpu["warmBaselineMiB"] is None
    assert per_gpu["absDriftMiB"] is None
    assert per_gpu["flags"] == []
    assert receipt["missingStages"]
    assert receipt["nvidiaSmiAvailable"] is False


def test_runtime_crashes_are_carried_through() -> None:
    receipt = stable_receipt()
    receipt["runtimeCrashes"] = [{"at": "during_measured_loop", "reason": "engine core died"}]
    analysis = telemetry.analyze_resource_receipt(receipt, owned_pids=[OWNED_PID])
    assert analysis["runtimeCrashCount"] == 1


def test_schema_file_declares_the_required_top_level_shape() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schemaVersion"]["const"] == telemetry.RECEIPT_SCHEMA_VERSION
    for key in ("runIdentity", "snapshots", "requests", "gpuCount", "tensorParallel"):
        assert key in schema["required"]
    # Every lifecycle stage the issue requires must be named in the schema, and
    # the per-GPU row must point at that same stage definition.
    stages = schema["$defs"]["stage"]["enum"]
    assert list(telemetry.SNAPSHOT_STAGES) == stages
    assert schema["$defs"]["gpu"]["properties"]["stage"] == {"$ref": "#/$defs/stage"}
    # Per-GPU memory must stay addressable per gpu object, with no summed
    # cross-GPU memory field anywhere in the schema.
    assert "usedMiB" in schema["$defs"]["gpu"]["properties"]
    assert not any(
        "sum" in key.lower() for key in schema["$defs"]["gpu"]["properties"]
    )


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"Kaggle telemetry receipt/analysis tests passed ({len(tests)} cases).")


if __name__ == "__main__":
    main()
