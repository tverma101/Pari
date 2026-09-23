"""Convert an English Core model result into official SWORDS `.lsr.json` format.

Usage:
    python convert-swords-english-core-output.py \
        swords-v1.1_test.json.gz model-result.json model.swords.lsr.json

Then evaluate with the official SWORDS repository, for example:
    python -m swords.cli eval swords-v1.1_test \
        --result_json_fp model.swords.lsr.json \
        --output_metrics_json_fp model.swords.metrics.json

Prefer the official repository's documented Docker/CLI environment for numbers
that will be compared to published SWORDS results.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
from pathlib import Path


def read_json(path: Path) -> dict:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    return json.loads(path.read_text())


def parse_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^\s*(?:[-*•]+|\d+[.)]|[A-Za-z][.)])\s*", "", line).strip()
        line = line.strip("`\"' ")
        if not line:
            continue
        # Reject obvious meta prose rather than turning an explanation into a substitute.
        lower = line.lower()
        if lower.startswith(("here are", "substitutes:", "alternatives:", "the best")):
            continue
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(line)
    return candidates


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("swords_json")
    ap.add_argument("model_result")
    ap.add_argument("out_lsr_json")
    ap.add_argument("--lemmatized", action="store_true", help="Set only if model outputs lemmas rather than context-fitting wordforms")
    ap.add_argument("--max-candidates", type=int, default=40)
    args = ap.parse_args()

    benchmark = read_json(Path(args.swords_json).resolve())
    targets = benchmark.get("targets", {})
    run = json.loads(Path(args.model_result).read_text())
    outputs = {row["id"]: row.get("output", "") for row in run.get("outputs", [])}

    converted: dict[str, list[list[object]]] = {}
    missing = []
    empty = []
    for target_id in targets:
        if target_id not in outputs:
            missing.append(target_id)
            converted[target_id] = []
            continue
        candidates = parse_candidates(outputs[target_id])[: args.max_candidates]
        if not candidates:
            empty.append(target_id)
        n = len(candidates)
        # The official SWORDS format accepts ranked candidate/score pairs. Scores
        # here encode only the model's output ranking; official SWORDS evaluation
        # decides candidate quality.
        converted[target_id] = [[candidate, float(n - i)] for i, candidate in enumerate(candidates)]

    result = {
        "substitutes_lemmatized": bool(args.lemmatized),
        "substitutes": converted,
    }
    Path(args.out_lsr_json).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "targets": len(targets),
        "converted": len(targets) - len(missing),
        "missingOutputs": len(missing),
        "emptyOutputs": len(empty),
        "out": args.out_lsr_json,
        "nextStep": "Run the official SWORDS evaluator; do not substitute a Pari-invented lexical score for the official metrics."
    }, indent=2))


if __name__ == "__main__":
    main()
