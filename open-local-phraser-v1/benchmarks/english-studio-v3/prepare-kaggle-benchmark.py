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
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import time
import venv
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

SEMANTICQA_REPO = "https://github.com/jacklanda/SemanticQA.git"
SEMANTICQA_COMMIT = "56c82a587f4a6cef609255cd10af372d8c76600a"
DATASETS_VERSION = "5.0.1"
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


def ensure_data_venv(path: Path, logs: Path) -> dict[str, Any]:
    python = path / "bin/python"
    recreate = False
    if python.is_file():
        probe = subprocess.run(
            [str(python), "-c", "import datasets, huggingface_hub; print(datasets.__version__); print(huggingface_hub.__version__)"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        versions = probe.stdout.strip().splitlines() if probe.returncode == 0 else []
        if not versions or versions[0] != DATASETS_VERSION:
            recreate = True
    else:
        recreate = True

    if recreate:
        if path.exists():
            shutil.rmtree(path)
        print(f"creating isolated data-prep venv: {path}", flush=True)
        venv.EnvBuilder(with_pip=True, clear=True).create(path)
        env = os.environ.copy()
        env.update({
            "PIP_ONLY_BINARY": ":all:",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        })
        run(
            [str(python), "-m", "pip", "install", "--only-binary=:all:", f"datasets=={DATASETS_VERSION}"],
            env=env,
            log=logs / "data-venv-install.log.txt",
        )

    probe = run(
        [str(python), "-c", "import datasets, huggingface_hub; print(datasets.__version__); print(huggingface_hub.__version__)"],
        log=logs / "data-venv-version.log.txt",
    ).strip().splitlines()
    if not probe or probe[0] != DATASETS_VERSION:
        raise SystemExit(f"isolated data venv has unexpected datasets version: {probe}")
    return {
        "python": str(python),
        "datasetsVersion": probe[0],
        "huggingfaceHubVersion": probe[1] if len(probe) > 1 else None,
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
    run(["node", str(HERE / "build-english-core.mjs")], cwd=HERE, log=logs / "shadow-build.log.txt")

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
        log=logs / "semanticqa-build.log.txt",
    )

    # Assemble model-visible common screen; builder never opens lane answer keys.
    run([sys.executable, str(HERE / "build-english-core-fixed-screen.py")], cwd=HERE, log=logs / "fixed-screen-build.log.txt")

    # Product suites are also generated before GPU work.
    run([sys.executable, str(HERE / "build-word-studio-transform-suite.py")], cwd=HERE, log=logs / "transform-build.log.txt")
    run(
        [
            sys.executable, str(HERE / "build-word-studio-strength-suite.py"),
            "--synthetic-seed", str(HERE / "word-studio-synthetic.seed.json"),
        ],
        cwd=HERE,
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

    receipt = {
        "version": 1,
        "purpose": "CPU-only preparation of frozen Pari English Core and Word Studio task files before GPU/model execution",
        "timestampUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "benchmarkRevision": benchmark_revision,
        "publicDatasetRevisions": PUBLIC_REVISIONS,
        "semanticQA": semanticqa,
        "isolatedDataEnvironment": data_env,
        "files": files,
        "qualityTaskCountExcludingProtocolSmoke": 2155,
        "taskExecutionsIncludingProtocolSmoke": 2171,
        "rules": [
            "No model weights are downloaded by this preparation script.",
            "No GPU is required or inspected by this preparation script.",
            "Public dataset Python dependencies are isolated from vLLM in a dedicated venv.",
            "The data venv uses binary-only pip policy; missing wheels are a preparation failure, never a source-build trigger.",
        ],
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "prepared",
        "receipt": str(args.receipt),
        "fixedScreenCases": files["english-core-fixed-screen.jsonl"]["cases"],
        "transformCases": files["word-studio-transform.jsonl"]["cases"],
        "strengthCases": files["word-studio-strength.jsonl"]["cases"],
    }, indent=2))


if __name__ == "__main__":
    main()
