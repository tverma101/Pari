"""Score the full-distribution prompted WiC / CoLA / PAWS lane.

Usage:
    python score-english-core-public-full-classification.py result.json

Important:
- This is prompted zero-shot classification on the benchmark distribution.
- It is not identical to a supervised benchmark-native model adaptation.
- CoLA reports MCC only when every item has a valid class prediction; invalid or
  missing outputs are never silently dropped.
- The scorer binds itself to the exact generated task/answer files by SHA-256 and
  rejects duplicate/extra outputs rather than silently taking the last record.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

from english_core_choice_parser import parse_choice_letter

HERE = Path(__file__).resolve().parent
TASKS = HERE / "english-core-public-full-classification.jsonl"
ANSWERS = HERE / "english-core-public-full-classification.answers.json"
MANIFEST = HERE / "english-core-public-full-classification.manifest.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def mcc_sklearn_convention(cm: dict[str, int]) -> float:
    """Binary MCC with the zero-denominator convention used by sklearn.

    GLUE/CoLA tooling commonly delegates to sklearn.metrics.matthews_corrcoef.
    Scikit-learn returns 0.0 for degenerate constant-class predictions where the
    denominator is zero. We reproduce that convention without adding a runtime
    sklearn dependency to this scorer.
    """
    tp, tn, fp, fn = cm["tp"], cm["tn"], cm["fp"], cm["fn"]
    denom = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
    if denom == 0:
        return 0.0
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
        "mcc": round(mcc_sklearn_convention(cm), 6) if gold else None,
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
    if not TASKS.exists() or not ANSWERS.exists() or not MANIFEST.exists():
        raise SystemExit("Build the full classification tasks first; task, answer, and manifest files are required.")

    result_path = Path(sys.argv[1]).resolve()
    run = json.loads(result_path.read_text())
    tasks = [json.loads(line) for line in TASKS.read_text().splitlines() if line.strip()]
    answer_file = json.loads(ANSWERS.read_text())
    answer_data = answer_file["answers"]
    manifest = json.loads(MANIFEST.read_text())

    task_ids = [task["id"] for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise SystemExit("Public-full task file contains duplicate IDs")
    if set(answer_data) != set(task_ids):
        raise SystemExit("Public-full answer keys do not exactly match task IDs")
    if int(manifest.get("cases", -1)) != len(tasks):
        raise SystemExit("Public-full manifest case count does not match task file")

    expected_task_hash = sha256(TASKS)
    run_task_hash = run.get("taskFileSha256")
    if run_task_hash != expected_task_hash:
        raise SystemExit("Result taskFileSha256 does not match english-core-public-full-classification.jsonl")
    if run.get("taskCount") != len(tasks):
        raise SystemExit("Result taskCount does not match public-full task count")

    run_outputs = run.get("outputs", [])
    if not isinstance(run_outputs, list):
        raise SystemExit("Result outputs is not an array")
    output_ids = [row.get("id") for row in run_outputs if isinstance(row, dict)]
    if len(output_ids) != len(run_outputs):
        raise SystemExit("Result contains a non-object output row")
    if any(not value for value in output_ids):
        raise SystemExit("Result contains an output without an ID")
    if len(output_ids) != len(set(output_ids)):
        raise SystemExit("Result contains duplicate output IDs")
    extra = sorted(set(output_ids) - set(task_ids))
    if extra:
        raise SystemExit(f"Result contains {len(extra)} IDs not present in the public-full task file")
    outputs = {row["id"]: row for row in run_outputs}

    by_source: dict[str, list[dict]] = defaultdict(list)
    detail = []

    for task in tasks:
        meta = answer_data[task["id"]]
        got = outputs.get(task["id"])
        predicted_letter = parse_choice_letter(got.get("output", "")) if got else None
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
        "version": 3,
        "runId": run.get("runId"),
        "model": run.get("model"),
        "adaptation": "zero-shot prompted classification on full locally scoreable validation distributions",
        "inputs": {
            "resultFile": str(result_path),
            "resultFileSha256": sha256(result_path),
            "taskFile": str(TASKS),
            "taskFileSha256": expected_task_hash,
            "answerFileSha256": sha256(ANSWERS),
            "manifestSha256": sha256(MANIFEST),
            "manifestSources": manifest.get("sources"),
            "resolvedDatasetFingerprints": manifest.get("resolvedDatasetFingerprints"),
            "datasetsLibraryVersion": manifest.get("datasetsLibraryVersion"),
        },
        "headline": headline,
        "bySource": source_reports,
        "notes": [
            "This lane preserves the public validation distribution; it is separate from Pari's balanced public-fast screen.",
            "The scorer requires an exact task-file hash/count match and rejects duplicate or extra output IDs before computing metrics.",
            "Missing/invalid expected outputs remain visible as coverage failures and prevent MCC/F1/native-distribution headline metrics from being computed; they are never silently dropped.",
            "The shared choice parser accepts only unambiguous letter forms such as A, A., Answer: A, The answer is A, or Option A; free-form prose remains invalid.",
            "Prompted zero-shot classification is not identical to the supervised model adaptation used in the original benchmark literature.",
            "CoLA headline reporting uses the standard GLUE MCC convention: Hugging Face GLUE and other established GLUE tooling delegate to sklearn.metrics.matthews_corrcoef; zero-denominator/constant-prediction cases therefore map to MCC 0.0 rather than an undefined score.",
            "Balanced-screen accuracy must not be called an official CoLA score.",
            "Report exact prompt/adaptation/model/runtime/source provenance alongside these metrics."
        ],
        "researchReferences": {
            "WiC": "https://aclanthology.org/N19-1128/",
            "CoLA": "https://aclanthology.org/Q19-1040/",
            "PAWS": "https://aclanthology.org/N19-1131/",
            "GLUE_metric_implementation": "https://github.com/huggingface/evaluate/blob/main/metrics/glue/glue.py"
        },
        "detail": detail,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
