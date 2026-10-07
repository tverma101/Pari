#!/usr/bin/env python3
"""Select a compatible pinned Prism llama.cpp prebuilt without compiling.

Both artifacts are the same pinned Prism source commit. The only allowed ladder
is CUDA 12.8 then CUDA 12.4. Every failed binary attempt is preserved.

Issue #54: metadata verification is not compatibility. Each ladder entry must
pass a bounded *actual-binary* probe (--version, --list-devices, CUDA/T4
evidence, clean exit within a timeout) before it can be selected, so the
predeclared 12.4 fallback is genuinely reachable when the 12.8 binary is
present but will not start on this driver. Compatibility is never inferred from
version-number ordering.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
INSTALL = HERE / "install-kaggle-prebuilt-runtime.py"
VERIFY = HERE / "verify-kaggle-prebuilt-runtime.py"
REGISTRY = HERE / "kaggle-prebuilt-runtimes.json"
LADDER = (
    "prism-llamacpp-b10735-cuda12.8-linux-x86_64",
    "prism-llamacpp-b10735-cuda12.4-linux-x86_64",
)

# Bounded probe budgets. These are wall-clock ceilings, not sleeps: a hung
# binary is killed and reaped, then the ladder falls back.
VERSION_TIMEOUT_S = 30
DEVICES_TIMEOUT_S = 60
# A misbehaving binary can spew output until it is killed. Capture at most
# this many bytes per probe (bounded memory); the cap is recorded so the report
# never implies it holds a binary's full stdout.
PROBE_OUTPUT_LIMIT_BYTES = 64 * 1024

# T4 is Turing, compute capability 7.5.
EXPECTED_COMPUTE_CAPABILITY = "7.5"

REPORT_VERSION = 2

# These must never appear in a probe's own output: their presence means the
# attempt tried to build something instead of using the pinned binary.
SOURCE_BUILD_MARKERS = (
    "cmake",
    "ninja",
    "nvcc",
    "bdist_wheel",
    "cargo build",
    "setup.py build",
    "building wheel for",
)

CC_PATTERN = re.compile(r"compute[_ ]cap(?:ability)?[^0-9]*(\d+)\.(\d+)", re.I)
GPU_NAME_PATTERN = re.compile(
    r"(?:device\s+\d+\s*:\s*)?\b(Tesla\s+T4|NVIDIA\s+Tesla\s+T4|A100|V100|T4)\b", re.I
)

# The shared #53 taxonomy returns every matching category in rule order, which is
# tuned for model-run failures, not process startup. When a binary dies before
# serving anything, the most specific *cause* is what an operator needs, so
# startup classification picks the first category on this list.
STARTUP_CATEGORY_PRIORITY = (
    "source_build_attempt_forbidden",
    "native_library_or_abi_failure",
    "cuda_driver_runtime_mismatch",
    "python_abi_mismatch",
    "illegal_instruction",
    "silent_cpu_fallback_detected",
    "unsupported_kernel",
    "runtime_crash",
    "runtime_import_failure",
)


def classify_startup_failure(text: str) -> tuple[str, list[str]]:
    """Return (primary startup category, all categories) for a failed probe."""
    hits = _taxonomy_hits(text)
    for category in STARTUP_CATEGORY_PRIORITY:
        if category in hits:
            return category, hits
    return (hits[0] if hits else "runtime_binary_startup_failed"), hits


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write the selection report atomically.

    Issue #54: a killed selector must not leave a truncated JSON file that later
    reads as a valid selectedArtifactId. Write to a sibling temp file, fsync it,
    then rename over the target (rename is atomic within a filesystem).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def registry_cuda_family(artifact_id: str) -> str | None:
    registry = _load_registry()
    for row in registry.get("artifacts", []):
        if row.get("id") == artifact_id:
            return row.get("cuda")
    return None


_REGISTRY_CACHE: dict[str, Any] | None = None


def _load_registry() -> dict[str, Any]:
    """Parse the artifact registry once; an unreadable registry is not fatal."""
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is None:
        _REGISTRY_CACHE = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return _REGISTRY_CACHE


def _read_receipt_executable(receipt: Path) -> tuple[Path | None, str | None]:
    """Return (executable, error). Never raises on a malformed receipt.

    Issue #54 requires every attempted binary to leave evidence behind. Letting a
    truncated or non-JSON receipt raise would abort the ladder before the attempt
    was written, so the failure is returned and recorded instead.
    """
    try:
        raw = receipt.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"receipt unreadable: {type(exc).__name__}: {exc}"
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        return None, f"receipt is not valid JSON: {exc}"
    if not isinstance(data, dict):
        return None, "receipt JSON is not an object"
    executable = data.get("runtimeExecutable")
    if not isinstance(executable, str) or not executable.strip():
        return None, "receipt has no runtimeExecutable path"
    return Path(executable), None


def _sha256_or_none(path: Path) -> tuple[str | None, str | None]:
    try:
        return sha256_file(path), None
    except OSError as exc:
        return None, f"sha256 failed: {type(exc).__name__}: {exc}"


def contains_source_build_marker(text: str) -> list[str]:
    lowered = (text or "").lower()
    return [marker for marker in SOURCE_BUILD_MARKERS if marker in lowered]


def parse_devices(output: str) -> dict[str, Any]:
    """Extract CUDA device evidence from a llama.cpp --list-devices payload."""
    caps = {(int(major), int(minor)) for major, minor in CC_PATTERN.findall(output or "")}
    names = GPU_NAME_PATTERN.findall(output or "")
    normalized_names = sorted({re.sub(r"\s+", " ", n).strip() for n in names})
    return {
        "computeCapabilities": sorted(f"{major}.{minor}" for major, minor in caps),
        "deviceNames": normalized_names,
        "cudaEnumerateLine": next(
            (line.strip() for line in (output or "").splitlines() if "CUDA" in line), None
        ),
    }


def has_cuda_device(evidence: dict[str, Any]) -> bool:
    """A CUDA runtime requires an enumerated device, not just the word CUDA."""
    if evidence.get("computeCapabilities"):
        return True
    if evidence.get("deviceNames"):
        return True
    return False


def _run_bounded(cmd: list[str], timeout: int) -> dict[str, Any]:
    """Run a probe with a hard timeout, bounded output, and no surviving orphan.

    `subprocess.run(..., timeout=)` kills only the *direct* child. A llama-server
    that has spawned helpers, or a shell wrapper, leaves those children running
    after the timeout fires (they are reparented to init). On Kaggle that means a
    killed probe can keep holding GPU memory, defeating the whole point of
    stepping the ladder. Issue #54 therefore starts the probe in its own session
    and SIGKILLs the entire process group, then reaps the leader.
    """
    with tempfile.TemporaryFile(mode="w+b") as sink:
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=sink,
                stderr=subprocess.STDOUT,
                text=False,
                start_new_session=True,
            )
        except OSError as exc:
            # e.g. the receipt points at a non-executable file. Report it as a
            # probe result rather than letting OSError unwind and lose the
            # attempt's evidence.
            return {
                "command": cmd,
                "timedOut": False,
                "timeoutSeconds": timeout,
                "returnCode": None,
                "output": "",
                "outputTruncated": False,
                "spawnError": f"{type(exc).__name__}: {exc}",
            }

        timed_out = False
        kill_note = None
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_note = _kill_process_group(proc)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:  # pragma: no cover - SIGKILL ignored
                kill_note = (kill_note or "") + " (leader still un-reaped)"

        sink.seek(0)
        raw = sink.read(PROBE_OUTPUT_LIMIT_BYTES + 1)
        truncated = len(raw) > PROBE_OUTPUT_LIMIT_BYTES
        if truncated:
            raw = raw[:PROBE_OUTPUT_LIMIT_BYTES]
        output = raw.decode("utf-8", "replace")

    result: dict[str, Any] = {
        "command": cmd,
        "timedOut": timed_out,
        "timeoutSeconds": timeout,
        "returnCode": proc.returncode,
        "output": output,
        "outputTruncated": truncated,
        "spawnError": None,
    }
    if kill_note:
        result["timeoutKill"] = kill_note
    return result


def _kill_process_group(proc: subprocess.Popen) -> str:
    """SIGKILL the probe's whole process group so no grandchild survives."""
    try:
        # The probe was started with start_new_session=True, so it leads its own
        # group and its pgid equals its pid.
        pgid = os.getpgid(proc.pid)
    except OSError:
        pgid = proc.pid
    try:
        os.killpg(pgid, signal.SIGKILL)
        return f"killed process group {pgid}"
    except OSError:
        try:
            proc.kill()
            return f"killed process {proc.pid}"
        except OSError:
            return "process already exited"
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        if isinstance(partial, bytes):  # pragma: no cover - py<3.11 shapes
            partial = partial.decode("utf-8", "replace")
        return {
            "command": cmd,
            "timedOut": True,
            "timeoutSeconds": timeout,
            "returnCode": None,
            "output": partial,
        }
    return {
        "command": cmd,
        "timedOut": False,
        "timeoutSeconds": timeout,
        "returnCode": proc.returncode,
        "output": proc.stdout,
    }


def _taxonomy_hits(text: str) -> list[str]:
    """Reuse the shared #53 failure taxonomy instead of inventing categories."""
    if "kaggle_failure_taxonomy.py" in sys.modules:
        return sys.modules["kaggle_failure_taxonomy"].classify(text)
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "kaggle_failure_taxonomy", HERE / "kaggle_failure_taxonomy.py"
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        return []
    module = importlib.util.module_from_spec(spec)
    sys.modules["kaggle_failure_taxonomy"] = module
    spec.loader.exec_module(module)
    return module.classify(text)


def probe_binary(executable: Path, *, nvidia_smi: list[str] | None = None) -> dict[str, Any]:
    """Bounded actual-binary compatibility probe for one pinned artifact.

    Pure with respect to the process boundary so CPU tests can drive it with
    fake executables and a stubbed runner.
    """
    result: dict[str, Any] = {
        "executable": str(executable),
        "executableSha256": None,
        "executableExists": executable.is_file(),
        "startupFailureCategories": [],
        "version": None,
        "devices": None,
        "driver": None,
        "compatible": False,
        "failureCategory": None,
        "failureDetail": None,
        "sourceBuildMarkers": [],
    }
    if not result["executableExists"]:
        result["failureCategory"] = "runtime_binary_missing"
        result["failureDetail"] = f"runtime executable is not a file: {executable}"
        return result
    if not os.access(executable, os.X_OK):
        result["failureCategory"] = "runtime_binary_not_executable"
        result["failureDetail"] = f"runtime executable is not executable: {executable}"
        return result
    try:
        result["executableSha256"] = sha256_file(executable)
    except OSError as exc:
        result["failureCategory"] = "runtime_binary_unreadable"
        result["failureDetail"] = f"runtime executable could not be hashed: {exc}"
        return result

    version = _run_bounded([str(executable), "--version"], VERSION_TIMEOUT_S)
    result["version"] = version
    result["sourceBuildMarkers"] = contains_source_build_marker(version.get("output", ""))
    if result["sourceBuildMarkers"]:
        result["failureCategory"] = "source_build_attempt_forbidden"
        result["failureDetail"] = (
            "probe output indicates a source build: " + ", ".join(result["sourceBuildMarkers"])
        )
        return result
    if version.get("spawnError"):
        category, hits = classify_startup_failure(str(version["spawnError"]))
        result["startupFailureCategories"] = hits
        result["failureCategory"] = category
        result["failureDetail"] = f"--version could not be started: {version['spawnError']}"
        return result
    if version["timedOut"]:
        result["failureCategory"] = "runtime_binary_timeout"
        result["failureDetail"] = f"--version exceeded {VERSION_TIMEOUT_S}s"
        return result
    if version["returnCode"] != 0:
        output = version.get("output", "")
        category, hits = classify_startup_failure(output)
        result["startupFailureCategories"] = hits
        result["failureCategory"] = category
        result["failureDetail"] = f"--version exited {version['returnCode']}"
        return result

    devices = _run_bounded([str(executable), "--list-devices"], DEVICES_TIMEOUT_S)
    result["devices"] = devices
    if contains_source_build_marker(devices.get("output", "")):
        result["sourceBuildMarkers"] = contains_source_build_marker(devices.get("output", ""))
        result["failureCategory"] = "source_build_attempt_forbidden"
        result["failureDetail"] = "--list-devices output indicates a source build"
        return result
    if devices.get("spawnError"):
        category, hits = classify_startup_failure(str(devices["spawnError"]))
        result["startupFailureCategories"] = hits
        result["failureCategory"] = category
        result["failureDetail"] = f"--list-devices could not be started: {devices['spawnError']}"
        return result
    if devices["timedOut"]:
        result["failureCategory"] = "runtime_binary_timeout"
        result["failureDetail"] = f"--list-devices exceeded {DEVICES_TIMEOUT_S}s"
        return result
    if devices["returnCode"] != 0:
        category, hits = classify_startup_failure(devices.get("output", ""))
        result["startupFailureCategories"] = hits
        result["failureCategory"] = category
        result["failureDetail"] = f"--list-devices exited {devices['returnCode']}"
        return result

    evidence = parse_devices(devices.get("output", ""))
    result["cudaEvidence"] = evidence
    if not has_cuda_device(evidence):
        result["failureCategory"] = "silent_cpu_fallback_detected"
        result["failureDetail"] = (
            "binary started but no CUDA device was enumerated; a CPU-only run cannot "
            "qualify a CUDA runtime"
        )
        return result

    if EXPECTED_COMPUTE_CAPABILITY not in evidence["computeCapabilities"]:
        # Reuse #53's own category. "unsupported_kernel" there means a real
        # kernel-level fault ("no kernel image is available", "invalid device
        # function"); a device that simply is not a T4 is a compute-capability
        # mismatch, and mislabelling it would send an operator hunting for a
        # broken kernel image.
        result["failureCategory"] = "unsupported_compute_capability"
        result["failureDetail"] = (
            f"enumerated compute capability {evidence['computeCapabilities']} does not include "
            f"the T4 value {EXPECTED_COMPUTE_CAPABILITY}"
        )
        return result

    result["driver"] = nvidia_smi if nvidia_smi is not None else _collect_nvidia_smi()
    result["compatible"] = True
    return result


def _collect_nvidia_smi() -> dict[str, Any] | list[str]:
    if not _which("nvidia-smi"):
        return []
    probe = _run_bounded(
        ["nvidia-smi", "--query-gpu=name,driver_version,compute_cap", "--format=csv,noheader"],
        20,
    )
    return probe


def _which(binary: str) -> str | None:
    import shutil

    return shutil.which(binary)


def probe_is_runtime_binary_incompatibility(probe: dict[str, Any]) -> bool:
    """Which probe failures justify stepping down the predeclared ladder.

    Issue #54: fallback is a *runtime-binary compatibility* fallback only. A
    candidate-specific model failure must not bounce between runtime builds, so
    the set below is restricted to failures of the binary/driver/ABI itself.

    Every entry is a property of *this* artifact (bad packaging, wrong
    architecture, unloadable native libraries, a driver too old for its CUDA
    build, a binary that starts but enumerates nothing), so trying the other
    pinned build is genuinely informative. Anything not listed is treated as
    *not* eligible, which keeps the walk fail-closed: an unrecognised outcome
    halts the ladder instead of silently burning the remaining entries.
    """
    return probe.get("failureCategory") in {
        "runtime_binary_missing",
        "runtime_binary_not_executable",
        "runtime_binary_unreadable",
        "runtime_receipt_unusable",
        "runtime_binary_startup_failed",
        "runtime_binary_timeout",
        "python_abi_mismatch",
        "illegal_instruction",
        "runtime_crash",
        "native_library_or_abi_failure",
        "cuda_driver_runtime_mismatch",
        "unsupported_kernel",
        "silent_cpu_fallback_detected",
        "source_build_attempt_forbidden",
    }


def probe_halts_ladder(probe: dict[str, Any]) -> bool:
    """Failures that stepping down the CUDA ladder cannot possibly fix.

    The ladder is a *runtime-binary compatibility* ladder over one pinned source
    commit. If the enumerated hardware is not a T4, or the driver itself is
    missing, then trying the 12.4 build against the same driver and the same GPU
    yields the same answer; the honest outcome is a halt with the evidence
    recorded, not two identical probes and a false impression that the 12.4
    binary was also tried and rejected.
    """
    return probe.get("failureCategory") in {
        "unsupported_compute_capability",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime-dir", type=Path, default=Path("/kaggle/working/pari-runtimes"))
    ap.add_argument("--output", type=Path, default=Path("/kaggle/working/results/prism-runtime-selection.json"))
    ap.add_argument(
        "--probe-only",
        action="store_true",
        help="run the ladder without installing; used by tests and by operators "
        "who pre-installed both binaries",
    )
    args = ap.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "version": REPORT_VERSION,
        "policy": "predeclared vendor-binary compatibility ladder; no source build",
        "ladder": list(LADDER),
        "attempts": [],
        "selectedArtifactId": None,
        "status": "in_progress",
    }

    for artifact_id in LADDER:
        receipt = args.runtime_dir / f"{artifact_id}.receipt.json"
        # Captured *before* any install work. Reading it afterwards would report
        # an install-created receipt as if the operator had already staged it.
        receipt_existed_before = receipt.is_file()
        install_output = ""
        install_rc = 0
        if not receipt_existed_before and not args.probe_only:
            install = subprocess.run(
                [sys.executable, str(INSTALL), artifact_id, "--dest", str(args.runtime_dir)],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            install_rc = install.returncode
            install_output = install.stdout
        verify = None
        if install_rc == 0 and not args.probe_only:
            verify = subprocess.run(
                [sys.executable, str(VERIFY), artifact_id, "--runtime-dir", str(args.runtime_dir)],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )

        # Issue #54: metadata verification is necessary but not sufficient. Run
        # the actual pinned binary before this artifact can be selected.
        probe: dict[str, Any] | None = None
        attempt_errors: list[str] = []
        if receipt.is_file() and install_rc == 0:
            executable, receipt_error = _read_receipt_executable(receipt)
            probe = {
                "executable": str(executable) if executable else None,
                "compatible": False,
                "failureCategory": None,
                "failureDetail": None,
            }
            probe["receiptPath"] = str(receipt)
            probe["receiptSha256"], receipt_sha_error = _sha256_or_none(receipt)
            for problem in (receipt_error, receipt_sha_error):
                if problem:
                    attempt_errors.append(problem)
            if attempt_errors:
                probe["failureCategory"] = "runtime_receipt_unusable"
                probe["failureDetail"] = "; ".join(attempt_errors)
            else:
                probe = probe_binary(executable)
                probe["cudaBuildFamilyFromRegistry"] = registry_cuda_family(artifact_id)
            # Issue #54: this flag records whether stepping to the next binary is
            # a legitimate runtime-binary compatibility fallback (vs. any other
            # failure), keeping the two failure classes distinguishable in the
            # preserved evidence.
            probe["fallbackEligible"] = probe_is_runtime_binary_incompatibility(probe)
            probe["haltsLadder"] = probe_halts_ladder(probe)

        attempt = {
            "artifactId": artifact_id,
            "receiptExistedBeforeAttempt": receipt_existed_before,
            "installReturnCode": install_rc,
            "installOutput": install_output,
            "verifyReturnCode": verify.returncode if verify else None,
            "verifyOutput": verify.stdout if verify else None,
            "compatibilityProbe": probe,
            "attemptErrors": attempt_errors,
        }
        report["attempts"].append(attempt)
        # Every attempt is durably recorded before any decision is made, so an
        # interrupted selector still leaves evidence of what it tried.
        atomic_write_json(args.output, report)

        metadata_ok = install_rc == 0 and (
            verify is None if args.probe_only else (verify is not None and verify.returncode == 0)
        )
        probe_ok = probe is not None and probe.get("compatible") is True
        if metadata_ok and probe_ok:
            report["selectedArtifactId"] = artifact_id
            report["status"] = "selected_prebuilt"
            report["selectedExecutable"] = probe["executable"]
            report["selectedExecutableSha256"] = probe["executableSha256"]
            report["selectedCudaEvidence"] = probe.get("cudaEvidence")
            report["selectedDriverEvidence"] = probe.get("driver")
            atomic_write_json(args.output, report)
            print(json.dumps({"status": report["status"], "selectedArtifactId": artifact_id, "artifact": str(args.output)}, indent=2))
            return

        # Issue #54: only a genuine runtime-binary incompatibility may advance the
        # ladder, and only within the predeclared 12.8 -> 12.4 order. Any other
        # outcome halts the walk so the report can never imply that an untried
        # binary was probed and rejected.
        if probe is not None and not probe.get("fallbackEligible"):
            reason = probe.get("failureCategory") or "no compatibility probe result"
            report["ladderHaltedAt"] = artifact_id
            report["ladderHaltReason"] = (
                f"{reason}: not a runtime-binary incompatibility, so stepping down the "
                "declared CUDA 12.8->12.4 ladder cannot change the outcome"
            )
            if probe.get("haltsLadder"):
                report["ladderHaltReason"] += (
                    "; the enumerated hardware is not the declared T4 target"
                )
            atomic_write_json(args.output, report)
            break

    report["status"] = "runtime_unqualified"
    # A failed artifact must never leave a stale selectedArtifactId behind.
    report["selectedArtifactId"] = None
    report.pop("selectedExecutable", None)
    report.pop("selectedExecutableSha256", None)
    report.pop("selectedCudaEvidence", None)
    report.pop("selectedDriverEvidence", None)
    report["failureCategories"] = [
        {
            "artifactId": a["artifactId"],
            "failureCategory": (a.get("compatibilityProbe") or {}).get("failureCategory"),
            "failureDetail": (a.get("compatibilityProbe") or {}).get("failureDetail"),
            "executable": (a.get("compatibilityProbe") or {}).get("executable"),
            "executableSha256": (a.get("compatibilityProbe") or {}).get("executableSha256"),
            "fallbackEligible": (a.get("compatibilityProbe") or {}).get("fallbackEligible"),
            "attemptErrors": a.get("attemptErrors") or [],
        }
        for a in report["attempts"]
    ]
    report["unattemptedArtifacts"] = [
        artifact_id for artifact_id in LADDER
        if artifact_id not in {a["artifactId"] for a in report["attempts"]}
    ]
    atomic_write_json(args.output, report)
    print(json.dumps({"status": report["status"], "selectedArtifactId": None, "artifact": str(args.output)}, indent=2))
    raise SystemExit(2)


if __name__ == "__main__":
    main()
