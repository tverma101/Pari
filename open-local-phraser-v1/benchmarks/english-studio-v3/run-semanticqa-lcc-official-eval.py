"""Run the pinned official SemanticQA LCC evaluator with provenance checks.

Promotion-quality evaluation requires the frozen ACL-2026 SemanticQA checkout,
a clean worktree, a protocol-faithful conversion produced by
convert-semanticqa-lcc-official-output.py, and the expected 305 LCC cases.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

PINNED_COMMIT = "56c82a587f4a6cef609255cd10af372d8c76600a"
EVAL_REL = Path("semantic_qa/eval.py")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_CASES = 305


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def git(checkout: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=checkout, text=True, stderr=subprocess.STDOUT).strip()


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


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
    if args.promotion:
        if int(conv_manifest.get("version", 0)) < 2:
            raise SystemExit("Promotion evaluation requires protocol-faithful SemanticQA conversion manifest v2+")
        if cases != EXPECTED_CASES:
            raise SystemExit(f"Promotion evaluation requires {EXPECTED_CASES} LCC cases; got {cases}")
        policy = str(conv_manifest.get("predictionPolicy") or "")
        required_fragments = ["whitespace normalization", "is: ", "Output:"]
        if not all(fragment in policy for fragment in required_fragments):
            raise SystemExit("Conversion manifest does not document the pinned SemanticQA LCC postprocessing policy")

    cmd = [args.python, str(eval_path), "--task", "lcc", "--result_file_path", str(converted)]
    proc = subprocess.run(cmd, cwd=eval_path.parent, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
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
        "version": 2,
        "benchmark": "SemanticQA LCC official protocol evaluation",
        "researchReference": "https://aclanthology.org/2026.acl-long.210/",
        "sourceCommit": commit,
        "pinnedPromotionCommit": PINNED_COMMIT,
        "checkoutDirty": dirty,
        "promotionEvaluation": args.promotion,
        "promotionReady": bool(args.promotion and commit == PINNED_COMMIT and not dirty and total == EXPECTED_CASES),
        "officialEvaluator": {
            "path": str(EVAL_REL),
            "sha256": sha256_file(eval_path),
            "pythonExecutable": args.python,
            "command": cmd,
            "environment": {
                "python": platform.python_version(),
                "numpy": package_version("numpy"),
                "scikitLearn": package_version("scikit-learn"),
                "evaluate": package_version("evaluate"),
            },
        },
        "conversion": {
            "manifestPath": str(conv_manifest_path),
            "manifestSha256": sha256_file(conv_manifest_path),
            "manifestVersion": conv_manifest.get("version"),
            "predictionPolicy": conv_manifest.get("predictionPolicy"),
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
            "Report this modern prompted LLM anchor separately from the EACL 2021 supervised/MLM collocation protocol and from Pari's shadow collocation cases.",
        ],
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
