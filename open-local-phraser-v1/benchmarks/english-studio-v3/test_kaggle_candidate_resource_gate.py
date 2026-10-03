#!/usr/bin/env python3
"""CPU-only checks that the #57 gate is wired into candidate wrappers and roster."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def _install_offline_stubs() -> None:
    """Keep this file runnable on a bare interpreter with no ML/HTTP deps.

    The Prism wrapper imports `requests` at module load. These checks never make
    a network call, so a stub that raises on any use is strictly safer than a
    real client: it cannot turn a CPU-only assertion into live traffic.
    """
    try:
        import requests  # noqa: F401
    except ImportError:  # pragma: no cover - depends on host site-packages
        import types

        stub = types.ModuleType("requests")

        def _blocked(*_args, **_kwargs):
            raise AssertionError("network access is not allowed in CPU-only tests")

        stub.get = _blocked
        stub.post = _blocked
        stub.Session = object
        sys.modules["requests"] = stub


_install_offline_stubs()


def load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {filename}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_roster() -> object:
    """Load the roster supervisor, stubbing only the optional HTTP dependency.

    The roster is CPU-testable because every `nvidia-smi` call is injected by
    the shared gate module; the stub below only keeps an unrelated optional
    import from aborting module load on a bare interpreter.
    """
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    return load_script("pari_resource_gate_roster", "run-kaggle-roster.py")


def check_vllm_calls_resource_gate() -> None:
    module = load_script("pari_resource_gate_vllm", "run-kaggle-vllm-candidate.py")
    state = {"available": True, "gpus": []}
    pre = {"allowed": True, "perGpu": [{"gpuIndex": 0, "usedMiB": 100}]}
    with patch.object(module.gpu_resource_gate, "sample_gpu_state", return_value=state), patch.object(
        module.gpu_resource_gate, "require_clean_pre_run", return_value=pre
    ) as require_gate, patch.object(
        module.gpu_resource_gate, "quarantine_after_stage", return_value={"clean": True}
    ) as quarantine:
        got_state, got_pre = module.pre_run_resource_gate(
            tensor_parallel=2, run_identity={"candidateId": "fixture"}
        )
        post = module.post_stage_resource_gate(
            tensor_parallel=2, baseline={"perGpu": pre["perGpu"]}, owned_pids=[4242, 4243]
        )
    assert got_state is state and got_pre is pre and post["clean"]
    assert require_gate.call_args.kwargs["tensor_parallel"] == 2
    assert quarantine.call_args.kwargs["owned_pids"] == [4242, 4243]


def check_prism_calls_resource_gate() -> None:
    module = load_script("pari_resource_gate_prism", "run-kaggle-prism-candidate.py")
    state = {"available": True, "gpus": []}
    pre = {"allowed": True, "perGpu": [{"gpuIndex": 0, "usedMiB": 100}]}
    with patch.object(module.gpu_resource_gate, "sample_gpu_state", return_value=state), patch.object(
        module.gpu_resource_gate, "require_clean_pre_run", return_value=pre
    ) as require_gate, patch.object(
        module.gpu_resource_gate, "quarantine_after_stage", return_value={"clean": True}
    ) as quarantine:
        got_state, got_pre = module.pre_run_resource_gate(
            tensor_parallel=1, run_identity={"candidateId": "fixture"}
        )
        post = module.post_stage_resource_gate(
            tensor_parallel=1, baseline={"perGpu": pre["perGpu"]}, owned_pids=[5150]
        )
    assert got_state is state and got_pre is pre and post["clean"]
    assert require_gate.call_args.kwargs["tensor_parallel"] == 1
    assert require_gate.call_args.kwargs["cuda_visible_devices"] == [0]
    assert quarantine.call_args.kwargs["owned_pids"] == [5150]


def check_roster_blocks_contaminated_candidate_not_oom() -> None:
    """A contaminated required GPU blocks the candidate as infrastructure.

    Issue #57's whole point is that contamination must never resurface as the
    next candidate's `cuda_oom_*`. This pins the roster's pre-candidate gate to
    the contamination category and proves no OOM category is produced.
    """
    roster = load_roster()
    candidate = {"id": "cand-contaminated", "tensorParallelSize": 1}
    state = {
        "available": True,
        "gpus": [{"gpuIndex": 0, "usedMiB": 9000, "freeMiB": 7000, "totalMiB": 16384}],
        "processesByGpu": {0: [{"pid": 4242, "processName": "python", "usedMiB": 9000}]},
    }
    with patch.object(roster.GATE, "sample_gpu_state", return_value=state), patch.object(
        roster.GATE, "default_smi_runner", return_value=(0, "", "")
    ):
        record = roster.pre_candidate_resource_gate(candidate=candidate)
    assert record["allowed"] is False, record
    assert record["category"] == roster.GATE.BLOCKED_CATEGORY, record
    assert record["candidateEvidenceEligible"] is False, record
    serialized = json.dumps(record)
    assert "cuda_oom" not in serialized, serialized
    assert "known_residue" not in serialized or "blocked" in serialized


def check_roster_allows_clean_candidate_and_records_baseline() -> None:
    """A clean baseline is allowed and is kept for the post-candidate compare."""
    roster = load_roster()
    candidate = {"id": "cand-clean", "tensorParallelSize": 2}
    state = {
        "available": True,
        "gpus": [
            {"gpuIndex": 0, "usedMiB": 100, "freeMiB": 16000, "totalMiB": 16384},
            {"gpuIndex": 1, "usedMiB": 120, "freeMiB": 15900, "totalMiB": 16384},
        ],
        "processesByGpu": {},
    }
    with patch.object(roster.GATE, "sample_gpu_state", return_value=state), patch.object(
        roster.GATE, "default_smi_runner", return_value=(0, "", "")
    ):
        record = roster.pre_candidate_resource_gate(candidate=candidate)
    assert record["allowed"] is True, record
    assert record["category"] is None, record
    # TP2 requires both GPUs, so the baseline must carry both per-GPU rows.
    assert [row["gpuIndex"] for row in record["baseline"]["perGpu"]] == [0, 1], record


def check_tp1_records_but_does_not_block_on_unused_gpu() -> None:
    """TP1 needs only GPU0, so GPU1 contamination is recorded, not blocking.

    Issue #57 is explicit that a TP1 candidate must not be blocked by the unused
    second GPU, while the contamination still has to reach the receipt.
    """
    roster = load_roster()
    candidate = {"id": "cand-tp1", "tensorParallelSize": 1}
    state = {
        "available": True,
        "gpus": [
            {"gpuIndex": 0, "usedMiB": 100, "freeMiB": 16000, "totalMiB": 16384},
            {"gpuIndex": 1, "usedMiB": 9000, "freeMiB": 7000, "totalMiB": 16384},
        ],
        "processesByGpu": {1: [{"pid": 9999, "processName": "python", "usedMiB": 9000}]},
    }
    with patch.object(roster.GATE, "sample_gpu_state", return_value=state), patch.object(
        roster.GATE, "default_smi_runner", return_value=(0, "", "")
    ):
        record = roster.pre_candidate_resource_gate(candidate=candidate)
    assert record["allowed"] is True, record
    assert record["cudaVisibleDevices"] == [0], record
    warnings = record["preRun"].get("warnings") or []
    assert any("unused_gpu" in warning for warning in warnings), warnings


def check_tp2_blocks_on_either_gpu() -> None:
    """TP2 needs both GPUs, so contamination on either one blocks the stage."""
    roster = load_roster()
    candidate = {"id": "cand-tp2", "tensorParallelSize": 2}
    state = {
        "available": True,
        "gpus": [
            {"gpuIndex": 0, "usedMiB": 100, "freeMiB": 16000, "totalMiB": 16384},
            {"gpuIndex": 1, "usedMiB": 9000, "freeMiB": 7000, "totalMiB": 16384},
        ],
        "processesByGpu": {1: [{"pid": 9999, "processName": "python", "usedMiB": 9000}]},
    }
    with patch.object(roster.GATE, "sample_gpu_state", return_value=state), patch.object(
        roster.GATE, "default_smi_runner", return_value=(0, "", "")
    ):
        record = roster.pre_candidate_resource_gate(candidate=candidate)
    assert record["allowed"] is False, record
    assert record["cudaVisibleDevices"] == [0, 1], record
    assert record["category"] == roster.GATE.BLOCKED_CATEGORY, record


def check_roster_quarantine_never_signals_foreign_pids() -> None:
    """A dirty handoff blocks the next candidate without killing anything.

    The roster forwards only PIDs it launched. Anything else is observed as
    foreign/unknown by the gate, which records and blocks it; the roster itself
    never sends a signal.
    """
    roster = load_roster()
    candidate = {"id": "cand-after", "tensorParallelSize": 1}
    baseline = {"perGpu": [{"gpuIndex": 0, "usedMiB": 100}]}
    dirty = {
        "clean": False,
        "verdict": roster.GATE.BLOCKED_CATEGORY,
        "blockingReasons": ["gpu0:residual_vram_mib_9000_above_512"],
    }
    with patch.object(roster.GATE, "quarantine_after_stage", return_value=dirty) as quarantine:
        record = roster.quarantine_candidate_handoff(
            candidate=candidate,
            baseline=baseline,
            owned_pids=[7000],
            residue_pids=[],
        )
    assert quarantine.call_args.kwargs["owned_pids"] == [7000]
    assert quarantine.call_args.kwargs["residue_pids"] == []
    assert record["clean"] is False
    assert record["category"] == roster.GATE.BLOCKED_CATEGORY
    assert record["candidateEvidenceEligible"] is False
    assert "never killed" in record["cleanupPolicy"]


def check_roster_owned_pids_come_only_from_q1_receipt() -> None:
    """Only the Q1 probe's server-identity tree is accepted as owned evidence."""
    roster = load_roster()
    assert roster.q1_owned_pids({"resourceGateOwnedPids": [12, 11, 12]}) == [11, 12]
    # A receipt with no ownership evidence yields nothing rather than guessing.
    assert roster.q1_owned_pids({"status": "completed"}) == []
    # Non-integer and boolean values are rejected: a bool is not a PID.
    assert roster.q1_owned_pids({"resourceGateOwnedPids": [13, True, "14", None]}) == [13]


def main() -> None:
    check_vllm_calls_resource_gate()
    check_prism_calls_resource_gate()
    check_roster_blocks_contaminated_candidate_not_oom()
    check_roster_allows_clean_candidate_and_records_baseline()
    check_tp1_records_but_does_not_block_on_unused_gpu()
    check_tp2_blocks_on_either_gpu()
    check_roster_quarantine_never_signals_foreign_pids()
    check_roster_owned_pids_come_only_from_q1_receipt()
    print("Kaggle candidate resource-gate integration tests passed (CPU mocks only).")


if __name__ == "__main__":
    main()
