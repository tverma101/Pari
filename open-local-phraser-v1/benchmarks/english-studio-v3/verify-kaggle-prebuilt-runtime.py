#!/usr/bin/env python3
"""Verify that the canonical Kaggle runtime came from the pinned binary registry."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "kaggle-prebuilt-runtimes.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("artifact_id")
    ap.add_argument("--runtime-dir", type=Path, default=Path("/kaggle/working/pari-runtimes"))
    args = ap.parse_args()

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    artifacts = {row["id"]: row for row in registry["artifacts"]}
    expected = artifacts.get(args.artifact_id)
    if expected is None:
        raise SystemExit(f"artifact {args.artifact_id!r} is not in the pinned runtime registry")

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

    if expected["kind"] == "python_wheel" and expected["runtime"] == "vllm":
        try:
            installed = importlib.metadata.version("vllm")
        except importlib.metadata.PackageNotFoundError:
            installed = None
        if installed != expected["version"]:
            failures.append(f"installed vLLM={installed!r}, expected {expected['version']!r}")
    elif expected["kind"] == "tarball":
        executable = Path(receipt.get("runtimeExecutable") or "")
        if not executable.is_file():
            failures.append(f"runtime executable missing: {executable}")
        source_commit = expected.get("sourceCommit")
        if source_commit and artifact.get("sourceCommit") != source_commit:
            failures.append("vendor runtime source commit mismatch")

    if failures:
        print(json.dumps({"status": "unqualified", "receipt": str(receipt_path), "failures": failures}, indent=2))
        raise SystemExit(2)

    print(json.dumps({
        "status": "verified_prebuilt",
        "artifactId": args.artifact_id,
        "runtime": expected["runtime"],
        "version": expected["version"],
        "sha256": expected["sha256"],
        "receipt": str(receipt_path),
    }, indent=2))


if __name__ == "__main__":
    main()
