#!/usr/bin/env python3
"""CPU-only tests for the Issue #54 bounded actual-binary Prism runtime probe.

Every case drives the real selector logic against fake executables and a stubbed
process runner. No Kaggle session, no GPU, no network, no source build.
"""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec and spec.loader, filename
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SEL = _load("pari_select_prism_runtime", "select-kaggle-prism-runtime.py")

CUDA_12_8 = "prism-llamacpp-b10735-cuda12.8-linux-x86_64"
CUDA_12_4 = "prism-llamacpp-b10735-cuda12.4-linux-x86_64"

T4_DEVICES = (
    "ggml_cuda_init: found 2 CUDA devices:\n"
    "  Device 0: NVIDIA Tesla T4, compute capability 7.5\n"
    "  Device 1: NVIDIA Tesla T4, compute capability 7.5\n"
)


def _fake_binary(
    directory: Path,
    name: str,
    *,
    version_out: str = "version: 4154 (prism)\n",
    version_rc: int = 0,
    devices_out: str = T4_DEVICES,
    devices_rc: int = 0,
    devices_timeout: float | None = None,
    sleep_seconds: float | None = None,
) -> Path:
    """Create an executable shell script standing in for llama-server."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    body = ["#!/bin/sh"]
    if sleep_seconds is not None:
        body.append(f"sleep {sleep_seconds}")
    body.append('case "$1" in')
    body.append(f"  --version) cat <<'EOF'\n{version_out}EOF\n\nexit {version_rc} ;;")
    if devices_timeout is not None:
        body.append(f"  --list-devices) sleep {devices_timeout} ;;")
    else:
        body.append(
            f"  --list-devices) cat <<'EOF'\n{devices_out}EOF\n\nexit {devices_rc} ;;"
        )
    body.append("  *) exit 0 ;;")
    body.append("esac")
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _receipt(runtime_dir: Path, artifact_id: str, executable: Path) -> Path:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    receipt = runtime_dir / f"{artifact_id}.receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "artifact": {"id": artifact_id, "kind": "tarball"},
                "runtimeExecutable": str(executable),
                "sourceCompilationAllowed": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return receipt


def _run_selector(runtime_dir: Path, output: Path) -> int:
    """Drive the real main() in probe-only mode over pre-seeded receipts."""
    argv = sys.argv
    sys.argv = [
        "select-kaggle-prism-runtime.py",
        "--runtime-dir",
        str(runtime_dir),
        "--output",
        str(output),
        "--probe-only",
    ]
    try:
        try:
            SEL.main()
            return 0
        except SystemExit as exc:
            return int(exc.code or 0)
    finally:
        sys.argv = argv


def _driver_stub(monkey_value: list[str] | None = None) -> None:
    """Pin nvidia-smi evidence so tests never depend on a real driver."""
    SEL._collect_nvidia_smi = lambda: monkey_value or [
        {"command": ["nvidia-smi"], "returnCode": 0, "output": "Tesla T4, 550.54.15, 7.5"}
    ]


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_compatible_128_selected_and_124_not_executed() -> None:
    """Issue #54 case 1: 12.8 passes; the 12.4 binary must never run."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_128 = _fake_binary(root / "b128", "llama-server")
        bin_124 = _fake_binary(root / "b124", "llama-server")
        runtime = root / "rt"
        _receipt(runtime, CUDA_12_8, bin_128)
        _receipt(runtime, CUDA_12_4, bin_124)
        # Make the 12.4 binary explode loudly if it is ever executed.
        bin_124.write_text("#!/bin/sh\necho 'SHOULD NOT RUN' >&2\nexit 99\n")
        bin_124.chmod(0o755)
        _driver_stub()
        output = root / "sel.json"
        assert _run_selector(runtime, output) == 0
        report = json.loads(output.read_text())
        assert report["selectedArtifactId"] == CUDA_12_8
        assert report["status"] == "selected_prebuilt"
        assert len(report["attempts"]) == 1, "ladder must stop at the first compatible binary"
        assert "SHOULD NOT RUN" not in json.dumps(report)


def test_missing_shared_library_falls_back_to_124() -> None:
    """Issue #54 case 2: present but unloadable 12.8 -> select 12.4."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bad = root / "b128"
        bad.mkdir(parents=True)
        bin_128 = _fake_binary(bad, "llama-server")
        bin_128.write_text(
            "#!/bin/sh\n"
            "echo 'llama-server: error while loading shared libraries: "
            "libcuda.so.1: cannot open shared object file: No such file or directory' >&2\n"
            "exit 127\n"
        )
        bin_128.chmod(0o755)
        bin_124 = _fake_binary(root / "b124", "llama-server")
        runtime = root / "rt"
        _receipt(runtime, CUDA_12_8, bin_128)
        _receipt(runtime, CUDA_12_4, bin_124)
        _driver_stub()
        output = root / "sel.json"
        assert _run_selector(runtime, output) == 0
        report = json.loads(output.read_text())
        assert report["selectedArtifactId"] == CUDA_12_4
        assert len(report["attempts"]) == 2
        first = report["attempts"][0]["compatibilityProbe"]
        assert first["compatible"] is False
        assert first["failureCategory"] == "native_library_or_abi_failure", first
        assert "libcuda.so.1" in first["version"]["output"]
        # both attempts preserved
        assert report["attempts"][1]["artifactId"] == CUDA_12_4


def test_no_cuda_device_falls_back_to_124() -> None:
    """Issue #54 case 3: 12.8 runs but --list-devices sees no CUDA."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_128 = _fake_binary(
            root / "b128",
            "llama-server",
            devices_out="no CUDA devices found\nggml_backend_cpu: using CPU backend\n",
        )
        bin_124 = _fake_binary(root / "b124", "llama-server")
        runtime = root / "rt"
        _receipt(runtime, CUDA_12_8, bin_128)
        _receipt(runtime, CUDA_12_4, bin_124)
        _driver_stub()
        output = root / "sel.json"
        assert _run_selector(runtime, output) == 0
        report = json.loads(output.read_text())
        assert report["selectedArtifactId"] == CUDA_12_4
        first = report["attempts"][0]["compatibilityProbe"]
        assert first["failureCategory"] == "silent_cpu_fallback_detected", first


def test_hanging_binary_times_out_then_falls_back() -> None:
    """Issue #54 case 4: 12.8 hangs on --version; it is killed and reaped."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        saved = (SEL.VERSION_TIMEOUT_S, SEL.DEVICES_TIMEOUT_S)
        SEL.VERSION_TIMEOUT_S, SEL.DEVICES_TIMEOUT_S = 1, 1
        try:
            bin_128 = _fake_binary(root / "b128", "llama-server", sleep_seconds=30)
            bin_124 = _fake_binary(root / "b124", "llama-server")
            runtime = root / "rt"
            _receipt(runtime, CUDA_12_8, bin_128)
            _receipt(runtime, CUDA_12_4, bin_124)
            _driver_stub()
            output = root / "sel.json"
            assert _run_selector(runtime, output) == 0
            report = json.loads(output.read_text())
            assert report["selectedArtifactId"] == CUDA_12_4
            first = report["attempts"][0]["compatibilityProbe"]
            assert first["failureCategory"] == "runtime_binary_timeout", first
            assert first["version"]["timedOut"] is True
        finally:
            SEL.VERSION_TIMEOUT_S, SEL.DEVICES_TIMEOUT_S = saved


def test_both_fail_yields_runtime_unqualified_with_both_reports() -> None:
    """Issue #54 case 5: neither passes -> runtime_unqualified, both preserved."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        broken = root / "broken"
        broken.mkdir(parents=True)
        for name in ("llama-server-a", "llama-server-b"):
            p = broken / name
            p.write_text("#!/bin/sh\necho 'GLIBC_2.38 not found' >&2\nexit 127\n")
            p.chmod(0o755)
        runtime = root / "rt"
        _receipt(runtime, CUDA_12_8, broken / "llama-server-a")
        _receipt(runtime, CUDA_12_4, broken / "llama-server-b")
        _driver_stub()
        output = root / "sel.json"
        rc = _run_selector(runtime, output)
        assert rc == 2, rc
        report = json.loads(output.read_text())
        assert report["status"] == "runtime_unqualified"
        assert report["selectedArtifactId"] is None
        assert len(report["attempts"]) == 2
        assert len(report["failureCategories"]) == 2
        for entry in report["failureCategories"]:
            assert entry["failureCategory"] == "native_library_or_abi_failure"
            assert entry["executableSha256"]


def test_failed_artifact_never_leaves_stale_selected_id() -> None:
    """Issue #54 case 6: a previous selectedArtifactId cannot survive a failure."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        broken = root / "broken"
        broken.mkdir(parents=True)
        for name in ("a", "b"):
            p = broken / name
            p.write_text("#!/bin/sh\nexit 127\n")
            p.chmod(0o755)
        runtime = root / "rt"
        _receipt(runtime, CUDA_12_8, broken / "a")
        _receipt(runtime, CUDA_12_4, broken / "b")
        output = root / "sel.json"
        # Seed a stale report that claims an artifact was selected.
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"selectedArtifactId": CUDA_12_8, "status": "selected_prebuilt"}))
        _driver_stub()
        rc = _run_selector(runtime, output)
        assert rc == 2
        report = json.loads(output.read_text())
        assert report["selectedArtifactId"] is None
        assert "selectedExecutable" not in report


def test_source_build_text_is_rejected() -> None:
    """Issue #54 case 7: a binary that prints build output is not compatible."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_128 = _fake_binary(
            root / "b128",
            "llama-server",
            version_out="Building wheel for x\nnvcc fatal\n",
        )
        runtime = root / "rt"
        _receipt(runtime, CUDA_12_8, bin_128)
        _driver_stub()
        probe = SEL.probe_binary(bin_128)
        assert probe["compatible"] is False
        assert probe["failureCategory"] == "source_build_attempt_forbidden"
        assert "nvcc" in probe["sourceBuildMarkers"]


def test_cpu_only_execution_cannot_qualify_cuda_runtime() -> None:
    """Issue #54 case 8: a clean CPU-only run is not a CUDA-compatible runtime."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_128 = _fake_binary(
            root / "b128",
            "llama-server",
            devices_out="ggml_backend_cpu: using CPU backend\ngpu layers: 0\n",
        )
        runtime = root / "rt"
        _receipt(runtime, CUDA_12_8, bin_128)
        _driver_stub()
        probe = SEL.probe_binary(bin_128)
        assert probe["compatible"] is False
        assert probe["failureCategory"] == "silent_cpu_fallback_detected"
        assert SEL.probe_is_runtime_binary_incompatibility(probe)


def test_selection_report_is_written_atomically() -> None:
    """Issue #54 case 9: the report is renamed into place, never truncated."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / "sel.json"
        payload = {"selectedArtifactId": CUDA_12_8, "status": "selected_prebuilt"}
        SEL.atomic_write_json(target, payload)
        assert json.loads(target.read_text()) == payload
        # No temp files may be left behind.
        leftovers = [p for p in root.iterdir() if p.name != "sel.json"]
        assert leftovers == [], leftovers
        # An interrupted write must not clobber a good prior report.
        good = {"selectedArtifactId": None, "status": "runtime_unqualified"}
        SEL.atomic_write_json(target, good)
        try:
            SEL.atomic_write_json(target, {"bad": {1, 2}})  # sets are not JSON
        except TypeError:
            pass
        assert json.loads(target.read_text()) == good, "prior good report must survive"
        assert [p for p in root.iterdir() if p.name != "sel.json"] == []


def test_fallback_is_limited_to_runtime_binary_incompatibility() -> None:
    """Issue #54: model-load capacity failures must not bounce runtimes."""
    for category in (
        "native_library_or_abi_failure",
        "cuda_driver_runtime_mismatch",
        "silent_cpu_fallback_detected",
        "runtime_binary_timeout",
        "runtime_binary_not_executable",
        "runtime_receipt_unusable",
        "python_abi_mismatch",
        "illegal_instruction",
    ):
        assert SEL.probe_is_runtime_binary_incompatibility({"failureCategory": category}), category
    for category in (
        "model_load_failure",
        "cuda_oom_load",
        "context_length_config_failure",
        "unsupported_compute_capability",
        None,
    ):
        assert not SEL.probe_is_runtime_binary_incompatibility({"failureCategory": category}), category


def test_non_t4_compute_capability_is_not_compatible() -> None:
    """A different GPU must not pass as a T4, and must not bounce the ladder.

    Issue #54: an A100/P100 is not a runtime-binary incompatibility. Stepping
    from the 12.8 build to the 12.4 build runs the same probe against the same
    GPU and the same driver, so the walk halts instead of recording a second
    identical rejection.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_128 = _fake_binary(
            root / "b128",
            "llama-server",
            devices_out="Device 0: NVIDIA A100, compute capability 8.0\n",
        )
        _driver_stub()
        probe = SEL.probe_binary(bin_128)
        assert probe["compatible"] is False
        # Reuse #53's own category rather than the selector's local label:
        # "unsupported_kernel" in that taxonomy means a real kernel-level fault.
        assert probe["failureCategory"] == "unsupported_compute_capability"
        assert not SEL.probe_is_runtime_binary_incompatibility(probe)
        assert SEL.probe_halts_ladder(probe)


def test_compatible_probe_records_full_evidence() -> None:
    """Every success must carry the evidence #54 asks to preserve."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_128 = _fake_binary(root / "b128", "llama-server")
        _driver_stub()
        probe = SEL.probe_binary(bin_128)
        assert probe["compatible"] is True
        assert probe["version"]["returnCode"] == 0
        assert "prism" in probe["version"]["output"]
        assert probe["cudaEvidence"]["computeCapabilities"] == ["7.5"]
        assert probe["cudaEvidence"]["deviceNames"] == ["NVIDIA Tesla T4"]
        assert probe["executableSha256"]
        assert probe["driver"]


def test_hanging_probe_leaves_no_orphan_process() -> None:
    """Issue #54: a timed-out probe must not leave a grandchild running.

    `subprocess.run(..., timeout=)` only kills the direct child; a wrapper that
    has spawned helpers leaves them alive, reparented to init. On Kaggle such an
    orphan can keep holding GPU memory after the ladder has moved on, so the
    selector starts each probe in its own session and SIGKILLs the group.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        marker = root / "grandchild.pid"
        wrapper = root / "wrapper.sh"
        wrapper.write_text(
            "#!/bin/sh\n"
            "/bin/sleep 120 &\n"
            f'echo "$!" > {marker}\n'
            "wait\n"
        )
        wrapper.chmod(0o755)
        saved = SEL.VERSION_TIMEOUT_S
        SEL.VERSION_TIMEOUT_S = 1
        try:
            result = SEL._run_bounded([str(wrapper)], timeout=2)
        finally:
            SEL.VERSION_TIMEOUT_S = saved
        assert result["timedOut"] is True
        assert "killed process group" in result.get("timeoutKill", "")
        # The orphan must be gone. Wait briefly for the kernel to reap it.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if not marker.exists() or not _pid_alive(int(marker.read_text().strip())):
                break
            time.sleep(0.1)
        assert marker.exists(), "wrapper never recorded its child pid"
        assert not _pid_alive(int(marker.read_text().strip())), (
            "the probe's grandchild survived the timeout; the ladder would move on "
            "with an orphaned process still holding accelerator resources"
        )


def test_probe_output_is_bounded_and_flagged_when_truncated() -> None:
    """Issue #54: a runaway binary cannot balloon the report or memory."""
    saved = SEL.PROBE_OUTPUT_LIMIT_BYTES
    SEL.PROBE_OUTPUT_LIMIT_BYTES = 4096
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            noisy = root / "noisy.sh"
            noisy.write_text(
                "#!/bin/sh\n"
                # 200 lines x 100 chars comfortably exceeds a 4 KiB cap.
                "i=0\n"
                "while [ $i -lt 200 ]; do\n"
                "  printf '%0100d\\n' $i\n"
                "  i=$((i+1))\n"
                "done\n"
                "exit 0\n"
            )
            noisy.chmod(0o755)
            result = SEL._run_bounded([str(noisy)], timeout=30)
    finally:
        SEL.PROBE_OUTPUT_LIMIT_BYTES = saved
    assert result["timedOut"] is False
    assert result["returnCode"] == 0
    assert result["outputTruncated"] is True
    assert len(result["output"].encode("utf-8")) <= SEL.PROBE_OUTPUT_LIMIT_BYTES


def test_missing_executable_is_recorded_not_raised() -> None:
    """A receipt pointing at a vanished binary yields evidence, not a traceback."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        probe = SEL.probe_binary(root / "does-not-exist")
        assert probe["compatible"] is False
        assert probe["executableExists"] is False
        assert probe["failureCategory"] == "runtime_binary_missing"
        assert SEL.probe_is_runtime_binary_incompatibility(probe)


def test_non_executable_binary_is_recorded_not_raised() -> None:
    """A receipt pointing at a non-executable file must not crash the ladder."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        blob = root / "llama-server"
        blob.write_text("#!/bin/sh\nexit 0\n")
        blob.chmod(0o644)
        probe = SEL.probe_binary(blob)
        assert probe["compatible"] is False
        assert probe["failureCategory"] == "runtime_binary_not_executable"
        assert SEL.probe_is_runtime_binary_incompatibility(probe)


def test_list_devices_nonzero_exit_falls_back_to_124() -> None:
    """Issue #54: incompatibility can surface only at device enumeration."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_128 = _fake_binary(
            root / "b128",
            "llama-server",
            devices_out=(
                "ggml_cuda_init: CUDA driver version is insufficient for CUDA runtime version\n"
            ),
            devices_rc=1,
        )
        bin_124 = _fake_binary(root / "b124", "llama-server")
        runtime = root / "rt"
        _receipt(runtime, CUDA_12_8, bin_128)
        _receipt(runtime, CUDA_12_4, bin_124)
        _driver_stub()
        output = root / "sel.json"
        assert _run_selector(runtime, output) == 0
        report = json.loads(output.read_text())
        assert report["selectedArtifactId"] == CUDA_12_4
        first = report["attempts"][0]["compatibilityProbe"]
        assert first["failureCategory"] == "cuda_driver_runtime_mismatch", first
        # --version succeeded, so the report must retain that it got that far.
        assert first["version"]["returnCode"] == 0
        assert first["devices"]["returnCode"] == 1


def test_list_devices_hang_falls_back_to_124() -> None:
    """Issue #54: a binary that starts then hangs on enumeration is bounded too."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        saved = SEL.VERSION_TIMEOUT_S, SEL.DEVICES_TIMEOUT_S
        SEL.VERSION_TIMEOUT_S, SEL.DEVICES_TIMEOUT_S = 5, 1
        try:
            bin_128 = _fake_binary(root / "b128", "llama-server", devices_timeout=30)
            bin_124 = _fake_binary(root / "b124", "llama-server")
            runtime = root / "rt"
            _receipt(runtime, CUDA_12_8, bin_128)
            _receipt(runtime, CUDA_12_4, bin_124)
            _driver_stub()
            output = root / "sel.json"
            assert _run_selector(runtime, output) == 0
            report = json.loads(output.read_text())
            assert report["selectedArtifactId"] == CUDA_12_4
            first = report["attempts"][0]["compatibilityProbe"]
            assert first["failureCategory"] == "runtime_binary_timeout", first
            assert first["version"]["returnCode"] == 0
            assert first["devices"]["timedOut"] is True
        finally:
            SEL.VERSION_TIMEOUT_S, SEL.DEVICES_TIMEOUT_S = saved


def test_source_build_marker_in_list_devices_is_rejected() -> None:
    """A build attempt hidden in the device probe must still be caught."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_128 = _fake_binary(
            root / "b128",
            "llama-server",
            devices_out="running cmake --build .\nnvcc fatal: unsupported\n",
        )
        _driver_stub()
        probe = SEL.probe_binary(bin_128)
        assert probe["compatible"] is False
        assert probe["failureCategory"] == "source_build_attempt_forbidden"
        assert "nvcc" in probe["sourceBuildMarkers"]


def test_corrupt_receipt_is_preserved_and_ladder_continues() -> None:
    """Issue #54: a truncated receipt must not lose the attempt's evidence."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runtime = root / "rt"
        runtime.mkdir(parents=True)
        (runtime / f"{CUDA_12_8}.receipt.json").write_text('{"runtimeExecutable": "/trunc')
        bin_124 = _fake_binary(root / "b124", "llama-server")
        _receipt(runtime, CUDA_12_4, bin_124)
        _driver_stub()
        output = root / "sel.json"
        assert _run_selector(runtime, output) == 0
        report = json.loads(output.read_text())
        assert report["selectedArtifactId"] == CUDA_12_4
        assert len(report["attempts"]) == 2, "the corrupt-receipt attempt must be recorded"
        first = report["attempts"][0]
        assert first["attemptErrors"], first
        probe = first["compatibilityProbe"]
        assert probe["failureCategory"] == "runtime_receipt_unusable"
        assert "not valid JSON" in probe["failureDetail"]
        # It is still an honest per-artifact defect, so 12.4 is worth trying.
        assert probe["fallbackEligible"] is True


def test_receipt_without_executable_path_is_preserved() -> None:
    """A receipt missing runtimeExecutable is evidence, not a crash."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runtime = root / "rt"
        runtime.mkdir(parents=True)
        (runtime / f"{CUDA_12_8}.receipt.json").write_text(
            json.dumps({"artifact": {"id": CUDA_12_8}, "sourceCompilationAllowed": False})
        )
        bin_124 = _fake_binary(root / "b124", "llama-server")
        _receipt(runtime, CUDA_12_4, bin_124)
        _driver_stub()
        output = root / "sel.json"
        assert _run_selector(runtime, output) == 0
        report = json.loads(output.read_text())
        assert report["selectedArtifactId"] == CUDA_12_4
        probe = report["attempts"][0]["compatibilityProbe"]
        assert probe["failureCategory"] == "runtime_receipt_unusable"
        assert "runtimeExecutable" in probe["failureDetail"]


def test_report_is_on_disk_and_parseable_after_every_attempt() -> None:
    """Issue #54: evidence is durable per attempt, not only at the end."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_128 = _fake_binary(
            root / "b128", "llama-server", version_out="GLIBC_2.38 not found\n", version_rc=127
        )
        bin_124 = _fake_binary(root / "b124", "llama-server")
        runtime = root / "rt"
        _receipt(runtime, CUDA_12_8, bin_128)
        _receipt(runtime, CUDA_12_4, bin_124)
        _driver_stub()
        output = root / "sel.json"

        snapshots: list[dict] = []
        original = SEL.probe_binary

        def _spy(executable, **kwargs):
            # Before the *second* probe runs, the first attempt must already be
            # durably on disk and parseable.
            if snapshots or output.exists():
                snapshots.append(json.loads(output.read_text()))
            return original(executable, **kwargs)

        SEL.probe_binary = _spy
        try:
            assert _run_selector(runtime, output) == 0
        finally:
            SEL.probe_binary = original

        assert snapshots, "probe_binary was never called"
        first_snapshot = snapshots[-1]
        assert first_snapshot["status"] == "in_progress"
        assert first_snapshot["selectedArtifactId"] is None
        assert [a["artifactId"] for a in first_snapshot["attempts"]] == [CUDA_12_8]
        assert first_snapshot["attempts"][0]["compatibilityProbe"]["failureCategory"]
        final = json.loads(output.read_text())
        assert final["selectedArtifactId"] == CUDA_12_4


def test_non_t4_hardware_halts_the_ladder_without_trying_124() -> None:
    """Issue #54: an untried binary must never be reported as rejected."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_128 = _fake_binary(
            root / "b128",
            "llama-server",
            devices_out="Device 0: NVIDIA Tesla P100, compute capability 6.0\n",
        )
        bin_124 = _fake_binary(root / "b124", "llama-server")
        # Trip-wire: the 12.4 binary must never be executed.
        bin_124.write_text("#!/bin/sh\necho 'SHOULD NOT RUN' >&2\nexit 99\n")
        bin_124.chmod(0o755)
        runtime = root / "rt"
        _receipt(runtime, CUDA_12_8, bin_128)
        _receipt(runtime, CUDA_12_4, bin_124)
        _driver_stub()
        output = root / "sel.json"
        rc = _run_selector(runtime, output)
        assert rc == 2, rc
        report = json.loads(output.read_text())
        assert report["status"] == "runtime_unqualified"
        assert report["ladderHaltedAt"] == CUDA_12_8
        assert "unsupported_compute_capability" in report["ladderHaltReason"]
        assert len(report["attempts"]) == 1
        assert report["unattemptedArtifacts"] == [CUDA_12_4]
        assert "SHOULD NOT RUN" not in json.dumps(report)


def test_receipt_existence_is_recorded_before_install() -> None:
    """Issue #54: the report must not blame the operator for an install receipt."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        bin_128 = _fake_binary(root / "b128", "llama-server")
        runtime = root / "rt"
        _receipt(runtime, CUDA_12_8, bin_128)
        _driver_stub()
        output = root / "sel.json"
        assert _run_selector(runtime, output) == 0
        report = json.loads(output.read_text())
        assert report["attempts"][0]["receiptExistedBeforeAttempt"] is True


def test_failed_run_lists_untried_artifacts() -> None:
    """The report must distinguish "rejected" from "never attempted"."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        runtime = root / "rt"
        runtime.mkdir(parents=True)
        bin_128 = _fake_binary(
            root / "b128", "llama-server", version_out="GLIBC_2.38 not found\n", version_rc=127
        )
        _receipt(runtime, CUDA_12_8, bin_128)
        # No 12.4 receipt at all: the probe-only walk finds nothing to probe.
        _driver_stub()
        output = root / "sel.json"
        rc = _run_selector(runtime, output)
        assert rc == 2, rc
        report = json.loads(output.read_text())
        assert report["selectedArtifactId"] is None
        assert report["attempts"][1]["compatibilityProbe"] is None
        assert report["attempts"][1]["receiptExistedBeforeAttempt"] is False
        assert report["unattemptedArtifacts"] == []
        assert report["failureCategories"][0]["fallbackEligible"] is True


def main() -> None:
    tests = [v for name, v in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"Prism runtime selection probe tests passed ({len(tests)} cases).")


if __name__ == "__main__":
    main()
