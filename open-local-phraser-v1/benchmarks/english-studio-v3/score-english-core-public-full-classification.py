"""Score the full-distribution prompted WiC / CoLA / PAWS lane.

Usage:
    python score-english-core-public-full-classification.py result.json

Important:
- This is prompted zero-shot classification on the benchmark distribution.
- It is not identical to a supervised benchmark-native model adaptation.
- CoLA reports MCC only when every item has a valid class prediction; invalid or
  missing outputs are never silently dropped.
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS = HERE / "english-core-public-full-classification.jsonl"
ANSWERS = HERE / "english-core-public-full-classification.answers.json"


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


def safe_div(a: float, b: float) -> float | None:
    return a / b if b else None


def wilson_interval(successes: int, n: int, z: float = 1.959963984540054) -> list[float] | None:
    if n <= 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]


def confusion(gold: list[int], pred: list[int]) -> dict[str, int]:
    tp = sum(1 for g, p in zip(gold, pred) if g == 1 and p == 1)
    tn = sum(1 for g, p in zip(gold, pred) if g == 0 and p == 0)
    fp = sum(1 for g, p in zip(gold, pred) if g == 0 and p == 1)
    fn = sum(1 for g, p in zip(gold, pred) if g == 1 and p == 0)
    return {"tp": tp, "tn": tn, "fp": fp, "fn": fn}


def mcc(cm: dict[str, int]) -> float | None:
    tp, tn, fp, fn = cm["tp"], cm["tn"], cm["fp"], cm["fn"]
    denom = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    if denom == 0:
        return None
    return (tp * tn - fp * fn) / denom


def binary_metrics(gold: list[int], pred: list[int]) -> dict:
    cm = confusion(gold, pred)
    tp, fp, fn = cm["tp"], cm["fp"], cm["fn"]
    precision = safe_div(tp, tp + fp)
    recall = safe_div(tp, tp + fn)
    f1 = None if precision is None or recall is None or precision + recall == 0 else 2 * precision * recall / (precision + recall)
    correct = sum(int(g == p) for g, p in zip(gold, pred))
    return {
        "cases": len(gold),
        "accuracy": round(correct / len(gold), 6) if gold else None,
        "accuracyWilson95": wilson_interval(correct, len(gold)),
        "mcc": None if (value := mcc(cm)) is None else round(value, 6),
        "precisionPositive": None if precision is None else round(precision, 6),
        "recallPositive": None if recall is None else round(recall, 6),
        "f1Positive": None if f1 is None else round(f1, 6),
        "confusion": cm,
        "goldLabelCounts": dict(sorted(Counter(gold).items())),
        "predictedLabelCounts": dict(sorted(Counter(pred).items())),
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python score-english-core-public-full-classification.py <result.json>")
    if not TASKS.exists() or not ANSWERS.exists():
        raise SystemExit("Build the full classification tasks first.")

    run = json.loads(Path(sys.argv[1]).read_text())
    tasks = [json.loads(line) for line in TASKS.read_text().splitlines() if line.strip()]
    answer_data = json.loads(ANSWERS.read_text())["answers"]
    outputs = {row["id"]: row for row in run.get("outputs", [])}

    by_source: dict[str, list[dict]] = defaultdict(list)
    detail = []

    for task in tasks:
        meta = answer_data[task["id"]]
        got = outputs.get(task["id"])
        predicted_letter = parse_letter(got.get("output", "")) if got else None
        predicted_label = None
        if predicted_letter is not None:
            predicted_label = meta["labelByLetter"].get(predicted_letter)
        valid = predicted_label in (0, 1)
        gold_label = int(meta["goldLabel"])
        correct = bool(valid and predicted_label == gold_label)
        row = {
            "id": task["id"],
            "source": task["source"],
            "dimension": task["dimension"],
            "goldLabel": gold_label,
            "expectedLetter": meta["letter"],
            "predictedLetter": predicted_letter,
            "predictedLabel": predicted_label,
            "correct": correct,
            "status": "scored" if valid else ("missing" if got is None else "invalid_output"),
        }
        detail.append(row)
        by_source[task["source"]].append(row)

    source_reports = {}
    for source, rows in sorted(by_source.items()):
        valid_rows = [row for row in rows if row["status"] == "scored"]
        correct_all = sum(int(row["correct"]) for row in rows)
        complete = len(valid_rows) == len(rows)
        report = {
            "cases": len(rows),
            "validPredictions": len(valid_rows),
            "validOutputCoverage": round(len(valid_rows) / len(rows), 6) if rows else None,
            "accuracyInvalidAsWrong": round(correct_all / len(rows), 6) if rows else None,
            "accuracyInvalidAsWrongWilson95": wilson_interval(correct_all, len(rows)),
            "completeForClassificationMetrics": complete,
        }
        if complete:
            gold = [int(row["goldLabel"]) for row in rows]
            pred = [int(row["predictedLabel"]) for row in rows]
            report.update(binary_metrics(gold, pred))
        else:
            report["classificationMetrics"] = None
            report["reason"] = "MCC/F1/native-distribution classification metrics withheld because one or more outputs are missing/invalid; invalid cases are not silently excluded."
        source_reports[source] = report

    headline = {
        "WiC": {"metric": "accuracy", "value": source_reports.get("WiC", {}).get("accuracy")},
        "CoLA": {"metric": "Matthews correlation coefficient", "value": source_reports.get("CoLA", {}).get("mcc")},
        "PAWS": {"metric": "accuracy", "value": source_reports.get("PAWS", {}).get("accuracy")},
    }

    report = {
        "version": 1,
        "runId": run.get("runId"),
        "model": run.get("model"),
        "adaptation": "zero-shot prompted classification on full locally scoreable validation distributions",
        "headline": headline,
        "bySource": source_reports,
        "notes": [
            "This lane preserves the public validation distribution; it is separate from Pari's balanced public-fast screen.",
            "Prompted zero-shot classification is not identical to the supervised model adaptation used in the original benchmark literature.",
            "CoLA headline reporting uses MCC when all predictions are valid; balanced-screen accuracy must not be called an official CoLA score.",
            "Invalid/missing outputs are never silently dropped from headline classification metrics.",
            "Report exact prompt/adaptation/model/runtime provenance alongside these metrics."
        ],
        "detail": detail,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
