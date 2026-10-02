#!/usr/bin/env python3
"""Deterministic Kaggle T4x2 qualification preflight for Pari Issue #25/#28.

This script does not download models and does not score English. It produces a
machine-readable environment artifact that downstream runners can require.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

EXPECTED_GPU_NAME_FRAGMENT = "T4"
EXPECTED_GPU_COUNT = 2
EXPECTED_CC = (7, 5)
MIN_MEMORY_BYTES = 14 * 1024**3


def pkg(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def run_text(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
        return proc.returncode, proc.stdout.strip()
    except Exception as exc:
        return 127, f"{type(exc).__name__}: {exc}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--allow-non-kaggle", action="store_true", help="development only; promotion still remains unqualified")
    args = ap.parse_args()

    checks: list[dict[str, Any]] = []
    failures: list[str] = []
    warnings: list[str] = []
    hardware: dict[str, Any] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cudaVisibleDevices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "packages": {name: pkg(name) for name in ("torch", "vllm", "transformers", "huggingface-hub")},
        "gpus": [],
    }

    def check(name: str, ok: bool, detail: Any) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            failures.append(name)

    try:
        import torch
        hardware["torchVersion"] = torch.__version__
        hardware["cudaRuntimeVersion"] = torch.version.cuda
        check("cuda_available", torch.cuda.is_available(), torch.cuda.is_available())
        count = torch.cuda.device_count() if torch.cuda.is_available() else 0
        check("exactly_two_visible_gpus", count == EXPECTED_GPU_COUNT, count)
        for idx in range(count):
            prop = torch.cuda.get_device_properties(idx)
            row = {
                "index": idx,
                "name": prop.name,
                "totalMemoryBytes": int(prop.total_memory),
                "computeCapability": [int(prop.major), int(prop.minor)],
            }
            hardware["gpus"].append(row)
            check(f"gpu{idx}_is_t4", EXPECTED_GPU_NAME_FRAGMENT.lower() in prop.name.lower(), prop.name)
            check(f"gpu{idx}_cc_7_5", (prop.major, prop.minor) == EXPECTED_CC, [prop.major, prop.minor])
            check(f"gpu{idx}_memory_at_least_14GiB", int(prop.total_memory) >= MIN_MEMORY_BYTES, int(prop.total_memory))
    except Exception as exc:
        failures.append("torch_gpu_inspection")
        hardware["torchGpuInspectionError"] = f"{type(exc).__name__}: {exc}"

    rc, smi = run_text([
        "nvidia-smi",
        "--query-gpu=index,name,memory.total,memory.free,driver_version,pstate",
        "--format=csv,noheader",
    ])
    hardware["nvidiaSmi"] = smi.splitlines() if smi else []
    check("nvidia_smi_works", rc == 0, smi)

    kaggle_markers = {
        "KAGGLE_KERNEL_RUN_TYPE": os.environ.get("KAGGLE_KERNEL_RUN_TYPE"),
        "KAGGLE_URL_BASE": os.environ.get("KAGGLE_URL_BASE"),
        "KAGGLE_DATA_PROXY_TOKEN": bool(os.environ.get("KAGGLE_DATA_PROXY_TOKEN")),
    }
    hardware["kaggleMarkers"] = kaggle_markers
    appears_kaggle = any(v for v in kaggle_markers.values()) or Path("/kaggle/working").exists()
    if not appears_kaggle:
        warnings.append("kaggle_environment_marker_not_detected")
        if not args.allow_non_kaggle:
            failures.append("real_kaggle_environment_not_detected")

    status = "qualified" if not failures else "unqualified"
    artifact = {
        "schemaVersion": 1,
        "purpose": "Pari Kaggle 2xT4 preflight; no linguistic scoring",
        "timestampUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": status,
        "promotionEligibleEnvironment": status == "qualified" and appears_kaggle,
        "hardware": hardware,
        "checks": checks,
        "failures": failures,
        "warnings": warnings,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "output": str(args.output), "failures": failures, "warnings": warnings}, indent=2))
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
