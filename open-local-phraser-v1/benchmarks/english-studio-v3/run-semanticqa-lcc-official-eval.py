"""Run the pinned official SemanticQA LCC evaluator with provenance checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

PINNED_COMMIT = "56c82a587f4a6cef609255cd10af372d8c76600a"
EVAL_REL = Path("semantic_qa/eval.py")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def git(checkout: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=checkout, text=True, stderr=subprocess.STDOUT).strip()


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
    if total != int(conv_manifest.get("cases", -1)):
        raise SystemExit(f"Official evaluator total {total} != conversion cases {conv_manifest.get('cases')}")

    report = {
        "version": 1,
        "benchmark": "SemanticQA LCC official strict evaluation",
        "sourceCommit": commit,
        "checkoutDirty": dirty,
        "promotionEvaluation": args.promotion,
        "officialEvaluator": {
            "path": str(EVAL_REL),
            "sha256": sha256_file(eval_path),
            "python": args.python,
            "command": cmd,
        },
        "convertedResult": {"path": str(converted), "sha256": sha256_file(converted)},
        "conversionManifestSha256": sha256_file(conv_manifest_path),
        "metrics": {
            "cases": total,
            "correct": correct,
            "accuracy": correct / total if total else None,
            "accuracyPercentAsPrinted": accuracy_percent,
        },
        "stdout": proc.stdout,
        "generatedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "interpretation": "This is the strict official SemanticQA LCC exact-label evaluation. Pari's tolerant scorer is a separate diagnostic and must not replace this value in official-protocol reporting.",
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["metrics"], indent=2))
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
