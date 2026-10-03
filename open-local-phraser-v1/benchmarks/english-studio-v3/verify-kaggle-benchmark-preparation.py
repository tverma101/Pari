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
STAGE_MANIFEST = HERE / "kaggle-stage-manifest.json"
PREPARED_REGISTER_NAME = "kaggle-stage-manifest.prepared.json"
PREPARED_REGISTER_KEY = "preparedStageRegister"


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


def ordered_ids_sha256(ids: list[str]) -> str:
    """Ordered task-ID digest, using the same canonical shape as the register."""
    payload = json.dumps(
        {"orderedTaskIds": list(ids)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def find_prepared_register(receipt_path: Path) -> Path:
    """The bundled register copy, falling back to the receipt's own directory."""
    bundled = HERE / PREPARED_REGISTER_NAME
    if bundled.is_file():
        return bundled
    return receipt_path.parent / PREPARED_REGISTER_NAME


def generated_stage_entries() -> dict[str, dict]:
    payload = json.loads(STAGE_MANIFEST.read_text(encoding="utf-8"))
    stages = payload.get("stages") or {}
    return {
        stage: entry
        for stage, entry in stages.items()
        if entry.get("identitySource") == "prepared-register"
    }


def validate_prepared_stage_register(receipt: dict, receipt_path: Path) -> list[str]:
    """Check the frozen generated-stage identity and its receipt binding.

    The bundled prepared register must be the exact bytes preparation froze, bound to
    this checked-in stage manifest, and agree with the receipt's per-stage freeze and
    with the artifacts now on disk. Any mismatch leaves the generated stage
    unqualified rather than silently accepted.
    """
    failures: list[str] = []
    stage_manifest_sha = sha256_file(STAGE_MANIFEST)
    generated = generated_stage_entries()
    if not generated:
        return ["stage manifest declares no generated stage, so there is nothing to freeze"]

    binding = receipt.get(PREPARED_REGISTER_KEY)
    if not isinstance(binding, dict):
        return [
            f"preparation receipt carries no {PREPARED_REGISTER_KEY} block, so generated "
            "stages cannot be qualified"
        ]

    register_path = find_prepared_register(receipt_path)
    if not register_path.is_file():
        return [
            f"prepared stage register {PREPARED_REGISTER_NAME} is missing; generated stages "
            "stay unqualified"
        ]

    register_sha = sha256_file(register_path)
    if binding.get("fileSha256") != register_sha:
        failures.append(
            f"prepared stage register digest {register_sha} does not match the receipt freeze "
            f"{binding.get('fileSha256')!r}"
        )
    if binding.get("stageManifestSha256") != stage_manifest_sha:
        failures.append(
            "prepared stage register is bound to a different stage manifest than the checked-in "
            f"{STAGE_MANIFEST.name}"
        )

    try:
        register = json.loads(register_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        failures.append(f"prepared stage register is not valid JSON: {exc}")
        return failures
    if register.get("stageManifestSha256") != stage_manifest_sha:
        failures.append("prepared stage register itself claims a different stage manifest digest")
    if binding.get("benchmarkRevision") != receipt.get("benchmarkRevision"):
        failures.append(
            "prepared stage register was frozen for a different benchmark revision than the "
            "receipt records"
        )
    frozen_stages = register.get("stages") or {}
    if binding.get("stages") != frozen_stages:
        failures.append(
            "prepared stage register does not match the per-stage freeze recorded in the receipt"
        )

    failures.extend(
        validate_frozen_generated_artifacts(generated, frozen_stages)
    )
    return failures


def validate_frozen_generated_artifacts(
    generated: dict[str, dict], frozen_stages: dict,
) -> list[str]:
    """Each generated stage's frozen digest, count, and ordered IDs vs disk."""
    failures: list[str] = []
    for stage, entry in sorted(generated.items()):
        frozen = frozen_stages.get(stage)
        if not isinstance(frozen, dict):
            failures.append(f"prepared stage register does not freeze generated stage {stage!r}")
            continue
        if frozen.get("path") != entry.get("path"):
            failures.append(
                f"stage {stage!r} is frozen at {frozen.get('path')!r} but the stage manifest "
                f"declares {entry.get('path')!r}"
            )
            continue
        filename = str(entry["path"])
        path = HERE / filename
        if not path.is_file():
            failures.append(f"{filename}: missing prepared file for generated stage {stage!r}")
            continue
        try:
            ids = [
                str(json.loads(line)["id"])
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (KeyError, json.JSONDecodeError) as exc:
            failures.append(f"{filename}: cannot read ordered task IDs: {exc}")
            continue
        current_sha = sha256_file(path)
        if frozen.get("artifactSha256") != current_sha:
            failures.append(
                f"{filename}: on-disk digest {current_sha} does not match the prepared freeze "
                f"{frozen.get('artifactSha256')!r} for stage {stage!r}"
            )
        if int(frozen.get("taskCount") or -1) != len(ids):
            failures.append(
                f"{filename}: on-disk task count {len(ids)} does not match the prepared freeze "
                f"{frozen.get('taskCount')!r} for stage {stage!r}"
            )
        if frozen.get("orderedTaskIdsSha256") != ordered_ids_sha256(ids):
            failures.append(
                f"{filename}: on-disk ordered task-ID digest does not match the prepared freeze "
                f"for stage {stage!r}"
            )
        prefix = entry.get("subsetPrefixCount")
        if prefix is None:
            continue
        prefix_count = int(prefix)
        if int(frozen.get("subsetPrefixCount") or -1) != prefix_count:
            failures.append(
                f"stage {stage!r} freeze records prefix size {frozen.get('subsetPrefixCount')!r}, "
                f"not the registered {prefix_count}"
            )
        elif prefix_count > len(ids):
            failures.append(
                f"stage {stage!r} registered prefix of {prefix_count} exceeds the {len(ids)} "
                "prepared tasks"
            )
        elif frozen.get("subsetOrderedTaskIdsSha256") != ordered_ids_sha256(ids[:prefix_count]):
            failures.append(
                f"stage {stage!r} frozen prefix ordered-ID digest does not match the registered "
                "ordered IDs on disk"
            )
    return failures


def validate_data_environment_receipt(data_env: dict) -> list[str]:
    failures: list[str] = []
    if data_env.get("sourceCompilationAllowed") is not False:
        failures.append("data-preparation environment does not explicitly forbid source compilation")
    dependency_lock = data_env.get("dependencyLock") or {}
    lock_name = dependency_lock.get("file") or ""
    if lock_name not in {
        "locks/kaggle-data-prep-cp310-linux-x86_64.txt",
        "locks/kaggle-data-prep-cp311-linux-x86_64.txt",
    }:
        failures.append("preparation receipt points to an unsupported data-preparation lock profile")
        return failures
    lock_file = HERE / lock_name
    digest_file = lock_file.with_suffix(".sha256")
    if not lock_file.is_file() or not digest_file.is_file():
        failures.append("committed data-preparation dependency lock or its digest pin is missing")
        return failures
    actual_lock_sha = sha256_file(lock_file)
    try:
        expected_lock_sha = digest_file.read_text(encoding="ascii").strip().split()[0].lower()
    except (OSError, IndexError):
        expected_lock_sha = ""
    if actual_lock_sha != expected_lock_sha:
        failures.append("committed data-preparation lock does not match its pinned SHA-256")
    if dependency_lock.get("state") != "verified":
        failures.append("preparation receipt does not record a verified dependency lock")
    if dependency_lock.get("sha256") != actual_lock_sha:
        failures.append("preparation receipt dependency-lock SHA-256 does not match the committed lock")
    if dependency_lock.get("packageCount", 0) < 30:
        failures.append("preparation receipt dependency lock omits the resolved package closure")
    install_flags = dependency_lock.get("installFlags") or []
    if not {"--require-hashes", "--only-binary=:all:", "--no-deps"}.issubset(set(install_flags)):
        failures.append("preparation receipt does not prove hash-checked binary-only lock installation")
    if data_env.get("pythonImplementation") != "CPython" or not data_env.get("pythonVersion") or not data_env.get("pythonCacheTag"):
        failures.append("preparation receipt omits the Python implementation/version/ABI identity")
    if not data_env.get("system") or not data_env.get("machine"):
        failures.append("preparation receipt omits the preparation platform identity")
    expected_suffix = "cp310" if data_env.get("pythonVersion", "").startswith("3.10.") else "cp311" if data_env.get("pythonVersion", "").startswith("3.11.") else None
    if expected_suffix is None or expected_suffix not in lock_name:
        failures.append("preparation receipt Python version does not match its wheel lock profile")
    if data_env.get("system") != "Linux" or data_env.get("machine", "").lower() not in {"x86_64", "amd64"}:
        failures.append("preparation receipt platform is not covered by the Kaggle Linux x86_64 wheel lock")
    return failures


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
    failures.extend(validate_data_environment_receipt(data_env))

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

    # The generated stages carry their frozen identity in the prepared register
    # rather than in the receipt's file list, so check it after the file sweep.
    prepared_failures = validate_prepared_stage_register(receipt, args.receipt)
    failures.extend(prepared_failures)

    report = {
        "status": "verified" if not failures else "unqualified",
        "benchmarkRevision": args.benchmark_revision,
        "receipt": str(args.receipt),
        "observed": observed,
        "preparedStageRegister": {
            "verified": not prepared_failures,
            "file": str(find_prepared_register(args.receipt)),
            "stages": sorted(generated_stage_entries()),
        },
        "failures": failures,
    }
    print(json.dumps(report, indent=2))
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
