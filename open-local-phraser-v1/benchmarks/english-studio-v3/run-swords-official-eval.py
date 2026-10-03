"""Run SWORDS' official evaluator with frozen provenance checks.

This wrapper does not reimplement lexical-substitution metrics. It verifies that
Pari's prompt source is byte-identical to the official parsed dataset in a pinned
SWORDS checkout, verifies the converted `.lsr.json`, then invokes
`python -m swords.cli eval` from that checkout and archives the official metrics.

Example:
    python run-swords-official-eval.py \
      /path/to/swords \
      model.swords.lsr.json \
      model.swords.lsr.json.manifest.json \
      swords-official-result.json

Issue #66: `parse_candidates()` is Pari-owned and score-affecting, so the conversion
manifest must bind a registered conversion protocol
(`pari-swords-candidate-parser` v1) whose contract hash, converter source hash,
config, and benchmark Git identity verify. `promotionProvenanceReady: true` is not
self-authenticating; a missing, unknown, or drifted converter identity fails here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from english_core_converter_provenance import (  # noqa: E402
    SWORDS_PROTOCOL_ID,
    verify_converter_provenance,
)

CORE_METRICS = (
    "lenient_a_f@10",
    "lenient_c_f@10",
    "strict_a_f@10",
    "strict_c_f@10",
    "strict_c_p@1",
)
GIT_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
CONVERTER_REL = "convert-swords-english-core-output.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head(repo: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip() or None
    except Exception:
        return None


def git_dirty(repo: Path) -> bool | None:
    try:
        return bool(subprocess.check_output(
            ["git", "-C", str(repo), "status", "--porcelain"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip())
    except Exception:
        return None


def evaluator_environment(python_executable: str, repo: Path) -> dict:
    script = """
import importlib.metadata
import json
import platform
import sys

def version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None

print(json.dumps({
    "pythonExecutable": sys.executable,
    "pythonVersion": sys.version,
    "platform": platform.platform(),
    "numpy": version("numpy"),
    "nltk": version("nltk"),
}))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    try:
        proc = subprocess.run(
            [python_executable, "-c", script],
            cwd=repo,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(proc.stdout.strip())
    except Exception as exc:
        return {"error": f"could_not_query_evaluator_environment: {exc}"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("swords_repo")
    ap.add_argument("lsr_json")
    ap.add_argument("conversion_manifest")
    ap.add_argument("out_json")
    ap.add_argument("--python", default=sys.executable, help="Python executable used to run the official SWORDS CLI")
    args = ap.parse_args()

    repo = Path(args.swords_repo).resolve()
    lsr = Path(args.lsr_json).resolve()
    manifest_path = Path(args.conversion_manifest).resolve()
    out = Path(args.out_json).resolve()

    if not repo.is_dir():
        raise SystemExit(f"Missing SWORDS repository: {repo}")
    if not lsr.is_file():
        raise SystemExit(f"Missing SWORDS result file: {lsr}")
    if not manifest_path.is_file():
        raise SystemExit(f"Missing SWORDS conversion manifest: {manifest_path}")

    manifest = json.loads(manifest_path.read_text())
    errors: list[str] = []

    if manifest.get("promotionProvenanceReady") is not True:
        errors.append("conversion_manifest_not_promotion_ready")
    if manifest.get("outLsrSha256") != sha256(lsr):
        errors.append("lsr_hash_mismatch")

    converter_path = Path(__file__).resolve().parent / CONVERTER_REL
    errors.extend(
        verify_converter_provenance(
            manifest, benchmark="swords", converter_path=converter_path
        )
    )

    expected_revision = str(manifest.get("officialSwordsRepositoryRevision") or "").strip()
    actual_revision = git_head(repo)
    dirty = git_dirty(repo)
    if not GIT_COMMIT_RE.fullmatch(expected_revision):
        errors.append("expected_swords_revision_is_not_full_commit_sha")
    elif actual_revision != expected_revision:
        errors.append("swords_checkout_revision_mismatch")
    if dirty is None:
        errors.append("could_not_determine_swords_worktree_cleanliness")
    elif dirty:
        errors.append("swords_checkout_is_dirty")

    dataset_id = str(manifest.get("officialDatasetId") or "").strip()
    if not dataset_id:
        errors.append("missing_official_dataset_id")

    official_dataset_file = repo / "assets" / "parsed" / f"{dataset_id}.json.gz"
    if not official_dataset_file.is_file():
        errors.append("official_dataset_file_missing_from_pinned_checkout")
    elif manifest.get("benchmarkSha256") != sha256(official_dataset_file):
        errors.append("official_dataset_bytes_do_not_match_prompt_source")

    required_modules = [
        repo / "swords" / "cli.py",
        repo / "swords" / "eval.py",
        repo / "swords" / "datasets.py",
        repo / "swords" / "lemma.py",
        repo / "swords" / "run.py",
        repo / "swords" / "__init__.py",
    ]
    for module in required_modules:
        if not module.is_file():
            errors.append(f"missing_official_module:{module.name}")

    evaluator_env = evaluator_environment(args.python, repo)
    if evaluator_env.get("error"):
        errors.append("could_not_query_evaluator_python_environment")
    if evaluator_env.get("numpy") is None or evaluator_env.get("nltk") is None:
        errors.append("evaluator_python_missing_numpy_or_nltk")

    if errors:
        raise SystemExit("SWORDS evaluator provenance failed:\n- " + "\n- ".join(errors))

    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    with tempfile.TemporaryDirectory(prefix="pari-swords-eval-") as tmp:
        metrics_path = Path(tmp) / "metrics.json"
        command = [
            args.python,
            "-m",
            "swords.cli",
            "eval",
            dataset_id,
            "--result_json_fp",
            str(lsr),
            "--output_metrics_json_fp",
            str(metrics_path),
            "--quiet",
        ]
        started = time.time()
        proc = subprocess.run(command, cwd=repo, env=env, text=True, capture_output=True)
        elapsed = time.time() - started
        if proc.returncode != 0:
            raise SystemExit(
                "Official SWORDS evaluator failed with exit code "
                f"{proc.returncode}:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
            )
        if not metrics_path.is_file():
            raise SystemExit("Official SWORDS evaluator did not create the requested metrics JSON")
        metrics_bytes = metrics_path.read_bytes()
        metrics = json.loads(metrics_bytes)

    missing_core = [name for name in CORE_METRICS if metrics.get(name) is None]
    if missing_core:
        raise SystemExit("Official SWORDS metrics output is missing core metrics: " + ", ".join(missing_core))

    module_hashes = {
        str(module.relative_to(repo)): sha256(module)
        for module in required_modules
    }
    result = {
        "version": 2,
        "purpose": "Frozen output from SWORDS' official evaluator; Pari does not reimplement the lexical-substitution metrics.",
        "swordsRepository": str(repo),
        "swordsRepositoryRevision": actual_revision,
        "swordsWorktreeDirty": dirty,
        "officialDatasetId": dataset_id,
        "officialDatasetFile": str(official_dataset_file),
        "officialDatasetSha256": sha256(official_dataset_file),
        "expectedBenchmarkSha256": manifest.get("benchmarkSha256"),
        "officialModuleSha256": module_hashes,
        "lsrFile": str(lsr),
        "lsrSha256": sha256(lsr),
        "conversionManifest": str(manifest_path),
        "conversionManifestSha256": sha256(manifest_path),
        "conversionChain": {
            "converterSource": (manifest.get("converterProvenance") or {}).get("converterSource"),
            "converterProtocol": (manifest.get("converterProvenance") or {}).get("protocol"),
            "conversionIdentity": (manifest.get("converterProvenance") or {}).get("identity"),
            "benchmarkGit": (manifest.get("converterProvenance") or {}).get("benchmarkGit"),
            "conversionConfig": (manifest.get("converterProvenance") or {}).get("conversionConfig"),
            "coverage": manifest.get("coverage"),
            "verifiedByWrapper": True,
        },
        "command": command,
        "environment": evaluator_env,
        "elapsedSeconds": round(elapsed, 6),
        "returnCode": proc.returncode,
        "stdout": proc.stdout,
        "stdoutSha256": hashlib.sha256(proc.stdout.encode("utf-8")).hexdigest(),
        "stderr": proc.stderr,
        "metrics": metrics,
        "metricsJsonSha256": hashlib.sha256(metrics_bytes).hexdigest(),
        "coreMetricsRequired": list(CORE_METRICS),
        "researchReference": "https://aclanthology.org/2021.naacl-main.345/",
        "officialRepository": "https://github.com/p-lambda/swords",
        "notes": [
            "The official CLI/evaluator is executed directly; Pari only verifies inputs and archives provenance.",
            "The pinned SWORDS checkout must be clean, preventing uncommitted evaluator/data changes from masquerading as the recorded commit.",
            "The benchmark source used to build prompts must be byte-identical to assets/parsed/<officialDatasetId>.json.gz in the pinned checkout.",
            "The official SWORDS loader also verifies the parsed dataset's internal dataset ID against its registry before evaluation.",
            "The conversion layer is Pari-owned and score-affecting: this wrapper re-hashes the converter script, verifies the registered protocol contract hash, and recomputes the conversion identity, so a changed parser or config cannot produce a promotion-ready official score.",
            "Core strict/lenient F@10 and strict conceivable P@1 metrics must be present; optional GAP/legacy metrics may depend on additional official assets."
        ],
    }
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({
        "out": str(out),
        "swordsRepositoryRevision": actual_revision,
        "swordsWorktreeDirty": dirty,
        "officialDatasetId": dataset_id,
        "officialDatasetSha256": result["officialDatasetSha256"],
        "lsrSha256": result["lsrSha256"],
        "coreMetrics": {name: metrics[name] for name in CORE_METRICS},
        "elapsedSeconds": result["elapsedSeconds"],
    }, indent=2))


if __name__ == "__main__":
    main()
