"""Score a result.json from english-core-public-fast.jsonl.

Usage:
    python score-english-core-public-fast.py public-result.json

This remains a prompted screening protocol, not an official native score for
BLiMP/WiC/CoLA/PAWS. Source-level results are the primary view.
"""

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

from english_core_choice_parser import parse_choice_letter

HERE = Path(__file__).resolve().parent
TASKS = HERE / "english-core-public-fast.jsonl"
ANSWERS = HERE / "english-core-public-fast.answers.json"


def wilson95(successes: int, n: int) -> list[float] | None:
    if n <= 0:
        return None
    z = 1.959963984540054
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt((p * (1 - p) / n) + (z * z / (4 * n * n))) / denom
    return [round(max(0.0, center - half), 6), round(min(1.0, center + half), 6)]


def summarize(groups):
    result = {}
    for key, values in sorted(groups.items()):
        wins = sum(values)
        result[key] = {
            "cases": len(values),
            "correct": wins,
            "accuracy": round(wins / len(values), 6) if values else None,
            "wilson95": wilson95(wins, len(values)),
        }
    return result


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python score-english-core-public-fast.py <result.json>")
    if not TASKS.exists() or not ANSWERS.exists():
        raise SystemExit("Build public fast tasks first with `python build-english-core-public-fast.py`.")

    run = json.loads(Path(sys.argv[1]).read_text())
    tasks = [json.loads(line) for line in TASKS.read_text().splitlines() if line.strip()]
    answers = json.loads(ANSWERS.read_text())["answers"]
    outputs = {row["id"]: row for row in run.get("outputs", [])}

    by_source = defaultdict(list)
    by_dimension = defaultdict(list)
    by_phenomenon = defaultdict(list)
    by_source_phenomenon = defaultdict(list)
    detail = []

    for task in tasks:
        got = outputs.get(task["id"])
        predicted = parse_choice_letter(got.get("output", "")) if got else None
        expected = answers[task["id"]]
        score = int(predicted == expected) if predicted else 0
        phenomenon = task.get("phenomenon") or "unspecified"
        record = {
            "id": task["id"],
            "source": task["source"],
            "dimension": task["dimension"],
            "phenomenon": phenomenon,
            "expected": expected,
            "predicted": predicted,
            "score": score,
            "status": "scored" if predicted else ("missing" if got is None else "invalid_output"),
        }
        detail.append(record)
        by_source[task["source"]].append(score)
        by_dimension[task["dimension"]].append(score)
        by_phenomenon[phenomenon].append(score)
        by_source_phenomenon[f"{task['source']}::{phenomenon}"].append(score)

    all_scores = [row["score"] for row in detail]
    wins = sum(all_scores)
    report = {
        "version": 3,
        "runId": run.get("runId"),
        "model": run.get("model"),
        "cases": len(detail),
        "correct": wins,
        "accuracy": round(wins / len(all_scores), 6) if all_scores else None,
        "wilson95": wilson95(wins, len(all_scores)),
        "bySource": summarize(by_source),
        "byDimension": summarize(by_dimension),
        "byPhenomenon": summarize(by_phenomenon),
        "bySourcePhenomenon": summarize(by_source_phenomenon),
        "notes": [
            "This is a deterministic prompted public-anchor screening subset, not an official full-suite score.",
            "The shared choice parser accepts only unambiguous letter forms such as A, A., Answer: A, The answer is A, or Option A; free-form prose remains invalid.",
            "The 95% Wilson intervals quantify binomial screening uncertainty under this fixed sampled set; they do not solve benchmark contamination or distribution-shift concerns.",
            "Compare by-source and per-phenomenon results; do not treat the unweighted overall accuracy as the final English Core composite.",
            "The fast-screen sampling distribution is deliberately balanced for WiC/CoLA/PAWS and therefore differs from each benchmark's native/full distribution.",
            "Public-anchor results remain separate from the fresh Pari shadow score to expose possible benchmark memorization/overfitting.",
            "For research-level claims, run benchmark-native official protocols and metrics in addition to this common prompted screen."
        ],
        "detail": detail,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
