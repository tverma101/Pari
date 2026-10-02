#!/usr/bin/env python3
"""Verify CPU-prepared benchmark files before any Kaggle model execution."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXPECTED = {
    "kaggle-protocol-smoke.jsonl": 16,
    "english-core-shadow.jsonl": 68,
    "english-core-public-fast.jsonl": 1570,
    "semanticqa-lcc-english-core.jsonl": 305,
    "english-core-fixed-screen.jsonl": 1943,
    "word-studio-transform.jsonl": 100,
    "word-studio-strength.jsonl": 112,
}
EXPECTED_SEMANTICQA = "56c82a587f4a6cef609255cd10af372d8c76600a"
EXPECTED_PUBLIC = {
    "blimp": "877fba0801ffb7cbd8c39c1ff314a46f053f6036",
    "super_glue": "3de24cf8022e94f4ee4b9d55a6f539891524d646",
    "glue": "bcdcba79d07bc864c1c254ccfcedcce55bcc9a8c",
    "paws": "161ece9501cf0a11f3e48bd356eaa82de46d6a09",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def jsonl_count(path: Path) -> int:
    ids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        task_id = row.get("id")
        if not task_id:
            raise ValueError(f"missing task id in {path}")
        ids.append(str(task_id))
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate task ids in {path}")
    return len(ids)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--receipt", type=Path, default=Path("/kaggle/working/results/benchmark-preparation.json"))
    ap.add_argument("--benchmark-revision", required=True)
    args = ap.parse_args()

    failures: list[str] = []
    if not args.receipt.is_file():
        failures.append(f"missing preparation receipt {args.receipt}")
        receipt = {}
    else:
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))

    try:
        current_revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=HERE, text=True, stderr=subprocess.STDOUT
        ).strip()
    except Exception as exc:
        current_revision = None
        failures.append(f"cannot resolve benchmark Git HEAD: {type(exc).__name__}: {exc}")

    if current_revision != args.benchmark_revision:
        failures.append(f"current Git HEAD {current_revision!r} != requested benchmark revision {args.benchmark_revision!r}")
    if receipt.get("benchmarkRevision") != args.benchmark_revision:
        failures.append(
            f"preparation receipt benchmarkRevision {receipt.get('benchmarkRevision')!r} != requested {args.benchmark_revision!r}"
        )
    if receipt.get("publicDatasetRevisions") != EXPECTED_PUBLIC:
        failures.append("preparation receipt public dataset revisions do not match frozen contract")
    semanticqa = receipt.get("semanticQA") or {}
    if semanticqa.get("commit") != EXPECTED_SEMANTICQA:
        failures.append("preparation receipt SemanticQA commit does not match frozen contract")
    data_env = receipt.get("isolatedDataEnvironment") or {}
    if data_env.get("sourceCompilationAllowed") is not False:
        failures.append("data-preparation environment does not explicitly forbid source compilation")

    receipt_files = receipt.get("files") or {}
    observed = {}
    for filename, expected_count in EXPECTED.items():
        path = HERE / filename
        if not path.is_file():
            failures.append(f"missing prepared file {filename}")
            continue
        try:
            count = jsonl_count(path)
        except Exception as exc:
            failures.append(f"{filename}: {type(exc).__name__}: {exc}")
            continue
        digest = sha256_file(path)
        observed[filename] = {"cases": count, "sha256": digest}
        if count != expected_count:
            failures.append(f"{filename}: expected {expected_count} cases, got {count}")
        expected_receipt = receipt_files.get(filename) or {}
        if expected_receipt.get("cases") != count or expected_receipt.get("sha256") != digest:
            failures.append(f"{filename}: current file does not match preparation receipt")

    report = {
        "status": "verified" if not failures else "unqualified",
        "benchmarkRevision": args.benchmark_revision,
        "receipt": str(args.receipt),
        "observed": observed,
        "failures": failures,
    }
    print(json.dumps(report, indent=2))
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
