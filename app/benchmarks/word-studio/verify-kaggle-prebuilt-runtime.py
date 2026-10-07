#!/usr/bin/env python3
"""Verify that the canonical Kaggle runtime came from the pinned binary registry.

Issue #41 adds the serving environment to the runtime identity: the pinned wheel
hash alone is not enough. For Python wheels this verifier also binds

* the hash of the dependency lock and of the materialised requirements file,
* the isolated interpreter identity,
* the installed package table (name + version) against that lock,
* a bounded import/CUDA smoke report,
* driver, torch CUDA version and visible compute capability.

Any failure is reported as a structured, machine-readable
``runtime_unqualified`` classification. Nothing here repairs the environment.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "kaggle-prebuilt-runtimes.json"

SMOKE_SENTINEL = "PARI_RUNTIME_SMOKE_JSON:"
SMOKE_TIMEOUT_SECONDS = 180
ENTRYPOINT_TIMEOUT_SECONDS = 120


def _load_installer() -> Any:
    """Reuse the installer's hash/lock helpers without duplicating the contract."""
    spec = importlib.util.spec_from_file_location(
        "pari_install_prebuilt_runtime", HERE / "install-kaggle-prebuilt-runtime.py"
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError("could not load install-kaggle-prebuilt-runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INSTALLER = _load_installer()
canonical_name = INSTALLER.canonical_name
sha256_bytes = INSTALLER.sha256_bytes


PACKAGE_TABLE_SOURCE = r"""
import importlib.metadata as md
import json
import sys

rows = {}
for dist in md.distributions():
    name = dist.metadata.get("Name")
    if not name:
        continue
    record = ""
    try:
        record = str(dist.read_text("RECORD") or "")
    except Exception:
        record = ""
    rows[name] = {
        "version": dist.version,
        "location": str(getattr(dist, "_path", "") or ""),
        "recordSha256": __import__("hashlib").sha256(record.encode()).hexdigest() if record else None,
    }
print(json.dumps({"python": sys.version, "packages": rows}))
"""


IMPORT_SMOKE_SOURCE = r"""
import importlib
import json
import os
import subprocess
import sys
import traceback

SENTINEL = "PARI_RUNTIME_SMOKE_JSON:"
venv_root = sys.argv[1]
smoke_spec = json.loads(sys.argv[2])


def probe(name, fn):
    try:
        detail = fn() or {}
        return {"name": name, "ok": True, "detail": detail}
    except BaseException as exc:
        return {
            "name": name,
            "ok": False,
            "errorType": type(exc).__name__,
            "error": str(exc)[:2000],
            "tracebackTail": traceback.format_exc()[-2000:],
        }


def module_identity(module_name):
    module = importlib.import_module(module_name)
    path = getattr(module, "__file__", None)
    return {
        "version": getattr(module, "__version__", None),
        "file": path,
        "insideVenv": bool(path and os.path.realpath(path).startswith(os.path.realpath(venv_root))),
    }


def torch_identity():
    import torch

    detail = {
        "version": torch.__version__,
        "torchCudaVersion": torch.version.cuda,
        "file": getattr(torch, "__file__", None),
    }
    try:
        available = bool(torch.cuda.is_available())
    except BaseException as exc:
        detail["cudaProbeError"] = f"{type(exc).__name__}: {exc}"
        return detail
    detail["cudaAvailable"] = available
    if not available:
        return detail
    count = torch.cuda.device_count()
    detail["deviceCount"] = count
    try:
        raw = torch._C._cuda_getDriverVersion()
        detail["driverVersion"] = f"{raw // 1000}.{(raw % 1000) // 10}"
    except BaseException as exc:
        detail["driverProbeError"] = f"{type(exc).__name__}: {exc}"
    devices = []
    for index in range(count):
        props = torch.cuda.get_device_properties(index)
        devices.append(
            {
                "index": index,
                "name": props.name,
                "computeCapability": f"{props.major}.{props.minor}",
            }
        )
    detail["devices"] = devices
    return detail


def torchvision_nms():
    import torch
    import torchvision

    # A bare import can succeed while the compiled op table is mismatched, which
    # is the exact upstream failure Issue #41 cites. Call one real operator.
    boxes = torch.tensor([[0.0, 0.0, 1.0, 1.0], [0.1, 0.1, 1.1, 1.1]])
    scores = torch.tensor([0.9, 0.8])
    keep = torchvision.ops.nms(boxes, scores, 0.5)
    return {
        "version": torchvision.__version__,
        "torchVersion": torch.__version__,
        "file": getattr(torchvision, "__file__", None),
        "nmsKeep": int(keep.numel()),
    }


def vllm_serve_help():
    entry = os.path.join(venv_root, "bin", "vllm")
    if not os.path.exists(entry):
        raise FileNotFoundError(f"vllm console script missing from the isolated env: {entry}")
    proc = subprocess.run(
        [entry, "serve", "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=int(os.environ.get("PARI_ENTRYPOINT_TIMEOUT", "120")),
    )
    return {
        "entrypoint": entry,
        "returncode": proc.returncode,
        "outputHead": proc.stdout[:1500],
    }


PROBES = {
    "module_identity": lambda spec: module_identity(spec["module"]),
    "torch_identity": torch_identity,
    "torchvision_nms": torchvision_nms,
    "vllm_identity": lambda spec: module_identity(spec.get("module", "vllm")),
    "vllm_serve_help": vllm_serve_help,
}

results = []
for spec in smoke_spec:
    name = spec.get("probe") or "module_identity"
    fn = PROBES.get(name)
    if fn is None:
        results.append({"name": name, "ok": False, "error": f"unknown probe {name!r}"})
        continue
    outcome = probe(name, lambda fn=fn, spec=spec: fn(spec))
    outcome["module"] = spec.get("module")
    outcome["required"] = bool(spec.get("required"))
    results.append(outcome)

print(SENTINEL + json.dumps({"python": sys.version, "results": results}))
"""


def run_probe_source(python: Path, source: str, argv: list[str], env: dict[str, str]) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
        handle.write(source)
        script = handle.name
    try:
        proc = subprocess.run(
            [str(python), "-I", script, *argv],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            timeout=SMOKE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"probe timed out after {SMOKE_TIMEOUT_SECONDS}s"}
    finally:
        Path(script).unlink(missing_ok=True)
    for line in proc.stdout.splitlines():
        if line.startswith(SMOKE_SENTINEL):
            payload = json.loads(line[len(SMOKE_SENTINEL):])
            payload["returncode"] = proc.returncode
            return payload
    return {
        "ok": False,
        "error": "probe produced no machine-readable result",
        "returncode": proc.returncode,
        "stdoutTail": proc.stdout[-2000:],
        "stderrTail": proc.stderr[-2000:],
    }


def installed_package_table(python: Path, env: dict[str, str]) -> tuple[dict[str, Any], list[str]]:
    payload = run_probe_source(python, PACKAGE_TABLE_SOURCE, [], env)
    if not payload.get("packages"):
        return {}, [f"could not read the installed package table: {payload.get('error', 'unknown')}"]
    return payload, []


def classify_import_smoke(env_spec: dict[str, Any], smoke: dict[str, Any]) -> tuple[str, list[str]]:
    """Pure decision function: import/CUDA smoke report -> classification + failures."""
    results = {row.get("name"): row for row in smoke.get("results", [])}
    failures: list[str] = []
    cuda_unavailable = False
    for spec in env_spec.get("importSmoke", []):
        name = spec.get("probe")
        row = results.get(name)
        required = bool(spec.get("required"))
        if row is None:
            if required:
                failures.append(f"import smoke did not run required probe {name!r}")
            continue
        if not row.get("ok"):
            message = f"probe {name!r} failed: {row.get('error') or row.get('errorType')}"
            if required:
                failures.append(message)
            continue
        detail = row.get("detail") or {}
        module = spec.get("module")
        if detail.get("insideVenv") is False:
            failures.append(
                f"probe {name!r} resolved {module or 'the runtime'} to {detail.get('file')!r} "
                "outside the isolated venv; a stale global package would shadow the frozen closure"
            )

    torch_row = results.get("torch_identity")
    if torch_row is not None and torch_row.get("ok"):
        detail = torch_row.get("detail") or {}
        if detail.get("cudaAvailable") is False:
            cuda_unavailable = True

    cuda_spec = env_spec.get("cuda") or {}
    if cuda_spec.get("required") and cuda_unavailable:
        return "environment_cuda_unavailable", failures or ["torch.cuda.is_available() was False"]
    if failures:
        return "import_smoke_failed", failures
    return "ok", []


def check_compute_capability(env_spec: dict[str, Any], smoke: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    torch_row = next((r for r in smoke.get("results", []) if r.get("name") == "torch_identity"), None)
    if not torch_row or not torch_row.get("ok"):
        return failures
    detail = torch_row.get("detail") or {}
    expected = {str(v) for v in (env_spec.get("cuda") or {}).get("expectedComputeCapability") or []}
    if not expected:
        return failures
    observed = {d.get("computeCapability") for d in detail.get("devices", [])}
    if not observed & expected:
        failures.append(
            f"visible compute capability {sorted(o for o in observed if o)} does not include "
            f"the expected T4 value(s) {sorted(expected)}"
        )
    return failures


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("artifact_id")
    ap.add_argument("--runtime-dir", type=Path, default=Path("/kaggle/working/pari-runtimes"))
    ap.add_argument("--skip-import-smoke", action="store_true")
    args = ap.parse_args()

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    artifacts = {row["id"]: row for row in registry["artifacts"]}
    expected = artifacts.get(args.artifact_id)
    if expected is None:
        raise SystemExit(f"artifact {args.artifact_id!r} is not in the pinned runtime registry")
    env_spec = INSTALLER.environment_for(registry, args.artifact_id)

    receipt_path = args.runtime_dir / f"{args.artifact_id}.receipt.json"
    if not receipt_path.is_file():
        raise SystemExit(f"missing pinned runtime receipt: {receipt_path}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    artifact = receipt.get("artifact") or {}

    failures: list[str] = []
    for key in ("id", "kind", "runtime", "version", "url", "sha256"):
        if artifact.get(key) != expected.get(key):
            failures.append(f"artifact.{key}: receipt={artifact.get(key)!r} expected={expected.get(key)!r}")
    if receipt.get("sha256Verified") != expected.get("sha256"):
        failures.append("receipt sha256Verified does not match registry")
    if receipt.get("sourceCompilationAllowed") is not False:
        failures.append("receipt does not explicitly forbid source compilation")

    env_evidence: dict[str, Any] = {}
    lock_evidence: dict[str, Any] = {}
    classification = "receipt_mismatch"

    if expected["kind"] == "python_wheel":
        if env_spec is None:
            failures.append(
                f"artifact {args.artifact_id!r} has no environments[] contract; "
                "Issue #41 requires an isolated, hash-bound environment for Python wheels"
            )
        else:
            dep = env_spec.get("dependencyLock") or {}
            lock_entry = receipt.get("dependencyLock") or {}
            venv_python = Path((receipt.get("environment") or {}).get("pythonExecutable") or "")
            venv_root = Path((receipt.get("environment") or {}).get("venvPath") or "")

            if dep.get("state") != "locked":
                failures.append(
                    f"registry dependencyLock.state={dep.get('state')!r}; the closure has not been "
                    "resolved and reviewed on the Kaggle image"
                )
                classification = "dependency_lock_pending"
            if receipt.get("environment", {}).get("kind") != "dedicated_venv":
                failures.append("receipt does not record a dedicated_venv environment")
            if not venv_python.is_file():
                failures.append(f"isolated interpreter missing: {venv_python}")
            if receipt.get("environment", {}).get("pythonExecutableSha256") != INSTALLER.sha256_file(venv_python):
                failures.append("isolated interpreter sha256 does not match the receipt")

            lock_path = INSTALLER.HERE / dep["file"] if dep.get("file") else None
            lock_bytes = lock_path.read_bytes() if lock_path and lock_path.is_file() else None
            lock = json.loads(lock_bytes) if lock_bytes else None
            failures.extend(
                INSTALLER.evaluate_lock(env_spec, lock, dep.get("sha256"), lock_bytes, None)
            )
            if lock is not None and lock_entry.get("sha256") != sha256_bytes(lock_bytes or b""):
                failures.append("receipt dependencyLock.sha256 does not match the committed lock")
            lock_evidence = {
                "path": str(lock_path) if lock_path else None,
                "sha256": lock_entry.get("sha256"),
                "packageCount": lock_entry.get("packageCount"),
                "requirementsTxtSha256": lock_entry.get("requirementsTxtSha256"),
            }

            if venv_python.is_file() and not failures:
                probe_env = INSTALLER.isolated_env(venv_root or venv_python.parent.parent)
                table, table_failures = installed_package_table(venv_python, probe_env)
                failures.extend(table_failures)
                if lock is not None and table.get("packages"):
                    pinned = INSTALLER.locked_versions(lock, include_optional=True)
                    live = {canonical_name(k): v.get("version") for k, v in table["packages"].items()}
                    for name, version in sorted(pinned.items()):
                        if live.get(name) != version:
                            failures.append(
                                f"installed {name}={live.get(name)!r} differs from the frozen lock "
                                f"version {version!r}"
                            )
                    env_evidence["installedPackageCount"] = len(live)
                    env_evidence["python"] = table.get("python")

                smoke_spec = env_spec.get("importSmoke", [])
                smoke: dict[str, Any] = {"skipped": bool(args.skip_import_smoke)}
                if not args.skip_import_smoke and smoke_spec:
                    smoke = run_probe_source(
                        venv_python,
                        IMPORT_SMOKE_SOURCE,
                        [str(venv_root or venv_python.parent.parent), json.dumps(smoke_spec)],
                        probe_env,
                    )
                    smoke_class, smoke_failures = classify_import_smoke(env_spec, smoke)
                    failures.extend(smoke_failures)
                    if smoke_class != "ok":
                        classification = smoke_class
                    failures.extend(check_compute_capability(env_spec, smoke))
                env_evidence["importSmoke"] = smoke
                env_evidence["cuda"] = next(
                    (r.get("detail") for r in smoke.get("results", []) if r.get("name") == "torch_identity"),
                    None,
                )
    elif expected["kind"] == "tarball":
        executable = Path(receipt.get("runtimeExecutable") or "")
        if not executable.is_file():
            failures.append(f"runtime executable missing: {executable}")
        source_commit = expected.get("sourceCommit")
        if source_commit and artifact.get("sourceCommit") != source_commit:
            failures.append("vendor runtime source commit mismatch")

    if failures:
        print(
            json.dumps(
                {
                    "status": "runtime_unqualified",
                    "classification": classification,
                    "receipt": str(receipt_path),
                    "failures": failures,
                    "environment": env_evidence,
                    "dependencyLock": lock_evidence,
                    "sourceCompilationAttempted": False,
                },
                indent=2,
            )
        )
        raise SystemExit(2)

    print(
        json.dumps(
            {
                "status": "verified_prebuilt",
                "artifactId": args.artifact_id,
                "runtime": expected["runtime"],
                "version": expected["version"],
                "sha256": expected["sha256"],
                "receipt": str(receipt_path),
                "environment": env_evidence,
                "dependencyLock": lock_evidence,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
