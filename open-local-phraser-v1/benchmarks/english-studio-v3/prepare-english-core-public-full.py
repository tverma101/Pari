#!/usr/bin/env python3
"""Prepare the full-distribution finalist classification lane and freeze a receipt.

Issue #67. This is the explicit finalist/public-full preparation step. It is
deliberately NOT part of `prepare-kaggle-benchmark.py`:

- the common screen is the balanced 1,943-case artifact assembled from
  public-fast + shadow + SemanticQA LCC. Full-distribution rows must never be
  added to it, so this step neither reads nor writes that screen; and
- this lane is not a Kaggle GPU stage, so it does not touch the stage register.

What it guarantees:
- sources come from the versioned frozen manifest
  (`english-core-public-full-sources.json`), never from ad hoc CLI memory;
- the build runs under `--promotion --lock-sources-to-config`, so a moved or
  drifted source fails closed instead of silently changing the lane;
- the resulting task/answer/manifest files are hashed and the exact ordered
  task-ID digest is frozen into a receipt;
- the locked data-preparation environment identity (#52) is recorded, either
  verified against the committed binary-only hash lock, or explicitly marked
  unverified so an off-Kaggle run can never claim promotion eligibility; and
- the benchmark tree is bound (#40) through the same `verify_git_identity`
  contract the Kaggle runner uses.

Usage:
    python prepare-english-core-public-full.py
    python prepare-english-core-public-full.py --receipt PATH --benchmark-revision SHA
    python prepare-english-core-public-full.py --verify-only --receipt PATH
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from english_core_public_sources import (
    FINALIST_LANE_ID,
    FULL_DISTRIBUTION_SOURCE_NAMES,
    REVISION_RESOLUTION_POLICY,
    SOURCE_CONTRACT_VERSION,
    SOURCE_MANIFEST_FILENAME,
    frozen_source_commits,
    load_frozen_source_manifest,
    sha256_file,
)

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]

RECEIPT_SCHEMA = "pari.english-core.public-full-preparation-receipt"
RECEIPT_VERSION = 1
PROTOCOL_VERSION = f"pari.english-core.public-full-finalist-{SOURCE_CONTRACT_VERSION}"
RECEIPT_FILENAME = "english-core-public-full-classification.preparation.json"

TASK_FILE = HERE / "english-core-public-full-classification.jsonl"
ANSWER_FILE = HERE / "english-core-public-full-classification.answers.json"
MANIFEST_FILE = HERE / "english-core-public-full-classification.manifest.json"

#: The common screen's own artifact. Named here only so the receipt can state
#: the boundary in a machine-checkable way; this script never reads or writes it.
COMMON_SCREEN_ARTIFACT = "english-core-fixed-screen.jsonl"
COMMON_SCREEN_CASES = 1943


def _load_module(name: str, filename: str):
    """Import a hyphenated sibling module the way this repo's tests already do."""
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    if not spec or not spec.loader:
        raise SystemExit(f"cannot import {filename} from {HERE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_builder_command(
    python: str, *, sources_config: Path, sources_lock: bool, promotion: bool
) -> list[str]:
    return [
        python,
        str(HERE / "build-english-core-public-full-classification.py"),
        "--sources-config",
        str(sources_config),
        *(["--lock-sources-to-config"] if sources_lock else []),
        *(["--promotion"] if promotion else []),
    ]


def run_build(
    python: str,
    *,
    sources_config: Path,
    sources_lock: bool,
    promotion: bool,
    log: Path,
) -> None:
    cmd = build_builder_command(
        python, sources_config=sources_config, sources_lock=sources_lock, promotion=promotion
    )
    print("+", " ".join(cmd), flush=True)
    proc = subprocess.run(
        cmd,
        cwd=str(HERE),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(proc.stdout, encoding="utf-8", errors="replace")
    if proc.stdout:
        print(proc.stdout, flush=True)
    if proc.returncode != 0:
        raise SystemExit(f"full-distribution build failed with exit {proc.returncode}; see {log}")


def data_environment_identity(*, required: bool) -> dict[str, Any]:
    """Record the locked data-prep environment identity (#52).

    On the qualified Kaggle profile this verifies the committed binary-only hash
    lock exactly the way `prepare-kaggle-benchmark.py` does. Anywhere else it
    returns an explicitly unverified identity, and the caller refuses to mark
    the receipt promotion-eligible.
    """
    identity: dict[str, Any] = {
        "python": sys.executable,
        "pythonImplementation": platform.python_implementation(),
        "pythonVersion": platform.python_version(),
        "pythonCacheTag": sys.implementation.cache_tag,
        "machine": platform.machine(),
        "system": platform.system(),
        "sourceCompilationAllowed": False,
    }
    for module_name in ("datasets", "huggingface_hub"):
        try:
            module = __import__(module_name)
        except ImportError:
            identity[module_name + "Version"] = None
        else:
            identity[module_name + "Version"] = getattr(module, "__version__", None)

    version = platform.python_version().split(".")
    tag = f"cp{version[0]}{version[1]}-linux-x86_64"
    lock_file = HERE / "locks" / f"kaggle-data-prep-{tag}.txt"
    digest_file = HERE / "locks" / f"kaggle-data-prep-{tag}.sha256"
    identity["dependencyLock"] = {
        "directory": "locks",
        "profile": tag,
        "file": lock_file.name if lock_file.is_file() else None,
        "sha256": None,
        "state": "unavailable",
        "resolver": "uv 0.12.5 CPython-minor/Linux-x86_64 resolution; pinned versions and PyPI artifact SHA-256 hashes",
        "installFlags": ["--require-hashes", "--only-binary=:all:", "--no-deps"],
    }
    if not (lock_file.is_file() and digest_file.is_file()):
        if required:
            raise SystemExit(
                "locked data-preparation hash lock is missing for this profile; "
                "the finalist lane cannot be prepared outside the qualified profile"
            )
        return identity

    identity["dependencyLock"]["sha256"] = sha256_file(lock_file)

    try:
        prep = _load_module("prepare_kaggle_benchmark", "prepare-kaggle-benchmark.py")
        actual, pins = prep.verify_data_prep_lock(lock_file, digest_file)
    except SystemExit as exc:
        if required:
            raise
        identity["dependencyLock"]["state"] = "rejected"
        identity["dependencyLock"]["reason"] = str(exc)
        return identity
    identity["dependencyLock"].update(
        {
            "state": "verified",
            "sha256": actual,
            "packageCount": len(pins),
            "pins": {name: version for name, version in pins},
        }
    )
    return identity


def current_git_head(repo_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(repo_root), text=True, stderr=subprocess.STDOUT
        ).strip()
    except Exception:
        return ""


def benchmark_tree_binding(repo_root: Path, *, require_clean: bool) -> dict[str, Any]:
    """Bind the checkout identity exactly the way the Kaggle runner does (#40)."""
    checkpoint = _load_module("kaggle_run_checkpoint", "kaggle_run_checkpoint.py")
    identity = checkpoint.verify_git_identity(
        repo_root, current_git_head(repo_root), require_clean=require_clean
    )
    return {
        "repoRoot": str(repo_root),
        "head": identity.head,
        "tree": identity.tree,
        "branch": identity.branch,
        "relevantPrefix": identity.relevant_prefix,
        "promotionEligible": identity.promotion_eligible,
        "statusPorcelain": list(identity.status_porcelain),
        "relevantStatusPorcelain": list(identity.relevant_status_porcelain),
    }


def ordered_ids_sha256(ids: list[str]) -> str:
    """The canonical ordered-task-ID digest shared with the prepared stage register."""
    payload = json.dumps(
        {"orderedTaskIds": list(ids)}, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def read_task_ids(path: Path) -> list[str]:
    ids: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        task_id = row.get("id")
        if not task_id:
            raise SystemExit(f"task without ID in {path}")
        ids.append(str(task_id))
    if len(ids) != len(set(ids)):
        raise SystemExit(f"duplicate task IDs in {path}")
    return ids


def verify_outputs(sources_config: dict) -> dict[str, Any]:
    """Check the built lane against the frozen contract and hash its bytes."""
    for path in (TASK_FILE, ANSWER_FILE, MANIFEST_FILE):
        if not path.is_file():
            raise SystemExit(f"prepared full-distribution artifact is missing: {path}")
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    answers = json.loads(ANSWER_FILE.read_text(encoding="utf-8"))
    ids = read_task_ids(TASK_FILE)

    if int(manifest.get("cases", -1)) != len(ids):
        raise SystemExit("manifest case count does not match the prepared task file")
    if set(answers.get("answers", {})) != set(ids):
        raise SystemExit("prepared answer keys do not exactly match the prepared task IDs")
    if manifest.get("lane") != FINALIST_LANE_ID:
        raise SystemExit(f"prepared manifest is not the {FINALIST_LANE_ID!r} lane")
    if not manifest.get("promotionEligible"):
        raise SystemExit(
            "prepared manifest is not promotion-eligible: "
            + json.dumps((manifest.get("promotion") or {}).get("gateErrors", []))
        )
    if manifest.get("revisionPolicy") is None or manifest.get("resolvedDatasetFingerprints") is None:
        raise SystemExit("prepared manifest lacks source revision/fingerprint provenance")

    sources = manifest.get("sources") or {}
    frozen = frozen_source_commits(sources_config)
    drift = {
        name: (frozen[name], (sources.get(name) or {}).get("resolvedRevision"))
        for name in FULL_DISTRIBUTION_SOURCE_NAMES
        if frozen[name] != (sources.get(name) or {}).get("resolvedRevision")
    }
    if drift:
        raise SystemExit(f"prepared manifest source drift: {drift}")

    expected_total = sources_config.get("expectedTotalCases")
    if expected_total is not None and len(ids) != int(expected_total):
        raise SystemExit(f"expected {expected_total} prepared cases, found {len(ids)}")
    for name in FULL_DISTRIBUTION_SOURCE_NAMES:
        expected = sources_config["sources"][name].get("expectedValidationRows")
        if expected is None:
            continue
        actual = sum(1 for task_id in ids if task_id.startswith(f"full-{name.lower()}-"))
        if actual != int(expected):
            raise SystemExit(f"{name}: expected {expected} prepared rows, found {actual}")

    if COMMON_SCREEN_ARTIFACT in {TASK_FILE.name, ANSWER_FILE.name, MANIFEST_FILE.name}:
        raise SystemExit("finalist preparation must not write the common screen artifact")

    return {
        "cases": len(ids),
        "countsBySource": manifest.get("countsBySource"),
        "files": {
            TASK_FILE.name: {
                "sha256": sha256_file(TASK_FILE),
                "bytes": TASK_FILE.stat().st_size,
                "cases": len(ids),
            },
            ANSWER_FILE.name: {
                "sha256": sha256_file(ANSWER_FILE),
                "bytes": ANSWER_FILE.stat().st_size,
            },
            MANIFEST_FILE.name: {
                "sha256": sha256_file(MANIFEST_FILE),
                "bytes": MANIFEST_FILE.stat().st_size,
            },
        },
        "orderedTaskIdsSha256": ordered_ids_sha256(ids),
        "manifestSources": sources,
        "resolvedDatasetFingerprints": manifest.get("resolvedDatasetFingerprints"),
        "manifestSha256": sha256_file(MANIFEST_FILE),
    }


def write_receipt(receipt_path: Path, receipt: dict[str, Any]) -> str:
    payload = (json.dumps(receipt, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{receipt_path.name}.", dir=receipt_path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, receipt_path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return hashlib.sha256(payload).hexdigest()


def verify_receipt(receipt_path: Path, *, benchmark_revision: str | None) -> dict[str, Any]:
    """Independently re-check a previously written receipt against the tree."""
    failures: list[str] = []
    if not receipt_path.is_file():
        return {
            "status": "unqualified",
            "receipt": str(receipt_path),
            "failures": ["receipt is missing"],
        }
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("version") != RECEIPT_VERSION:
        failures.append("receipt schema/version is not the expected finalist preparation contract")
    if receipt.get("protocolVersion") != PROTOCOL_VERSION:
        failures.append(
            f"receipt protocolVersion {receipt.get('protocolVersion')!r} is not {PROTOCOL_VERSION!r}"
        )
    if not receipt.get("promotionEligible"):
        failures.append("receipt is not promotion-eligible")
    if receipt.get("sourceContractVersion") != SOURCE_CONTRACT_VERSION:
        failures.append("receipt source contract version is not understood by this verifier")
    if benchmark_revision and receipt.get("benchmarkRevision") != benchmark_revision:
        failures.append("receipt benchmark revision does not match the declared revision")
    lock = (receipt.get("isolatedDataEnvironment") or {}).get("dependencyLock") or {}
    if not lock.get("sha256") or lock.get("state") != "verified":
        failures.append("receipt does not bind a verified data-preparation lock")

    for name, entry in (receipt.get("files") or {}).items():
        path = HERE / name
        if not path.is_file():
            failures.append(f"prepared file {name} is missing from the benchmark tree")
            continue
        if sha256_file(path) != entry.get("sha256"):
            failures.append(f"prepared file {name} does not match the receipt hash")
    tree = receipt.get("benchmarkTree") or {}
    if benchmark_revision and tree.get("head") != benchmark_revision:
        failures.append("receipt benchmark tree head does not match the declared revision")
    if (receipt.get("laneSeparation") or {}).get("commonScreenArtifact") != COMMON_SCREEN_ARTIFACT:
        failures.append("receipt does not declare the common-screen boundary")
    return {
        "status": "verified" if not failures else "unqualified",
        "receipt": str(receipt_path),
        "receiptSha256": sha256_file(receipt_path),
        "failures": failures,
    }


def build_receipt(
    *,
    sources_config: dict,
    sources_config_path: Path,
    outputs: dict[str, Any],
    tree: dict[str, Any],
    env_identity: dict[str, Any],
    promotion: bool,
    blockers: list[str],
) -> dict[str, Any]:
    return {
        "schema": RECEIPT_SCHEMA,
        "version": RECEIPT_VERSION,
        "protocolVersion": PROTOCOL_VERSION,
        "sourceContractVersion": SOURCE_CONTRACT_VERSION,
        "revisionResolutionPolicy": REVISION_RESOLUTION_POLICY,
        "purpose": "frozen preparation receipt for the full-distribution prompted WiC/CoLA/PAWS finalist lane",
        "timestampUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "lane": FINALIST_LANE_ID,
        "benchmarkRevision": tree.get("head"),
        "benchmarkTree": tree,
        "isolatedDataEnvironment": env_identity,
        "frozenSources": {
            "file": sources_config_path.name,
            "sha256": sha256_file(sources_config_path),
            "sources": {
                name: {
                    "dataset": sources_config["sources"][name]["dataset"],
                    "config": sources_config["sources"][name]["config"],
                    "split": sources_config["sources"][name]["split"],
                    "resolvedRevision": sources_config["sources"][name]["resolvedRevision"],
                }
                for name in FULL_DISTRIBUTION_SOURCE_NAMES
            },
        },
        "cases": outputs["cases"],
        "countsBySource": outputs["countsBySource"],
        "orderedTaskIdsSha256": outputs["orderedTaskIdsSha256"],
        "files": outputs["files"],
        "manifestSha256": outputs["manifestSha256"],
        "manifestSources": outputs["manifestSources"],
        "resolvedDatasetFingerprints": outputs["resolvedDatasetFingerprints"],
        "laneSeparation": {
            "commonScreenArtifact": COMMON_SCREEN_ARTIFACT,
            "commonScreenCases": COMMON_SCREEN_CASES,
            "rule": (
                "This lane is prepared and receipted separately from the balanced "
                "1,943-case common screen. No full-distribution row is added to that "
                "screen, and prepare-kaggle-benchmark.py does not build this lane."
            ),
        },
        "promotionEligible": bool(promotion and not blockers),
        "promotionBlockers": blockers,
        "scorerContract": {
            "manifestField": "promotionEligible",
            "requiredWhenFlagged": "--promotion",
            "note": (
                "A scorer given --promotion must refuse a manifest whose "
                "promotionEligible is false, whose sources lack a full resolvedRevision "
                "with revisionResolution=hf-api-dataset-info-sha-once, or whose repo "
                "IDs/configs/splits differ from the canonical identities. A task-file "
                "hash match alone must never upgrade a non-promotion build."
            ),
        },
        "rules": [
            "No model weights are downloaded and no GPU is required or inspected.",
            "Sources are read only at the frozen commits recorded in the versioned source manifest.",
            "The build runs with --promotion --lock-sources-to-config unless --exploratory is passed.",
            "Task, answer, and manifest bytes are hashed here; the ordered task-ID digest matches the prepared stage register convention.",
            "The common 1,943-case screen is never written or extended by this step.",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources-config", type=Path, default=HERE / SOURCE_MANIFEST_FILENAME)
    ap.add_argument("--receipt", type=Path, default=HERE / RECEIPT_FILENAME)
    ap.add_argument("--work-root", type=Path, default=None, help="Where build logs are written.")
    ap.add_argument("--benchmark-revision", default=None, help="Expected checkout revision.")
    ap.add_argument("--verify-only", action="store_true", help="Verify an existing receipt without rebuilding.")
    ap.add_argument(
        "--allow-unlocked-environment",
        action="store_true",
        help="Prepare off the qualified Kaggle profile; the receipt is never promotion-eligible.",
    )
    ap.add_argument("--allow-dirty-tree", action="store_true", help="Bind the tree without requiring it clean.")
    ap.add_argument("--exploratory", action="store_true", help="Build without promotion gating.")
    args = ap.parse_args()

    if args.verify_only:
        report = verify_receipt(args.receipt, benchmark_revision=args.benchmark_revision)
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if report["status"] == "verified" else 2)

    sources_config = load_frozen_source_manifest(args.sources_config)
    promotion = not args.exploratory
    env_identity = data_environment_identity(required=not args.allow_unlocked_environment)
    tree = benchmark_tree_binding(REPO_ROOT, require_clean=not args.allow_dirty_tree)

    work_root = args.work_root or (HERE / ".finalist-prep-work")
    run_build(
        sys.executable,
        sources_config=args.sources_config,
        sources_lock=True,
        promotion=promotion,
        log=work_root / "full-distribution-build.log.txt",
    )
    outputs = verify_outputs(sources_config)

    env_verified = (env_identity.get("dependencyLock") or {}).get("state") == "verified"
    blockers: list[str] = []
    if promotion and not env_verified:
        blockers.append("data-preparation environment lock is not verified for this profile")
    if promotion and not tree.get("promotionEligible"):
        blockers.append("benchmark tree is not clean under the runner's git identity contract")
    if promotion and args.benchmark_revision and tree.get("head") != args.benchmark_revision:
        blockers.append("checkout revision does not match --benchmark-revision")

    receipt = build_receipt(
        sources_config=sources_config,
        sources_config_path=args.sources_config,
        outputs=outputs,
        tree=tree,
        env_identity=env_identity,
        promotion=promotion,
        blockers=blockers,
    )
    receipt_sha = write_receipt(args.receipt, receipt)
    print(
        json.dumps(
            {
                "status": "prepared",
                "receipt": str(args.receipt),
                "receiptSha256": receipt_sha,
                "cases": outputs["cases"],
                "promotionEligible": receipt["promotionEligible"],
                "promotionBlockers": blockers,
                "orderedTaskIdsSha256": outputs["orderedTaskIdsSha256"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
