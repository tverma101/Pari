#!/usr/bin/env python3
"""CPU-only tests for the Issue #57 GPU resource gate and single-owner lease.

Every `nvidia-smi` read, sleep, clock tick, and process signal is mocked, so
these tests never touch a real accelerator. The cases map onto the issue's
required test list.
"""
from __future__ import annotations

import json
import signal
import tempfile
from pathlib import Path
from typing import Any, Sequence

import kaggle_gpu_resource_gate as gate

T4_TOTAL_MIB = 16384
GPU0_UUID = "GPU-0000"
GPU1_UUID = "GPU-0001"

# A process name carrying the orchestrator allowlist fragment, used for the
# stale-residue fixture.
RESIDUE_NAME = "pari_bench_vllm_server"
RESIDUE_PID = 5150
# A PID the orchestrator has no handle on and does not recognize.
UNKNOWN_PID = 9999
RUN_OWNED_PID = 4242


def gpu_csv(used: Sequence[int | None], *, total: int = T4_TOTAL_MIB) -> str:
    """Render the `--query-gpu` CSV the mocked driver returns."""
    uuids = [GPU0_UUID, GPU1_UUID]
    lines = []
    for index, used_mib in enumerate(used):
        if used_mib is None:
            lines.append(f"{index}, {uuids[index]}, Tesla T4, [N/A], [N/A], [N/A], [N/A]")
            continue
        free = total - used_mib
        lines.append(f"{index}, {uuids[index]}, Tesla T4, {used_mib}, {free}, {total}, 0")
    return "\n".join(lines) + ("\n" if lines else "")


def process_csv(rows: Sequence[tuple[str, int, str, int | None]]) -> str:
    """Render the `--query-compute-apps` CSV the mocked driver returns."""
    out = []
    for gpu_uuid, pid, name, used in rows:
        used_text = "[N/A]" if used is None else str(used)
        out.append(f"{gpu_uuid}, {pid}, {name}, {used_text}")
    return "\n".join(out) + ("\n" if out else "")


def make_smi_runner(
    used: Sequence[int | None],
    processes: Sequence[tuple[str, int, str, int | None]] = (),
    *,
    gpu_rc: int = 0,
    compute_rc: int = 0,
    queue: Sequence[tuple[Sequence[int | None], Sequence[tuple[str, int, str, int | None]]]] | None = None,
) -> Any:
    """Build a mocked `nvidia-smi` runner.

    With ``queue``, successive reads walk the list, which is how the quarantine
    tests model memory that only releases after a cooldown.
    """
    calls: list[list[str]] = []
    state = {"read": 0}

    def runner(argv: Sequence[str]) -> tuple[int, str, str]:
        calls.append(list(argv))
        is_compute = any("compute-apps" in arg for arg in argv)
        if queue is not None:
            index = min(state["read"], len(queue) - 1)
            state["read"] += 1
            if is_compute:
                return compute_rc, process_csv(queue[index][1]), ""
            return gpu_rc, gpu_csv(queue[index][0]), ""
        if is_compute:
            return compute_rc, process_csv(processes), ""
        return gpu_rc, gpu_csv(used), ""

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def clean_state(*, used: Sequence[int | None] = (200, 200)) -> dict[str, Any]:
    return gate.sample_gpu_state(make_smi_runner(used))


def _step_clock(initial: float = 0.0) -> Any:
    """Monotonic clock that advances by one cooldown step per read."""
    state = {"t": float(initial)}

    def clock() -> float:
        value = state["t"]
        state["t"] += gate.COOLDOWN_POLL_SECONDS
        return value

    return clock


# 1. Both GPUs clean -> TP1/TP2 allowed


def test_clean_both_gpus_allows_tp1_and_tp2() -> None:
    state = clean_state()
    tp1 = gate.evaluate_pre_run_gate(state, tensor_parallel=1)
    tp2 = gate.evaluate_pre_run_gate(state, tensor_parallel=2)
    assert tp1["allowed"] is True and tp1["verdict"] == "clean"
    assert tp2["allowed"] is True
    assert tp1["requiredGpuIndices"] == [0]
    assert tp2["requiredGpuIndices"] == [0, 1]
    assert tp1["blockingReasons"] == [] and tp2["blockingReasons"] == []


# 2. Foreign process on GPU0 -> blocked, not OOM-tested


def test_foreign_process_on_gpu0_blocks() -> None:
    state = gate.sample_gpu_state(
        make_smi_runner((9000, 200), [(GPU0_UUID, UNKNOWN_PID, "jupyter-kernel", 4000)])
    )
    result = gate.evaluate_pre_run_gate(state, tensor_parallel=1)
    assert result["allowed"] is False
    assert result["verdict"] == gate.BLOCKED_CATEGORY
    assert any("foreign_or_unknown_compute" in reason for reason in result["blockingReasons"])
    gpu0 = next(row for row in result["perGpu"] if row["gpuIndex"] == 0)
    assert gpu0["blocked"] is True
    assert gpu0["processes"][0]["ownership"] == gate.FOREIGN_UNKNOWN


def test_blocked_gate_raises_and_never_reports_oom() -> None:
    """A contaminated gate must surface as infrastructure, not model capacity."""
    state = gate.sample_gpu_state(
        make_smi_runner((12000, 200), [(GPU0_UUID, UNKNOWN_PID, "someone-else", 8000)])
    )
    try:
        gate.require_clean_pre_run(state=state, tensor_parallel=1)
    except gate.GateError as exc:
        assert exc.category == gate.BLOCKED_CATEGORY
        assert "cuda_oom" not in json.dumps(exc.evidence)
        assert exc.evidence["verdict"] == gate.BLOCKED_CATEGORY
    else:
        raise AssertionError("contaminated GPU0 must block qualification")


# 3. Foreign process only on unused GPU1 -> TP1 proceeds with a warning


def test_foreign_on_unused_gpu1_warns_but_allows_tp1() -> None:
    state = gate.sample_gpu_state(
        make_smi_runner((200, 9000), [(GPU1_UUID, UNKNOWN_PID, "other-agent", 6000)])
    )
    result = gate.evaluate_pre_run_gate(state, tensor_parallel=1)
    assert result["allowed"] is True, "TP1 uses only GPU0, so GPU1 must not block"
    assert result["warnings"], "unused GPU contamination must still be recorded"
    assert "gpu1" in result["warnings"][0]
    gpu1 = next(row for row in result["perGpu"] if row["gpuIndex"] == 1)
    assert gpu1["required"] is False
    assert gpu1["foreignOrUnknownComputeMiB"] == 6000
    assert gpu1["blocked"] is False


# 4. TP2 with a process on either GPU -> blocked


def test_tp2_blocked_by_either_gpu() -> None:
    on_gpu1 = gate.sample_gpu_state(
        make_smi_runner((200, 9000), [(GPU1_UUID, UNKNOWN_PID, "other-agent", 6000)])
    )
    result1 = gate.evaluate_pre_run_gate(on_gpu1, tensor_parallel=2)
    assert result1["allowed"] is False
    assert any(reason.startswith("gpu1:") for reason in result1["blockingReasons"])

    on_gpu0 = gate.sample_gpu_state(
        make_smi_runner((9000, 200), [(GPU0_UUID, UNKNOWN_PID, "other-agent", 6000)])
    )
    result0 = gate.evaluate_pre_run_gate(on_gpu0, tensor_parallel=2)
    assert result0["allowed"] is False
    assert any(reason.startswith("gpu0:") for reason in result0["blockingReasons"])


# 5. Stale owned previous server -> cleanup attempted, then verified


def test_stale_owned_residue_is_cleaned_then_verified() -> None:
    state = gate.sample_gpu_state(
        make_smi_runner((6000, 200), [(GPU0_UUID, RESIDUE_PID, RESIDUE_NAME, 5000)])
    )
    pre_run = gate.evaluate_pre_run_gate(state, tensor_parallel=1)
    assert pre_run["allowed"] is False
    assert any("known_residue_processes_present" in r for r in pre_run["blockingReasons"])

    classified = gate.classify_gpu_processes(state)
    assert classified["0"][0]["ownership"] == gate.KNOWN_RESIDUE

    sent: list[tuple[int, int]] = []
    cleanup = gate.terminate_owned_residue(
        [RESIDUE_PID],
        classified=classified,
        signal_sender=lambda pid, sig: sent.append((pid, sig)),
        sleep=lambda _seconds: None,
    )
    assert cleanup["attempted"] == [RESIDUE_PID]
    assert cleanup["notKilled"] == []
    assert sent and sent[0][0] == RESIDUE_PID
    assert sent[0][1] == signal.SIGTERM

    after = gate.evaluate_pre_run_gate(clean_state(), tensor_parallel=1)
    assert after["allowed"] is True


# 6. Unknown PID is never killed


def test_unknown_pid_is_never_killed() -> None:
    state = gate.sample_gpu_state(
        make_smi_runner((9000, 200), [(GPU0_UUID, UNKNOWN_PID, "totally-unknown", 4000)])
    )
    classified = gate.classify_gpu_processes(state)
    assert classified["0"][0]["ownership"] == gate.FOREIGN_UNKNOWN

    sent: list[tuple[int, int]] = []
    result = gate.terminate_owned_residue(
        [UNKNOWN_PID],
        classified=classified,
        signal_sender=lambda pid, sig: sent.append((pid, sig)),
        sleep=lambda _seconds: None,
    )
    assert sent == [], "no signal may be sent to a foreign/unknown process"
    assert result["attempted"] == []
    assert result["notKilled"][0]["pid"] == UNKNOWN_PID
    assert result["notKilled"][0]["reason"] == "not_killed_foreign_or_unknown"


def test_run_owned_pid_is_not_reaped_as_residue() -> None:
    """This run's own live PID is OWNED, never eligible for the reap path."""
    state = gate.sample_gpu_state(
        make_smi_runner((9000, 200), [(GPU0_UUID, RUN_OWNED_PID, "vllm", 4000)])
    )
    classified = gate.classify_gpu_processes(state, owned_pids={RUN_OWNED_PID})
    assert classified["0"][0]["ownership"] == gate.OWNED
    assert gate.reapable_residue_pids(classified) == set()
    sent: list[tuple[int, int]] = []
    result = gate.terminate_owned_residue(
        [RUN_OWNED_PID],
        classified=classified,
        signal_sender=lambda pid, sig: sent.append((pid, sig)),
        sleep=lambda _seconds: None,
    )
    assert sent == []
    assert result["notKilled"][0]["observedOwnership"] == gate.OWNED


# 7. Residual memory after owned exit does not silently pass


def test_residual_memory_above_threshold_blocks_handoff() -> None:
    baseline = {"perGpu": [{"gpuIndex": 0, "usedMiB": 200}, {"gpuIndex": 1, "usedMiB": 200}]}
    runner = make_smi_runner((4400, 200))
    result = gate.quarantine_after_stage(
        tensor_parallel=1,
        baseline=baseline,
        smi_runner=runner,
        sleep=lambda _s: None,
        clock=_step_clock(),
        cooldown_seconds=0.0,
        signal_sender=lambda pid, sig: None,
    )
    assert result["clean"] is False
    assert result["verdict"] == gate.BLOCKED_CATEGORY
    assert any("residual_vram_mib" in reason for reason in result["blockingReasons"])
    gpu0 = next(r for r in result["residualPerGpu"] if r["gpuIndex"] == 0)
    assert gpu0["residualMiB"] == 4200
    assert gpu0["exceedsThreshold"] is True


def test_residual_memory_within_threshold_passes_handoff() -> None:
    baseline = {"perGpu": [{"gpuIndex": 0, "usedMiB": 200}, {"gpuIndex": 1, "usedMiB": 200}]}
    result = gate.quarantine_after_stage(
        tensor_parallel=1,
        baseline=baseline,
        smi_runner=make_smi_runner((300, 200)),
        sleep=lambda _s: None,
        clock=_step_clock(),
        cooldown_seconds=0.0,
        signal_sender=lambda pid, sig: None,
    )
    assert result["clean"] is True
    assert result["verdict"] == "clean_handoff"
    assert result["blockingReasons"] == []


def test_quarantine_reaps_residue_then_confirms_release() -> None:
    """Stale residue is signalled once, and the handoff waits for release."""
    baseline = {"perGpu": [{"gpuIndex": 0, "usedMiB": 200}, {"gpuIndex": 1, "usedMiB": 200}]}
    runner = make_smi_runner(
        (6000, 200),
        queue=[
            ((6000, 200), [(GPU0_UUID, RESIDUE_PID, RESIDUE_NAME, 5000)]),
            ((6000, 200), [(GPU0_UUID, RESIDUE_PID, RESIDUE_NAME, 5000)]),
            ((250, 200), []),
            ((250, 200), []),
        ],
    )
    sent: list[tuple[int, int]] = []
    result = gate.quarantine_after_stage(
        tensor_parallel=1,
        baseline=baseline,
        smi_runner=runner,
        sleep=lambda _s: None,
        clock=_step_clock(),
        cooldown_seconds=10.0,
        signal_sender=lambda pid, sig: sent.append((pid, sig)),
        terminate_grace_seconds=0.0,
    )
    assert sent, "owned residue must be signalled"
    assert all(pid == RESIDUE_PID for pid, _sig in sent)
    assert result["cleanupAttempt"]["attempted"] == [RESIDUE_PID]
    assert result["clean"] is True
    assert result["residueCleared"] is True


# 8. Two concurrent canonical workers contend for the same lease


def test_second_worker_cannot_take_a_held_lease() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "gpu.lease"
        first = gate.GpuLease(path=path, owner="worker-a").acquire()
        assert first.held is True
        holder = first.read_holder()
        assert holder["owner"] == "worker-a"
        assert holder["pid"] > 0

        second = gate.GpuLease(path=path, owner="worker-b")
        try:
            second.acquire()
        except gate.LeaseUnavailable as exc:
            assert exc.evidence["holder"]["owner"] == "worker-a"
        else:
            raise AssertionError("a second worker must not acquire a held lease")
        assert second.held is False

        first.release()
        second.acquire()
        assert second.held is True
        second.release()


def test_lease_is_not_stolen_from_a_live_holder() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "gpu.lease"
        holder = gate.GpuLease(path=path, owner="live-worker").acquire()
        thief = gate.GpuLease(path=path, owner="thief")
        try:
            thief.steal()
        except gate.LeaseUnavailable:
            pass
        else:
            raise AssertionError("a live lease must not be stolen")
        assert path.exists()
        holder.release()


def test_lease_context_manager_releases() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "gpu.lease"
        with gate.GpuLease(path=path, owner="ctx") as lease:
            assert lease.held is True
            assert path.exists()
        assert not path.exists()


def test_stale_lease_from_dead_process_is_reclaimed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "gpu.lease"
        # A PID that cannot be alive: os.kill raises ProcessLookupError.
        dead_pid = 2**30
        path.write_text(json.dumps({"owner": "crashed", "pid": dead_pid}), encoding="utf-8")
        lease = gate.GpuLease(path=path, owner="next-worker")
        lease.acquire(steal_stale_after=0.0)
        assert lease.held is True
        assert lease.read_holder()["owner"] == "next-worker"
        lease.release()


# 9. Clean baseline + genuine model OOM stays candidate/runtime evidence


def test_clean_gate_then_oom_is_candidate_evidence() -> None:
    """The gate must not claim an OOM, so a later OOM keeps its #53/#47 meaning."""
    state = clean_state()
    pre_run = gate.evaluate_pre_run_gate(state, tensor_parallel=1)
    assert pre_run["allowed"] is True
    assert pre_run["verdict"] == "clean"
    assert gate.BLOCKED_CATEGORY not in json.dumps(pre_run)


# 10. Contamination introduced mid-run invalidates timing comparability


def test_mid_run_contamination_invalidates_timings() -> None:
    mid = gate.sample_gpu_state(
        make_smi_runner((9000, 200), [(GPU0_UUID, UNKNOWN_PID, "intruder", 5000)])
    )
    result = gate.detect_mid_run_contamination(mid, tensor_parallel=1)
    assert result["contaminationDetected"] is True
    assert result["timingComparabilityValid"] is False
    assert result["verdict"] == gate.BLOCKED_CATEGORY
    assert result["contaminatedRequiredGpus"][0]["gpuIndex"] == 0


def test_mid_run_contamination_on_unused_gpu_does_not_invalidate_tp1() -> None:
    mid = gate.sample_gpu_state(
        make_smi_runner((9000, 9000), [(GPU1_UUID, UNKNOWN_PID, "intruder", 5000)])
    )
    result = gate.detect_mid_run_contamination(mid, tensor_parallel=1)
    assert result["contaminationDetected"] is False
    assert result["timingComparabilityValid"] is True


# Thresholds, driver failure, sampling, and receipt shape


def test_thresholds_may_only_be_tightened() -> None:
    # A higher free-VRAM floor is stricter, and a lower ceiling is stricter.
    gate.assert_thresholds_unmodified(
        gate.GateThresholds(
            min_free_vram_mib=15_000,
            foreign_compute_mib_baseline=64,
            max_post_stage_residual_mib=128,
        )
    )
    # Loosening the free-VRAM floor is what the issue explicitly forbids.
    looser = gate.GateThresholds(min_free_vram_mib=2_000)
    try:
        gate.assert_thresholds_unmodified(looser)
    except gate.GateError as exc:
        assert exc.category == "infrastructure_blocked_threshold_relaxation"
        assert exc.evidence["predeclared"] == gate.MIN_FREE_VRAM_MIB
    else:
        raise AssertionError("relaxing a predeclared threshold must be refused")


def test_relaxed_ceiling_is_also_refused() -> None:
    looser = gate.GateThresholds(max_post_stage_residual_mib=65_536)
    try:
        gate.assert_thresholds_unmodified(looser)
    except gate.GateError as exc:
        assert exc.evidence["threshold"] == "max_post_stage_residual_mib"
    else:
        raise AssertionError("loosening the residual ceiling must be refused")


def test_relaxed_foreign_baseline_blocks_a_dirty_gate() -> None:
    """Widening the foreign-process baseline must not let contamination pass."""
    dirty = gate.sample_gpu_state(
        make_smi_runner((9000, 200), [(GPU0_UUID, UNKNOWN_PID, "intruder", 4000)])
    )
    try:
        gate.evaluate_pre_run_gate(
            dirty,
            tensor_parallel=1,
            thresholds=gate.GateThresholds(foreign_compute_mib_baseline=999_999),
        )
    except gate.GateError as exc:
        assert exc.category == "infrastructure_blocked_threshold_relaxation"
    else:
        raise AssertionError("a widened baseline must be refused before evaluating")


def test_unavailable_driver_fails_closed() -> None:
    state = gate.sample_gpu_state(make_smi_runner((200, 200), gpu_rc=1))
    assert state["available"] is False
    result = gate.evaluate_pre_run_gate(state, tensor_parallel=1)
    assert result["allowed"] is False
    assert "nvidia_smi_unavailable_cannot_prove_clean_baseline" in result["blockingReasons"]


def test_partial_nvidia_smi_sample_does_not_crash_the_gate() -> None:
    state = gate.sample_gpu_state(make_smi_runner((None, 200)))
    result = gate.evaluate_pre_run_gate(state, tensor_parallel=1)
    gpu0 = next(row for row in result["perGpu"] if row["gpuIndex"] == 0)
    assert gpu0["freeMiB"] is None
    # An unreadable free-VRAM field is not proof of a clean device: fail closed.
    assert result["allowed"] is False
    assert "gpu0:free_vram_unknown_cannot_prove_clean_baseline" in result["blockingReasons"]


def test_compute_apps_query_failure_still_reports_gpus() -> None:
    state = gate.sample_gpu_state(make_smi_runner((200, 200), compute_rc=1))
    assert state["available"] is True
    assert len(state["gpus"]) == 2
    assert any(e["query"] == "compute-apps" for e in state["errors"])


def test_unattributed_compute_app_is_recorded_under_unknown_index() -> None:
    runner = make_smi_runner((200, 200), [("GPU-9999", 777, "ghost", 100)])
    state = gate.sample_gpu_state(runner)
    assert -1 in state["processesByGpu"]
    assert state["processesByGpu"][-1][0]["pid"] == 777


def test_gate_receipt_reuses_the_31_shape() -> None:
    state = clean_state()
    pre_run = gate.evaluate_pre_run_gate(state, tensor_parallel=2)
    receipt = gate.build_gate_receipt(
        run_identity={"runId": "gate-run", "candidateId": "cand"},
        tensor_parallel=2,
        pre_run=pre_run,
        state=state,
    )
    assert receipt["schemaVersion"] == gate.RECEIPT_SCHEMA_VERSION
    assert receipt["gpuCount"] == 2
    assert len(receipt["snapshots"]) == 1
    assert receipt["snapshots"][0]["stage"] == "before_measured_loop"
    # Per-GPU rows stay separate: two entries, no merged total.
    assert [g["gpuIndex"] for g in receipt["snapshots"][0]["gpus"]] == [0, 1]
    assert receipt["resourceGate"]["preRun"]["allowed"] is True
    json.dumps(receipt)


def test_required_gpu_indices_rejects_unsupported_tp() -> None:
    for bad in (0, 3, 8):
        try:
            gate.required_gpu_indices(bad)
        except ValueError:
            continue
        raise AssertionError(f"tensor_parallel {bad} must be rejected")


def test_required_gpu_indices_respects_visible_devices() -> None:
    assert gate.required_gpu_indices(2, cuda_visible_devices=[1, 0]) == [0, 1]
    assert gate.required_gpu_indices(1, cuda_visible_devices=[1, 0]) == [1]


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"Kaggle GPU resource gate tests passed ({len(tests)} cases).")


if __name__ == "__main__":
    main()
