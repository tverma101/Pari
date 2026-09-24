"""Run JFLEG's official GLEU evaluator with frozen provenance checks.

This wrapper does not reimplement GLEU. It verifies the exact official JFLEG
checkout, source/reference bundle, and hypothesis artifact recorded by Pari,
then invokes the repository's own `eval/gleu.py` and archives its output.

Example:
    python run-jfleg-official-eval.py \
      /path/to/jfleg \
      hypothesis.txt \
      hypothesis.txt.manifest.json \
      jfleg-gleu-result.json

Promotion-quality use requires that the conversion manifest was built from a
prompt manifest with a pinned official repository commit and exactly four pinned
reference files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path


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


def evaluator_environment(python_executable: str) -> dict:
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
    "scipy": version("scipy"),
}))
"""
    try:
        proc = subprocess.run(
            [python_executable, "-c", script],
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(proc.stdout.strip())
    except Exception as exc:
        return {"error": f"could_not_query_evaluator_environment: {exc}"}


def resolve_recorded_path(value: object, fallback_root: Path | None = None) -> Path | None:
    if not value:
        return None
    p = Path(str(value)).expanduser()
    if p.is_absolute():
        return p.resolve()
    if fallback_root is not None:
        candidate = (fallback_root / p).resolve()
        if candidate.exists():
            return candidate
    return p.resolve()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("jfleg_repo")
    ap.add_argument("hypothesis")
    ap.add_argument("conversion_manifest")
    ap.add_argument("out_json")
    ap.add_argument("--python", default=sys.executable, help="Python executable used to run official eval/gleu.py")
    args = ap.parse_args()

    repo = Path(args.jfleg_repo).resolve()
    hyp = Path(args.hypothesis).resolve()
    manifest_path = Path(args.conversion_manifest).resolve()
    out = Path(args.out_json).resolve()

    if not repo.is_dir():
        raise SystemExit(f"Missing JFLEG repository: {repo}")
    if not hyp.is_file():
        raise SystemExit(f"Missing hypothesis file: {hyp}")
    if not manifest_path.is_file():
        raise SystemExit(f"Missing conversion manifest: {manifest_path}")

    manifest = json.loads(manifest_path.read_text())
    errors: list[str] = []

    if manifest.get("promotionProvenanceReady") is not True:
        errors.append("conversion_manifest_not_promotion_ready")
    if manifest.get("outHypothesisSha256") != sha256(hyp):
        errors.append("hypothesis_hash_mismatch")

    expected_revision = str(manifest.get("officialJflegRepositoryRevision") or "").strip()
    actual_revision = git_head(repo)
    if not expected_revision:
        errors.append("missing_expected_jfleg_revision")
    elif actual_revision != expected_revision:
        errors.append("jfleg_checkout_revision_mismatch")

    evaluator = repo / "eval" / "gleu.py"
    if not evaluator.is_file():
        errors.append("missing_official_eval_gleu_py")

    source = resolve_recorded_path(manifest.get("sourceFile"), repo)
    if source is None or not source.is_file():
        errors.append("recorded_source_file_missing")
    elif manifest.get("sourceSha256") != sha256(source):
        errors.append("source_hash_mismatch")

    reference_records = manifest.get("references") or []
    if len(reference_records) != 4:
        errors.append("expected_exactly_four_reference_records")
    references: list[Path] = []
    seen_paths: set[Path] = set()
    seen_hashes: set[str] = set()
    for i, record in enumerate(reference_records):
        ref = resolve_recorded_path(record.get("path"), repo)
        if ref is None or not ref.is_file():
            errors.append(f"reference_{i}_missing")
            continue
        digest = sha256(ref)
        if ref in seen_paths:
            errors.append(f"reference_{i}_duplicates_another_reference_path")
        if digest in seen_hashes:
            errors.append(f"reference_{i}_duplicates_another_reference_bytes")
        seen_paths.add(ref)
        seen_hashes.add(digest)
        if record.get("sha256") != digest:
            errors.append(f"reference_{i}_hash_mismatch")
        references.append(ref)

    evaluator_env = evaluator_environment(args.python)
    if evaluator_env.get("error"):
        errors.append("could_not_query_evaluator_python_environment")
    if evaluator_env.get("numpy") is None or evaluator_env.get("scipy") is None:
        errors.append("evaluator_python_missing_numpy_or_scipy")

    if errors:
        raise SystemExit("JFLEG evaluator provenance failed:\n- " + "\n- ".join(errors))

    command = [
        args.python,
        str(evaluator),
        "-r",
        *[str(ref) for ref in references],
        "-s",
        str(source),
        "--hyp",
        str(hyp),
    ]
    started = time.time()
    proc = subprocess.run(command, text=True, capture_output=True)
    elapsed = time.time() - started
    if proc.returncode != 0:
        raise SystemExit(
            "Official JFLEG evaluator failed with exit code "
            f"{proc.returncode}:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )

    result = {
        "version": 3,
        "purpose": "Frozen output from JFLEG's official GLEU evaluator; Pari does not reimplement the metric.",
        "jflegRepository": str(repo),
        "jflegRepositoryRevision": actual_revision,
        "evaluatorFile": str(evaluator),
        "evaluatorSha256": sha256(evaluator),
        "sourceFile": str(source),
        "sourceSha256": sha256(source),
        "references": [
            {"path": str(ref), "sha256": sha256(ref)} for ref in references
        ],
        "hypothesisFile": str(hyp),
        "hypothesisSha256": sha256(hyp),
        "conversionManifest": str(manifest_path),
        "conversionManifestSha256": sha256(manifest_path),
        "command": command,
        "protocol": {
            "metric": "official JFLEG GLEU",
            "iterations": 500,
            "iterationSetting": "official eval/gleu.py default; --iter omitted",
            "referenceSampling": "official evaluator reseeds each iteration with j*101",
            "referencesUsed": 4,
        },
        "environment": evaluator_env,
        "elapsedSeconds": round(elapsed, 6),
        "returnCode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "researchReference": "https://aclanthology.org/E17-2037/",
        "officialRepository": "https://github.com/keisks/jfleg",
        "notes": [
            "The official evaluator code is executed directly; this wrapper only verifies and records provenance.",
            "The repository's default 500-iteration protocol is retained because eval/gleu.py uses deterministic per-iteration seeds under that default.",
            "Python/NumPy/SciPy versions are queried from the exact interpreter used to execute eval/gleu.py, not from the wrapper process by assumption.",
            "Keep this JSON artifact with the exact hypothesis conversion manifest for promotion-quality comparison."
        ],
    }
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({
        "out": str(out),
        "jflegRepositoryRevision": actual_revision,
        "evaluatorSha256": result["evaluatorSha256"],
        "hypothesisSha256": result["hypothesisSha256"],
        "elapsedSeconds": result["elapsedSeconds"],
    }, indent=2))


if __name__ == "__main__":
    main()
