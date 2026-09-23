"""Build Pari English Core prompts from an official SWORDS JSON/JSON.GZ file.

This script does not vendor or modify SWORDS data. Download an official SWORDS
benchmark file from https://github.com/p-lambda/swords and pass its path here.

Usage:
    python build-swords-english-core-prompts.py swords-v1.1_test.json.gz swords-prompts.jsonl

The output contains model-visible prompts only. Official SWORDS evaluation remains
authoritative and should be run with the SWORDS repository evaluator.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path


def read_json(path: Path) -> dict:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    return json.loads(path.read_text())


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("swords_json")
    ap.add_argument("out_jsonl")
    ap.add_argument("--count", type=int, default=40, help="Maximum ranked substitutes requested per target")
    args = ap.parse_args()

    source = Path(args.swords_json).resolve()
    data = read_json(source)
    contexts = data.get("contexts", {})
    targets = data.get("targets", {})
    if not contexts or not targets:
        raise SystemExit("Input does not look like an official SWORDS-format benchmark JSON")

    tasks = []
    for target_id, target in targets.items():
        context_id = target["context_id"]
        context = contexts[context_id]["context"]
        target_text = target["target"]
        offset = target.get("offset")
        pos = target.get("pos")
        pos_line = f"\nPart of speech: {pos}" if pos else ""
        prompt = (
            f"Context: {context}\n"
            f"Target text: {target_text}\n"
            f"Target character offset: {offset}{pos_line}\n"
            f"Give up to {args.count} ranked substitutes for the target text that could replace it in this exact context while preserving its intended meaning and grammatical fit. "
            "Do not rewrite the surrounding context. Output only the substitutes, one per line, best first."
        )
        tasks.append({
            "id": target_id,
            "dimension": "lexical_context",
            "source": "SWORDS",
            "task": "lexical_substitution_generation",
            "generative": True,
            "prompt": prompt,
            "metadata": {
                "contextId": context_id,
                "target": target_text,
                "offset": offset,
                "pos": pos,
            },
        })

    out = Path(args.out_jsonl)
    out.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in tasks) + "\n")
    manifest = out.with_suffix(out.suffix + ".manifest.json")
    manifest.write_text(json.dumps({
        "version": 1,
        "sourceFile": str(source),
        "sourceSha256": sha256(source),
        "targets": len(tasks),
        "requestedCandidates": args.count,
        "officialEvaluator": "Use the SWORDS repository CLI/Docker evaluator; Pari does not redefine official SWORDS metrics.",
        "officialRepository": "https://github.com/p-lambda/swords",
        "researchReference": "https://aclanthology.org/2021.naacl-main.345/",
    }, indent=2) + "\n")
    print(json.dumps({"targets": len(tasks), "out": str(out), "manifest": str(manifest)}, indent=2))


if __name__ == "__main__":
    main()
