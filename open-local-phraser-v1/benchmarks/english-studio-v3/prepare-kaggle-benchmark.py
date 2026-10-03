#!/usr/bin/env python3
"""Prepare every generated Pari benchmark task file before Kaggle GPU work.

This is a CPU/data-preparation stage. It does not import vLLM, download model
weights, or require a GPU. Public-dataset dependencies live in a dedicated venv
and are installed from binary wheels only so benchmark preparation cannot trigger
native compilation or mutate the later inference runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

SEMANTICQA_REPO = "https://github.com/jacklanda/SemanticQA.git"
SEMANTICQA_COMMIT = "56c82a587f4a6cef609255cd10af372d8c76600a"
DATASETS_VERSION = "5.0.1"
DATA_PREP_LOCK_DIR = HERE / "locks"
PUBLIC_REVISIONS = {
    "blimp": "877fba0801ffb7cbd8c39c1ff314a46f053f6036",
    "super_glue": "3de24cf8022e94f4ee4b9d55a6f539891524d646",
    "glue": "bcdcba79d07bc864c1c254ccfcedcce55bcc9a8c",
    "paws": "161ece9501cf0a11f3e48bd356eaa82de46d6a09",
}

EXPECTED = {
    "kaggle-protocol-smoke.jsonl": 16,
    "english-core-shadow.jsonl": 68,
    "english-core-public-fast.jsonl": 1570,
    "semanticqa-lcc-english-core.jsonl": 305,
    "english-core-fixed-screen.jsonl": 1943,
    "word-studio-transform.jsonl": 100,
    "word-studio-strength.jsonl": 112,
}

#: The frozen stage register and the stage manifest it is bound to. Both are data
#: read by kaggle_stage_identity.py, so a generated screen becomes promotion-valid
#: only when preparation has frozen its exact bytes, count, and ordered task IDs
#: into the register, and the register is bound to this exact stage manifest.
#:
#: The register is written into the benchmark tree on purpose so the candidate
#: bundle's whole-directory copy lands it next to the checked-in stage manifest
#: where kaggle_stage_identity.py resolves a generated stage. That makes it an
#: untracked generated input under the clean-tree policy in kaggle_run_checkpoint.py,
#: so it also needs the same receipt-gated allowance the other prepared task inputs
#: get (see PREPARED_TASK_INPUT_NAMES there); resolution itself fails closed here
#: without a matching preparation receipt, so the allowance is the only piece this
#: file cannot own.
STAGE_MANIFEST = HERE / "kaggle-stage-manifest.json"
PREPARED_STAGE_REGISTER = HERE / "kaggle-stage-manifest.prepared.json"
PREPARED_STAGE_REGISTER_KEY = "preparedStageRegister"

#: Stages whose task files are generated here rather than committed, so their
#: identity is frozen here instead of in the checked-in stage manifest. Each entry
#: names the artifact plus, for a registered frozen prefix, the prefix size whose
#: ordered task-ID digest is frozen alongside the full-screen digest.
PREPARED_STAGES: dict[str, dict[str, int | str]] = {
    "full": {"path": "english-core-fixed-screen.jsonl"},
    "benchmark-smoke": {
        "path": "english-core-fixed-screen.jsonl",
        "subsetPrefixCount": 64,
    },
}

#: Ordered-task-ID digest convention shared with kaggle_stage_identity.py: the same
#: canonical JSON shape, so a digest frozen here is directly comparable.
def ordered_ids_sha256(ids: list[str]) -> str:
    payload = json.dumps({"orderedTaskIds": list(ids)}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ordered_task_ids(path: Path) -> list[str]:
    """Ordered task IDs of one model-visible task file, uniqueness-checked."""
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

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, log: Path | None = None) -> str:
    print("+", " ".join(cmd), flush=True)
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(proc.stdout, encoding="utf-8", errors="replace")
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n", flush=True)
    if proc.returncode != 0:
        raise SystemExit(f"command failed rc={proc.returncode}: {' '.join(cmd)}")
    return proc.stdout


def git_text(checkout: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=checkout, text=True, stderr=subprocess.STDOUT).strip()


def prepare_semanticqa(checkout: Path, logs: Path) -> dict[str, Any]:
    checkout.parent.mkdir(parents=True, exist_ok=True)
    reuse = False
    if checkout.is_dir() and (checkout / ".git").is_dir():
        try:
            head = git_text(checkout, "rev-parse", "HEAD").lower()
            dirty = bool(git_text(checkout, "status", "--porcelain"))
            reuse = head == SEMANTICQA_COMMIT and not dirty
        except Exception:
            reuse = False
    if not reuse:
        if checkout.exists():
            shutil.rmtree(checkout)
        checkout.mkdir(parents=True)
        run(["git", "init"], cwd=checkout, log=logs / "semanticqa-git-init.log.txt")
        run(["git", "remote", "add", "origin", SEMANTICQA_REPO], cwd=checkout, log=logs / "semanticqa-git-remote.log.txt")
        run(
            ["git", "fetch", "--depth", "1", "origin", SEMANTICQA_COMMIT],
            cwd=checkout,
            log=logs / "semanticqa-git-fetch.log.txt",
        )
        run(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=checkout, log=logs / "semanticqa-git-checkout.log.txt")

    head = git_text(checkout, "rev-parse", "HEAD").lower()
    dirty = bool(git_text(checkout, "status", "--porcelain"))
    if head != SEMANTICQA_COMMIT or dirty:
        raise SystemExit(f"SemanticQA checkout is not exact/clean: head={head} dirty={dirty}")
    required = [
        checkout / "resources/dataset.zip",
        checkout / "semantic_qa/prompts/collocation_categorization_zeroshot.txt",
        checkout / "semantic_qa/taxonomy/SEM_REL_CATEGORY_8_0-shots.txt",
    ]
    missing = [str(p) for p in required if not p.is_file()]
    if missing:
        raise SystemExit(f"SemanticQA pinned checkout is missing required assets: {missing}")
    return {
        "repository": SEMANTICQA_REPO,
        "commit": head,
        "checkout": str(checkout),
        "reusedExistingCleanCheckout": reuse,
        "datasetZipSha256": sha256_file(checkout / "resources/dataset.zip"),
    }


def data_environment() -> dict[str, str]:
    """Avoid host-site import shadowing and ambient pip policy in prep commands."""
    env = os.environ.copy()
    for key in list(env):
        if key == "PYTHONPATH" or key == "PYTHONHOME" or key.startswith("PIP_"):
            env.pop(key, None)
    env.update({"PYTHONNOUSERSITE": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"})
    return env


def data_prep_lock_paths(
    *, system: str | None = None, machine: str | None = None,
    python_version: tuple[int, int] | None = None, implementation: str | None = None,
) -> tuple[Path, Path]:
    system = system or platform.system()
    machine = machine or platform.machine()
    python_version = python_version or (sys.version_info.major, sys.version_info.minor)
    implementation = implementation or platform.python_implementation()
    if implementation != "CPython":
        raise SystemExit(f"no data-preparation wheel lock for {implementation}; only CPython profiles are qualified")
    if system != "Linux" or machine.lower() not in {"x86_64", "amd64"}:
        raise SystemExit(f"no data-preparation wheel lock for {system}/{machine}; only Kaggle Linux x86_64 is qualified")
    version = f"{python_version[0]}.{python_version[1]}"
    if version not in {"3.10", "3.11"}:
        raise SystemExit(f"no data-preparation wheel lock for CPython {version}; supported profiles are CPython 3.10 and 3.11")
    tag = f"cp{python_version[0]}{python_version[1]}-linux-x86_64"
    lock_file = DATA_PREP_LOCK_DIR / f"kaggle-data-prep-{tag}.txt"
    digest_file = DATA_PREP_LOCK_DIR / f"kaggle-data-prep-{tag}.sha256"
    return lock_file, digest_file


def verify_data_prep_lock(
    lock_file: Path | None = None, digest_file: Path | None = None,
) -> tuple[str, list[tuple[str, str]]]:
    """Verify the committed hash lock and return its exact package pins."""
    if lock_file is None and digest_file is None:
        lock_file, digest_file = data_prep_lock_paths()
    elif lock_file is None or digest_file is None:
        raise SystemExit("both data-preparation lock and digest paths must be provided together")
    if not lock_file.is_file() or not digest_file.is_file():
        raise SystemExit("data-preparation hash lock or its SHA-256 pin is missing")
    try:
        expected = digest_file.read_text(encoding="ascii").strip().split()[0].lower()
    except (OSError, IndexError) as exc:
        raise SystemExit("data-preparation lock SHA-256 pin is missing or empty") from exc
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise SystemExit("data-preparation lock SHA-256 pin is malformed")
    actual = sha256_file(lock_file)
    if actual != expected:
        raise SystemExit(f"data-preparation lock SHA-256 mismatch: expected {expected}, got {actual}")
    try:
        from pip._vendor.packaging.requirements import Requirement
    except ImportError as exc:
        raise SystemExit(f"base Python pip lacks its requirements parser: {exc}") from exc
    lines = lock_file.read_text(encoding="utf-8").splitlines()
    stanzas: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace():
            if current:
                stanzas.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        stanzas.append(current)
    pins: list[tuple[str, str]] = []
    for stanza in stanzas:
        requirement_text = stanza[0].strip().removesuffix("\\").strip()
        try:
            requirement = Requirement(requirement_text)
        except Exception as exc:
            raise SystemExit(f"invalid data-preparation lock requirement {requirement_text!r}: {exc}") from exc
        hashes = re.findall(r"--hash=sha256:([0-9a-f]{64})", "\n".join(stanza))
        if not hashes:
            raise SystemExit(f"data-preparation lock requirement lacks an artifact SHA-256: {requirement_text}")
        if requirement.marker is None or requirement.marker.evaluate():
            if len(requirement.specifier) != 1 or not str(requirement.specifier).startswith("=="):
                raise SystemExit(f"data-preparation package is not exactly pinned: {requirement_text}")
            pins.append((re.sub(r"[-_.]+", "-", requirement.name).lower(), str(requirement.specifier)[2:]))
    if not pins or len({name for name, _ in pins}) != len(pins):
        raise SystemExit("data-preparation lock has no pins or duplicate package names")
    if ("datasets", DATASETS_VERSION) not in pins:
        raise SystemExit("data-preparation lock does not pin the required datasets version")
    return actual, pins


def package_lock_drift(installed: dict[str, str], pins: list[tuple[str, str]]) -> list[tuple[str, str | None, str | None]]:
    expected = dict(pins)
    drift = [
        (name, version, installed.get(name))
        for name, version in pins
        if installed.get(name) != version
    ]
    allowed_bootstrap = {"pip", "setuptools", "wheel"}
    drift.extend((name, None, installed[name]) for name in sorted(set(installed) - set(expected) - allowed_bootstrap))
    return drift


def ensure_data_venv(path: Path, logs: Path) -> dict[str, Any]:
    lock_file, digest_file = data_prep_lock_paths()
    lock_sha256, lock_pins = verify_data_prep_lock(lock_file, digest_file)
    python = path / "bin/python"
    env = data_environment()
    recreate = False
    if python.is_file():
        probe = subprocess.run(
            [str(python), "-m", "pip", "list", "--format=json"],
            env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        try:
            installed = {
                re.sub(r"[-_.]+", "-", row["name"]).lower(): row["version"]
                for row in json.loads(probe.stdout)
            } if probe.returncode == 0 else {}
        except (ValueError, KeyError, TypeError):
            installed = {}
        if package_lock_drift(installed, lock_pins):
            recreate = True
    else:
        recreate = True

    if recreate:
        if path.exists():
            shutil.rmtree(path)
        print(f"creating isolated data-prep venv: {path}", flush=True)
        run(
            [sys.executable, "-m", "venv", "--clear", str(path)],
            env=env,
            log=logs / "data-venv-create.log.txt",
        )
        run(
            [
                str(python), "-m", "pip", "--isolated", "install",
                "--require-hashes", "--only-binary=:all:", "--no-deps",
                "--requirement", str(lock_file),
            ],
            env=env,
            log=logs / "data-venv-install.log.txt",
        )

    probe = run(
        [str(python), "-m", "pip", "list", "--format=json"],
        env=env,
        log=logs / "data-venv-version.log.txt",
    )
    installed = {
        re.sub(r"[-_.]+", "-", row["name"]).lower(): row["version"]
        for row in json.loads(probe)
    }
    drift = package_lock_drift(installed, lock_pins)
    if drift:
        raise SystemExit(f"isolated data venv differs from the verified package lock: {drift}")
    run([str(python), "-m", "pip", "check"], env=env, log=logs / "data-venv-check.log.txt")
    versions = run(
        [str(python), "-c", "import datasets, huggingface_hub; print(datasets.__version__); print(huggingface_hub.__version__)"],
        env=env,
        log=logs / "data-venv-imports.log.txt",
    ).strip().splitlines()
    if not versions or versions[0] != DATASETS_VERSION:
        raise SystemExit(f"isolated data venv has unexpected datasets version: {versions}")
    pip_version = installed.get("pip")
    return {
        "python": str(python),
        "pythonImplementation": platform.python_implementation(),
        "pythonVersion": platform.python_version(),
        "pythonCacheTag": sys.implementation.cache_tag,
        "machine": platform.machine(),
        "system": platform.system(),
        "pipVersion": pip_version,
        "datasetsVersion": versions[0],
        "huggingfaceHubVersion": versions[1] if len(versions) > 1 else None,
        "dependencyLock": {
            "state": "verified",
            "file": str(lock_file.relative_to(HERE)),
            "sha256": lock_sha256,
            "packageCount": len(lock_pins),
            "resolver": "uv 0.12.5 CPython-minor/Linux-x86_64 resolution; pinned versions and PyPI artifact SHA-256 hashes",
            "installFlags": ["--require-hashes", "--only-binary=:all:", "--no-deps"],
        },
        "installedPackageCount": len(installed),
        "sourceCompilationAllowed": False,
    }


def jsonl_count(path: Path) -> int:
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
    return len(ids)


def declared_subset_prefix_counts() -> dict[str, int]:
    """The registered frozen-prefix size per stage, read from the stage manifest."""
    payload = json.loads(STAGE_MANIFEST.read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    for stage, entry in payload.get("stages", {}).items():
        if entry.get("subsetPrefixCount") is not None:
            counts[str(stage)] = int(entry["subsetPrefixCount"])
    return counts


def freeze_prepared_stage_identity(files: dict[str, Any]) -> dict[str, Any]:
    """Freeze the generated stages' exact identity into the prepared register.

    For each generated stage this records the artifact SHA-256, task count, and
    ordered task-ID SHA-256, plus the registered frozen-prefix ordered-ID SHA-256
    for a prefix stage. Only model-visible task files are read; no gold answer key
    is opened, hashed, or emitted.
    """
    stage_manifest_sha = sha256_file(STAGE_MANIFEST)
    if not stage_manifest_sha:
        raise SystemExit(f"stage manifest is missing: {STAGE_MANIFEST}")
    stage_manifest = json.loads(STAGE_MANIFEST.read_text(encoding="utf-8"))
    declared_prefixes = declared_subset_prefix_counts()
    stages: dict[str, Any] = {}
    for stage, spec in PREPARED_STAGES.items():
        filename = str(spec["path"])
        prepared = files.get(filename)
        if prepared is None:
            raise SystemExit(f"prepared file {filename} is absent from the verified output set")
        path = HERE / filename
        ids = ordered_task_ids(path)
        # The task count is never restated here: EXPECTED already owns it, and
        # verify_outputs() checked every file against that same table.
        expected = int(EXPECTED[filename])
        if len(ids) != expected or int(prepared["cases"]) != expected:
            raise SystemExit(
                f"{stage}: {filename} must hold exactly {expected} ordered tasks; "
                f"verified {prepared['cases']}, read {len(ids)}"
            )
        entry: dict[str, Any] = {
            "path": filename,
            "gate": (stage_manifest.get("stages", {}).get(stage) or {}).get("gate"),
            "taskCount": len(ids),
            "artifactSha256": prepared["sha256"],
            "orderedTaskIdsSha256": ordered_ids_sha256(ids),
            "artifactBytes": prepared["bytes"],
        }
        prefix = spec.get("subsetPrefixCount")
        if prefix is not None:
            prefix_count = int(prefix)
            declared = declared_prefixes.get(stage)
            if declared is None:
                raise SystemExit(
                    f"stage manifest declares no subsetPrefixCount for {stage!r}, so its "
                    "frozen prefix cannot be recorded"
                )
            if declared != prefix_count:
                raise SystemExit(
                    f"{stage}: stage manifest registers a {declared}-case prefix, but "
                    f"preparation would freeze {prefix_count}; refusing to diverge"
                )
            if prefix_count > len(ids):
                raise SystemExit(
                    f"{stage}: registered prefix of {prefix_count} exceeds the {len(ids)} "
                    "prepared tasks"
                )
            entry["subsetPrefixCount"] = prefix_count
            entry["subsetOrderedTaskIdsSha256"] = ordered_ids_sha256(ids[:prefix_count])
        stages[stage] = entry
    return {
        "version": 1,
        "preparedBy": "prepare-kaggle-benchmark.py",
        "purpose": (
            "frozen identity for generated benchmark stages; written after the "
            "deterministic build so the exact prepared bytes, count, and ordered task "
            "IDs a promotion run consumes are cryptographically bound to the "
            "checked-in stage manifest"
        ),
        "stageManifestFile": STAGE_MANIFEST.name,
        "stageManifestSha256": stage_manifest_sha,
        "goldPolicy": (
            "only model-visible task JSONL files are read and hashed; answer keys stay "
            "in lane-specific files and are never read, hashed, or written here"
        ),
        "stages": stages,
    }


def write_prepared_stage_register(register: dict[str, Any]) -> str:
    """Write the prepared register atomically and return its SHA-256."""
    payload = (json.dumps(register, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{PREPARED_STAGE_REGISTER.name}.", dir=HERE)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, PREPARED_STAGE_REGISTER)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return hashlib.sha256(payload).hexdigest()


def verify_outputs() -> dict[str, Any]:
    files: dict[str, Any] = {}
    for filename, expected in EXPECTED.items():
        path = HERE / filename
        if not path.is_file():
            raise SystemExit(f"missing prepared benchmark file: {path}")
        actual = jsonl_count(path)
        if actual != expected:
            raise SystemExit(f"{filename}: expected {expected} tasks, got {actual}")
        files[filename] = {
            "cases": actual,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
    return files


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-root", type=Path, default=Path("/kaggle/working/pari-benchmark-prep"))
    ap.add_argument("--receipt", type=Path, default=Path("/kaggle/working/results/benchmark-preparation.json"))
    args = ap.parse_args()

    args.work_root.mkdir(parents=True, exist_ok=True)
    logs = args.work_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    semanticqa = prepare_semanticqa(args.work_root / "sources" / "SemanticQA", logs)
    data_env = ensure_data_venv(args.work_root / "data-env", logs)
    data_python = data_env["python"]

    # Fresh shadow lane from the tracked private seed.
    run(["node", str(HERE / "build-english-core.mjs")], cwd=HERE, env=data_environment(), log=logs / "shadow-build.log.txt")

    # Deterministic public-fast screen from immutable Hub dataset commits.
    run(
        [
            data_python, str(HERE / "build-english-core-public-fast.py"),
            "--blimp-revision", PUBLIC_REVISIONS["blimp"],
            "--super-glue-revision", PUBLIC_REVISIONS["super_glue"],
            "--glue-revision", PUBLIC_REVISIONS["glue"],
            "--paws-revision", PUBLIC_REVISIONS["paws"],
        ],
        cwd=HERE,
        env=data_environment(),
        log=logs / "public-fast-build.log.txt",
    )

    # Official SemanticQA LCC assets from the exact clean Git commit.
    run(
        [
            sys.executable, str(HERE / "build-semanticqa-lcc-english-core.py"),
            "--semanticqa-checkout", semanticqa["checkout"],
            "--promotion",
        ],
        cwd=HERE,
        env=data_environment(),
        log=logs / "semanticqa-build.log.txt",
    )

    # Assemble model-visible common screen; builder never opens lane answer keys.
    run([sys.executable, str(HERE / "build-english-core-fixed-screen.py")], cwd=HERE, env=data_environment(), log=logs / "fixed-screen-build.log.txt")

    # Product suites are also generated before GPU work.
    run([sys.executable, str(HERE / "build-word-studio-transform-suite.py")], cwd=HERE, env=data_environment(), log=logs / "transform-build.log.txt")
    run(
        [
            sys.executable, str(HERE / "build-word-studio-strength-suite.py"),
            "--synthetic-seed", str(HERE / "word-studio-synthetic.seed.json"),
        ],
        cwd=HERE,
        env=data_environment(),
        log=logs / "strength-build.log.txt",
    )

    files = verify_outputs()
    execution_manifest = json.loads((HERE / "kaggle-execution-manifest.json").read_text(encoding="utf-8"))
    if execution_manifest.get("expectedNormalDecodeTaskExecutionsIncludingSmoke") != 2171:
        raise SystemExit("kaggle-execution-manifest.json has unexpected total task contract")

    try:
        benchmark_revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=HERE, text=True, stderr=subprocess.STDOUT
        ).strip()
    except Exception:
        benchmark_revision = None

    # Freeze the generated stages' identity now that the build is byte-stable.
    # This is the handoff that lets a promotion run prove which exact screen bytes,
    # count, and ordered task IDs it consumes; without it a generated stage stays
    # unresolved and fails closed.
    prepared_register = freeze_prepared_stage_identity(files)
    register_bytes = (json.dumps(prepared_register, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    register_sha256 = hashlib.sha256(register_bytes).hexdigest()
    written_sha256 = write_prepared_stage_register(prepared_register)
    if written_sha256 != register_sha256:
        raise SystemExit("prepared stage register digest changed between hashing and writing")
    register_copy = args.receipt.parent / PREPARED_STAGE_REGISTER.name
    register_copy.parent.mkdir(parents=True, exist_ok=True)
    if args.receipt.parent.resolve() != HERE.resolve():
        register_copy.write_bytes(register_bytes)
    frozen_stages = {
        stage: {
            "path": entry["path"],
            "gate": entry["gate"],
            "taskCount": entry["taskCount"],
            "artifactSha256": entry["artifactSha256"],
            "artifactBytes": entry["artifactBytes"],
            "orderedTaskIdsSha256": entry["orderedTaskIdsSha256"],
            **(
                {
                    "subsetPrefixCount": entry["subsetPrefixCount"],
                    "subsetOrderedTaskIdsSha256": entry["subsetOrderedTaskIdsSha256"],
                }
                if "subsetOrderedTaskIdsSha256" in entry
                else {}
            ),
        }
        for stage, entry in prepared_register["stages"].items()
    }

    receipt = {
        "version": 1,
        "purpose": "CPU-only preparation of frozen Pari English Core and Word Studio task files before GPU/model execution",
        "timestampUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "benchmarkRevision": benchmark_revision,
        "publicDatasetRevisions": PUBLIC_REVISIONS,
        "semanticQA": semanticqa,
        "isolatedDataEnvironment": data_env,
        "files": files,
        PREPARED_STAGE_REGISTER_KEY: {
            "file": PREPARED_STAGE_REGISTER.name,
            "fileSha256": register_sha256,
            "writtenTo": str(PREPARED_STAGE_REGISTER),
            "receiptCopy": str(register_copy),
            "stageManifestFile": prepared_register["stageManifestFile"],
            "stageManifestSha256": prepared_register["stageManifestSha256"],
            "benchmarkRevision": benchmark_revision,
            "stages": frozen_stages,
            "goldPolicy": prepared_register["goldPolicy"],
        },
        "qualityTaskCountExcludingProtocolSmoke": 2155,
        "taskExecutionsIncludingProtocolSmoke": 2171,
        "rules": [
            "No model weights are downloaded by this preparation script.",
            "No GPU is required or inspected by this preparation script.",
            "Public dataset Python dependencies are isolated from vLLM in a dedicated venv.",
            "The data venv uses binary-only pip policy; missing wheels are a preparation failure, never a source-build trigger.",
            "Generated stages are frozen here: the prepared stage register binds each screen's artifact SHA-256, task count, and ordered task-ID SHA-256 to this exact stage manifest, so a promotion run cannot consume unregistered or drifted bytes.",
            "Only model-visible task files are read and hashed; gold answer keys are never read, hashed, or written to any public output.",
        ],
    }
    # The register is a prepared input like the task files it freezes: it belongs in
    # the receipt's file table so a bundle copy carries it and the clean-tree policy
    # can allow it once this receipt verifies it.
    receipt["files"][PREPARED_STAGE_REGISTER.name] = {
        "cases": None,
        "sha256": register_sha256,
        "bytes": len(register_bytes),
        "role": "prepared-stage-register",
        "stageManifestSha256": prepared_register["stageManifestSha256"],
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "prepared",
        "receipt": str(args.receipt),
        "fixedScreenCases": files["english-core-fixed-screen.jsonl"]["cases"],
        "transformCases": files["word-studio-transform.jsonl"]["cases"],
        "strengthCases": files["word-studio-strength.jsonl"]["cases"],
        "preparedStageRegister": {
            "file": str(PREPARED_STAGE_REGISTER),
            "sha256": register_sha256,
            "stages": {
                stage: {
                    "taskCount": entry["taskCount"],
                    "artifactSha256": entry["artifactSha256"],
                    "orderedTaskIdsSha256": entry["orderedTaskIdsSha256"],
                    **(
                        {"subsetOrderedTaskIdsSha256": entry["subsetOrderedTaskIdsSha256"]}
                        if "subsetOrderedTaskIdsSha256" in entry
                        else {}
                    ),
                }
                for stage, entry in prepared_register["stages"].items()
            },
        },
    }, indent=2))


if __name__ == "__main__":
    main()
