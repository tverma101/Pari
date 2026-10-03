"""Run the pinned official SemanticQA LCC evaluator with provenance checks.

Promotion-quality evaluation requires the frozen ACL-2026 SemanticQA checkout,
a clean worktree, a protocol-faithful conversion produced by
convert-semanticqa-lcc-official-output.py, and the expected 305 LCC cases.

Issue #66 provenance rules enforced here:

* The conversion manifest must bind a registered conversion protocol
  (``pari-semanticqa-lcc-postprocess`` v1) whose recorded contract hash, converter
  source hash, config, and benchmark Git identity still verify. A natural-language
  ``predictionPolicy`` string is documentation, not proof.
* Promotion requires the conversion to have imported the official postprocessor
  from a verified pinned checkout, never the local mirror.
* All interpreter/package metadata is queried from the exact ``--python``
  executable that runs official ``semantic_qa/eval.py`` -- never from the wrapper
  process -- so the report describes the interpreter that produced the metric.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from english_core_converter_provenance import (  # noqa: E402
    SEMANTICQA_PROTOCOL_ID,
    verify_converter_provenance,
)

PINNED_COMMIT = "56c82a587f4a6cef609255cd10af372d8c76600a"
EVAL_REL = Path("semantic_qa/eval.py")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_CASES = 305
CONVERTER_REL = "convert-semanticqa-lcc-official-output.py"

#: Packages that can change an official SemanticQA metric. Queried from the selected
#: evaluator interpreter, not from this wrapper process.
EVALUATOR_CRITICAL_PACKAGES = (
    "numpy",
    "scikit-learn",
    "evaluate",
    "nltk",
    "pandas",
    "sacrebleu",
    "datasets",
)

ENVIRONMENT_PROBE = """
import importlib.metadata
import json
import platform
import sys

PACKAGES = {packages!r}

def version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None

print(json.dumps({{
    "resolvedExecutable": sys.executable,
    "argv0": sys.argv[0],
    "pythonVersion": sys.version,
    "pythonImplementation": platform.python_implementation(),
    "platform": platform.platform(),
    "machine": platform.machine(),
    "abi": getattr(sys, "abiflags", ""),
    "packages": {{name: version(name) for name in PACKAGES}},
}}, sort_keys=True))
""".strip()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def git(checkout: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=checkout, text=True, stderr=subprocess.STDOUT).strip()


def resolve_python(python_executable: str) -> str:
    """Resolve ``--python`` to the exact executable that will be executed."""
    resolved = shutil_which(python_executable)
    if resolved:
        return resolved
    candidate = Path(python_executable).expanduser()
    if candidate.is_file():
        return str(candidate.resolve())
    return python_executable


def shutil_which(executable: str) -> str | None:
    import shutil

    return shutil.which(executable)


def evaluator_environment(python_executable: str, checkout: Path) -> dict:
    """Query interpreter/package metadata *from the selected evaluator interpreter*.

    ``platform.python_version()`` in the wrapper process would describe the wrong
    interpreter whenever ``--python`` differs, which is exactly the #66 defect.
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = str(checkout) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    script = ENVIRONMENT_PROBE.format(packages=list(EVALUATOR_CRITICAL_PACKAGES))
    try:
        proc = subprocess.run(
            [python_executable, "-c", script],
            cwd=checkout,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(proc.stdout.strip())
    except Exception as exc:
        return {"error": f"could_not_query_evaluator_environment: {exc}"}


def self_path() -> Path:
    return Path(__file__).resolve()


def wrapper_identity() -> dict:
    return {
        "path": self_path().name,
        "sha256": sha256_file(self_path()),
        "bytes": self_path().stat().st_size,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--semanticqa-checkout", required=True, type=Path)
    ap.add_argument("--converted", required=True, type=Path)
    ap.add_argument("--conversion-manifest", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--promotion", action="store_true")
    args = ap.parse_args()

    checkout = args.semanticqa_checkout.expanduser().resolve()
    converted = args.converted.expanduser().resolve()
    conv_manifest_path = args.conversion_manifest.expanduser().resolve()
    if not checkout.is_dir() or not converted.is_file() or not conv_manifest_path.is_file():
        raise SystemExit("Missing SemanticQA checkout, converted result, or conversion manifest")

    commit = git(checkout, "rev-parse", "HEAD").lower()
    dirty = bool(git(checkout, "status", "--porcelain"))
    if args.promotion:
        if not SHA40_RE.fullmatch(commit) or commit != PINNED_COMMIT:
            raise SystemExit(f"Promotion evaluation requires SemanticQA commit {PINNED_COMMIT}; got {commit}")
        if dirty:
            raise SystemExit("Promotion evaluation requires a clean SemanticQA checkout")

    eval_path = checkout / EVAL_REL
    if not eval_path.is_file():
        raise SystemExit(f"Missing official SemanticQA evaluator: {eval_path}")

    conv_manifest = json.loads(conv_manifest_path.read_text(encoding="utf-8"))
    if conv_manifest.get("sourceCommit") != commit:
        raise SystemExit("Conversion manifest source commit does not match evaluator checkout")
    if conv_manifest.get("convertedFileSha256") != sha256_file(converted):
        raise SystemExit("Converted LCC result hash does not match conversion manifest")

    cases = int(conv_manifest.get("cases", -1))
    provenance_errors = verify_converter_provenance(
        conv_manifest,
        benchmark="semanticqa_lcc",
        converter_path=self_path().parent / CONVERTER_REL,
    )
    postprocessor = conv_manifest.get("postprocessor")
    if not isinstance(postprocessor, dict):
        provenance_errors.append("semanticqa_postprocessor_provenance_missing")
    elif postprocessor.get("kind") != "official-pinned-import":
        provenance_errors.append("semanticqa_postprocessor_not_official_pinned_import")
    elif postprocessor.get("commit") != commit:
        provenance_errors.append("semanticqa_postprocessor_commit_does_not_match_evaluator_checkout")

    if args.promotion:
        if int(conv_manifest.get("version", 0)) < 3:
            raise SystemExit(
                "Promotion evaluation requires converter-bound SemanticQA conversion manifest v3+"
            )
        if cases != EXPECTED_CASES:
            raise SystemExit(f"Promotion evaluation requires {EXPECTED_CASES} LCC cases; got {cases}")
        if provenance_errors:
            raise SystemExit(
                "SemanticQA converter/postprocessor provenance failed:\n- "
                + "\n- ".join(provenance_errors)
            )

    python_executable = resolve_python(args.python)
    evaluator_env = evaluator_environment(python_executable, checkout)
    if evaluator_env.get("error"):
        raise SystemExit(
            "Could not query the selected evaluator interpreter environment: "
            f"{evaluator_env['error']}"
        )

    cmd = [python_executable, str(eval_path), "--task", "lcc", "--result_file_path", str(converted)]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(checkout) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    proc = subprocess.run(
        cmd,
        cwd=eval_path.parent,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.returncode != 0:
        raise SystemExit(f"Official SemanticQA evaluator failed ({proc.returncode}):\n{proc.stdout}")

    matches = re.findall(r"Total:\s*(\d+),\s*Correct:\s*(\d+),\s*Accuracy:\s*([0-9.]+)", proc.stdout)
    if not matches:
        raise SystemExit("Could not parse total LCC accuracy from official SemanticQA evaluator output")
    total_s, correct_s, percent_s = matches[-1]
    total = int(total_s)
    correct = int(correct_s)
    accuracy_percent = float(percent_s)
    if total != cases:
        raise SystemExit(f"Official evaluator total {total} != conversion cases {cases}")
    if args.promotion and total != EXPECTED_CASES:
        raise SystemExit(f"Promotion evaluation requires official evaluator total {EXPECTED_CASES}; got {total}")

    report = {
        "version": 3,
        "benchmark": "SemanticQA LCC official protocol evaluation",
        "researchReference": "https://aclanthology.org/2026.acl-long.210/",
        "sourceCommit": commit,
        "pinnedPromotionCommit": PINNED_COMMIT,
        "checkoutDirty": dirty,
        "promotionEvaluation": args.promotion,
        "promotionReady": bool(
            args.promotion
            and commit == PINNED_COMMIT
            and not dirty
            and total == EXPECTED_CASES
            and not provenance_errors
        ),
        "pariEvaluatorWrapper": wrapper_identity(),
        "officialEvaluator": {
            "path": str(EVAL_REL),
            "sha256": sha256_file(eval_path),
            "repositoryRevision": commit,
            "pythonExecutable": python_executable,
            "command": cmd,
            "environmentSource": "queried-from --python executable via subprocess probe",
            "environment": evaluator_env,
        },
        "conversion": {
            "manifestPath": str(conv_manifest_path),
            "manifestSha256": sha256_file(conv_manifest_path),
            "manifestVersion": conv_manifest.get("version"),
            "predictionPolicy": conv_manifest.get("predictionPolicy"),
            "postprocessor": postprocessor,
            "converterProvenance": conv_manifest.get("converterProvenance"),
            "conversionIdentity": (conv_manifest.get("converterProvenance") or {}).get("identity"),
            "coverage": conv_manifest.get("coverage"),
            "provenanceErrors": provenance_errors,
            "promotionProvenanceReady": conv_manifest.get("promotionProvenanceReady"),
            "postprocessChangedOutputs": conv_manifest.get("postprocessChangedOutputs"),
        },
        "convertedResult": {"path": str(converted), "sha256": sha256_file(converted)},
        "metrics": {
            "cases": total,
            "correct": correct,
            "accuracy": correct / total if total else None,
            "accuracyPercentAsPrinted": accuracy_percent,
        },
        "stdout": proc.stdout,
        "generatedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "interpretation": [
            "This executes the pinned official SemanticQA standalone LCC evaluator on predictions postprocessed according to the pinned SemanticQA collocation-categorization pipeline.",
            "The evaluator itself uses exact label equality after that official postprocessing. Pari's broader format-tolerant scorer is a separate diagnostic and must not replace this value in official-protocol reporting.",
            "converterProvenance binds the conversion protocol contract hash, converter source SHA-256, conversion config, and benchmark Git commit/tree; a missing or unknown protocol identity is rejected for promotion.",
            "predictionPolicy is documentation only. The executable fidelity proof is the postprocessor provenance block, which records an official import from the pinned clean checkout.",
            "environment metadata is queried from the exact --python executable that runs the official evaluator, so interpreter drift is visible instead of inherited from the wrapper.",
            "Report this modern prompted LLM anchor separately from the EACL 2021 supervised/MLM collocation protocol and from Pari's shadow collocation cases.",
        ],
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
