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

Issue #66: `normalize_one_line()` is Pari-owned and score-affecting, so the
conversion manifest must bind a registered conversion protocol
(`pari-jfleg-one-line-normalizer` v1) whose contract hash, converter source hash,
config, and benchmark Git identity verify. `promotionProvenanceReady: true` is not
self-authenticating; a missing, unknown, or drifted converter identity fails here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from english_core_converter_provenance import (  # noqa: E402
    JFLEG_PROTOCOL_ID,
    verify_converter_provenance,
)

GIT_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{40}$")
CONVERTER_REL = "convert-jfleg-english-core-output.py"


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


def official_jfleg_file(repo: Path, recorded: Path) -> Path | None:
    """Map canonical dev/test JFLEG filenames back into the pinned checkout."""
    name = recorded.name
    if name.startswith("dev."):
        candidate = repo / "dev" / name
    elif name.startswith("test."):
        candidate = repo / "test" / name
    else:
        return None
    return candidate.resolve()


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

    converter_path = Path(__file__).resolve().parent / CONVERTER_REL
    errors.extend(
        verify_converter_provenance(
            manifest, benchmark="jfleg", converter_path=converter_path
        )
    )

    expected_revision = str(manifest.get("officialJflegRepositoryRevision") or "").strip()
    actual_revision = git_head(repo)
    dirty = git_dirty(repo)
    if not GIT_COMMIT_RE.fullmatch(expected_revision):
        errors.append("expected_jfleg_revision_is_not_full_commit_sha")
    elif actual_revision != expected_revision:
        errors.append("jfleg_checkout_revision_mismatch")
    if dirty is None:
        errors.append("could_not_determine_jfleg_worktree_cleanliness")
    elif dirty:
        errors.append("jfleg_checkout_is_dirty")

    evaluator = repo / "eval" / "gleu.py"
    if not evaluator.is_file():
        errors.append("missing_official_eval_gleu_py")

    source = resolve_recorded_path(manifest.get("sourceFile"), repo)
    official_source = None
    if source is None or not source.is_file():
        errors.append("recorded_source_file_missing")
    else:
        digest = sha256(source)
        if manifest.get("sourceSha256") != digest:
            errors.append("source_hash_mismatch")
        official_source = official_jfleg_file(repo, source)
        if official_source is None or not official_source.is_file():
            errors.append("source_filename_not_mappable_to_official_dev_or_test_file")
        elif sha256(official_source) != digest:
            errors.append("recorded_source_bytes_do_not_match_pinned_checkout")

    reference_records = manifest.get("references") or []
    if len(reference_records) != 4:
        errors.append("expected_exactly_four_reference_records")
    references: list[Path] = []
    official_references: list[Path] = []
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
        official_ref = official_jfleg_file(repo, ref)
        if official_ref is None or not official_ref.is_file():
            errors.append(f"reference_{i}_filename_not_mappable_to_official_dev_or_test_file")
        elif sha256(official_ref) != digest:
            errors.append(f"reference_{i}_bytes_do_not_match_pinned_checkout")
        else:
            official_references.append(official_ref)
        references.append(ref)

    if official_source is not None and official_source.is_file() and official_references:
        source_split = official_source.parent.name
        if any(ref.parent.name != source_split for ref in official_references):
            errors.append("source_and_references_do_not_share_same_official_split")

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
        *[str(ref) for ref in official_references],
        "-s",
        str(official_source),
        "--hyp",
        str(hyp),
    ]
    started = time.time()
    proc = subprocess.run(command, cwd=repo, text=True, capture_output=True)
    elapsed = time.time() - started
    if proc.returncode != 0:
        raise SystemExit(
            "Official JFLEG evaluator failed with exit code "
            f"{proc.returncode}:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    if not proc.stdout.strip():
        raise SystemExit("Official JFLEG evaluator returned empty stdout; refusing to archive an unverifiable metric result")

    result = {
        "version": 4,
        "purpose": "Frozen output from JFLEG's official GLEU evaluator; Pari does not reimplement the metric.",
        "jflegRepository": str(repo),
        "jflegRepositoryRevision": actual_revision,
        "jflegWorktreeDirty": dirty,
        "evaluatorFile": str(evaluator),
        "evaluatorSha256": sha256(evaluator),
        "sourceFile": str(official_source),
        "sourceSha256": sha256(official_source),
        "references": [
            {"path": str(ref), "sha256": sha256(ref)} for ref in official_references
        ],
        "hypothesisFile": str(hyp),
        "hypothesisSha256": sha256(hyp),
        "conversionManifest": str(manifest_path),
        "conversionManifestSha256": sha256(manifest_path),
        "conversionChain": {
            "converterSource": (manifest.get("converterProvenance") or {}).get("converterSource"),
            "converterProtocol": (manifest.get("converterProvenance") or {}).get("protocol"),
            "conversionIdentity": (manifest.get("converterProvenance") or {}).get("identity"),
            "benchmarkGit": (manifest.get("converterProvenance") or {}).get("benchmarkGit"),
            "conversionConfig": (manifest.get("converterProvenance") or {}).get("conversionConfig"),
            "coverage": manifest.get("coverage"),
            "rawHypotheses": manifest.get("rawHypotheses"),
            "verifiedByWrapper": True,
        },
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
        "stdoutSha256": hashlib.sha256(proc.stdout.encode("utf-8")).hexdigest(),
        "stderr": proc.stderr,
        "researchReference": "https://aclanthology.org/E17-2037/",
        "officialRepository": "https://github.com/keisks/jfleg",
        "notes": [
            "The official evaluator code is executed directly; this wrapper only verifies and records provenance.",
            "The pinned JFLEG checkout must be clean, preventing uncommitted evaluator/data changes from masquerading as the recorded commit.",
            "Source and all four references are byte-checked against their canonical dev/ or test/ files in the pinned checkout before evaluation.",
            "The repository's default 500-iteration protocol is retained because eval/gleu.py uses deterministic per-iteration seeds under that default.",
            "Python/NumPy/SciPy versions are queried from the exact interpreter used to execute eval/gleu.py, not from the wrapper process by assumption.",
            "The one-line normalizer is Pari-owned and score-affecting: this wrapper re-hashes the converter script, verifies the registered protocol contract hash, and recomputes the conversion identity, so a normalization change cannot produce a promotion-ready official score.",
            "Keep this JSON artifact with the exact hypothesis conversion manifest for promotion-quality comparison."
        ],
    }
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({
        "out": str(out),
        "jflegRepositoryRevision": actual_revision,
        "jflegWorktreeDirty": dirty,
        "evaluatorSha256": result["evaluatorSha256"],
        "hypothesisSha256": result["hypothesisSha256"],
        "stdoutSha256": result["stdoutSha256"],
        "elapsedSeconds": result["elapsedSeconds"],
    }, indent=2))


if __name__ == "__main__":
    main()
