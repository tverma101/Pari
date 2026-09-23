"""Score a result.json from english-core-public-fast.jsonl.

Usage:
    python score-english-core-public-fast.py public-result.json
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS = HERE / "english-core-public-fast.jsonl"
ANSWERS = HERE / "english-core-public-fast.answers.json"


def parse_letter(text: str) -> str | None:
    s = str(text or "").strip().upper()
    if not s:
        return None
    patterns = [
        r"^([A-Z])$",
        r"^([A-Z])(?:[.)\]:-])(?:\s|$)",
        r"^ANSWER\s*[:=-]\s*([A-Z])(?:\b|[.)\]:-])",
        r"^OPTION\s+([A-Z])(?:\b|[.)\]:-])",
    ]
    for pattern in patterns:
        match = re.match(pattern, s)
        if match:
            return match.group(1)
    return None


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
    detail = []

    for task in tasks:
        got = outputs.get(task["id"])
        predicted = parse_letter(got.get("output", "")) if got else None
        expected = answers[task["id"]]
        score = int(predicted == expected) if predicted else 0
        record = {
            "id": task["id"],
            "source": task["source"],
            "dimension": task["dimension"],
            "expected": expected,
            "predicted": predicted,
            "score": score,
            "status": "scored" if predicted else ("missing" if got is None else "invalid_output"),
        }
        detail.append(record)
        by_source[task["source"]].append(score)
        by_dimension[task["dimension"]].append(score)

    def summarize(groups):
        return {
            key: {
                "cases": len(values),
                "accuracy": round(sum(values) / len(values), 6) if values else None,
            }
            for key, values in sorted(groups.items())
        }

    all_scores = [row["score"] for row in detail]
    report = {
        "version": 1,
        "runId": run.get("runId"),
        "model": run.get("model"),
        "cases": len(detail),
        "accuracy": round(sum(all_scores) / len(all_scores), 6) if all_scores else None,
        "bySource": summarize(by_source),
        "byDimension": summarize(by_dimension),
        "notes": [
            "This is a deterministic public-anchor screening subset, not an official full-suite score.",
            "Compare by-source results; do not treat the unweighted overall accuracy as the final English Core composite.",
            "Public-anchor results remain separate from the fresh Pari shadow score to expose possible benchmark memorization/overfitting.",
        ],
        "detail": detail,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
