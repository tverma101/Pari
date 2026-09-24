"""Score a result.json from english-core-public-fast.jsonl.

Usage:
    python score-english-core-public-fast.py public-result.json

This remains a prompted screening protocol, not an official native score for
BLiMP/WiC/CoLA/PAWS. Source-level results are the primary view. Invalid/missing
responses count as wrong for screening accuracy but are also reported separately
as output-coverage failures.
"""

import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

from english_core_choice_parser import parse_choice_letter

HERE = Path(__file__).resolve().parent
TASKS = HERE / "english-core-public-fast.jsonl"
ANSWERS = HERE / "english-core-public-fast.answers.json"
MANIFEST = HERE / "english-core-public-fast.manifest.json"
VALID_BINARY_LETTERS = {"A", "B"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    for key, rows in sorted(groups.items()):
        wins = sum(row["score"] for row in rows)
        valid = sum(int(row["status"] == "scored") for row in rows)
        n = len(rows)
        result[key] = {
            "cases": n,
            "correct": wins,
            "validOutputs": valid,
            "validOutputCoverage": round(valid / n, 6) if n else None,
            "accuracyInvalidAsWrong": round(wins / n, 6) if n else None,
            "wilson95InvalidAsWrong": wilson95(wins, n),
        }
    return result


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python score-english-core-public-fast.py <result.json>")
    if not TASKS.exists() or not ANSWERS.exists() or not MANIFEST.exists():
        raise SystemExit("Build public fast tasks first; task, answer, and manifest files are required.")

    result_path = Path(sys.argv[1]).resolve()
    run = json.loads(result_path.read_text())
    tasks = [json.loads(line) for line in TASKS.read_text().splitlines() if line.strip()]
    answers_file = json.loads(ANSWERS.read_text())
    answers = answers_file["answers"]
    manifest = json.loads(MANIFEST.read_text())

    task_ids = [task.get("id") for task in tasks]
    if any(not task_id for task_id in task_ids):
        raise SystemExit("Public-fast task file contains a task without an ID")
    if len(task_ids) != len(set(task_ids)):
        raise SystemExit("Public-fast task file contains duplicate IDs")
    if set(answers) != set(task_ids):
        raise SystemExit("Public-fast answer keys do not exactly match task IDs")
    if int(manifest.get("cases", -1)) != len(tasks):
        raise SystemExit("Public-fast manifest case count does not match task file")

    expected_task_hash = sha256(TASKS)
    if run.get("taskFileSha256") != expected_task_hash:
        raise SystemExit("Result taskFileSha256 does not match english-core-public-fast.jsonl")
    if run.get("taskCount") != len(tasks):
        raise SystemExit("Result taskCount does not match public-fast task count")

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
        raise SystemExit(f"Result contains {len(extra)} IDs not present in the public-fast task file")
    outputs = {row["id"]: row for row in run_outputs}

    by_source = defaultdict(list)
    by_dimension = defaultdict(list)
    by_phenomenon = defaultdict(list)
    by_source_phenomenon = defaultdict(list)
    detail = []

    for task in tasks:
        got = outputs.get(task["id"])
        parsed = parse_choice_letter(got.get("output", "")) if got else None
        predicted = parsed if parsed in VALID_BINARY_LETTERS else None
        expected = answers[task["id"]]
        if expected not in VALID_BINARY_LETTERS:
            raise SystemExit(f"Unexpected non-binary answer key for {task['id']}: {expected}")
        score = int(predicted == expected) if predicted else 0
        phenomenon = task.get("phenomenon") or "unspecified"
        record = {
            "id": task["id"],
            "source": task["source"],
            "dimension": task["dimension"],
            "phenomenon": phenomenon,
            "expected": expected,
            "parsedLetter": parsed,
            "predicted": predicted,
            "score": score,
            "status": "scored" if predicted else ("missing" if got is None else "invalid_output"),
        }
        detail.append(record)
        by_source[task["source"]].append(record)
        by_dimension[task["dimension"]].append(record)
        by_phenomenon[phenomenon].append(record)
        by_source_phenomenon[f"{task['source']}::{phenomenon}"].append(record)

    wins = sum(row["score"] for row in detail)
    valid = sum(int(row["status"] == "scored") for row in detail)
    n = len(detail)
    report = {
        "version": 4,
        "runId": run.get("runId"),
        "model": run.get("model"),
        "cases": n,
        "correct": wins,
        "validOutputs": valid,
        "validOutputCoverage": round(valid / n, 6) if n else None,
        "accuracyInvalidAsWrong": round(wins / n, 6) if n else None,
        "wilson95InvalidAsWrong": wilson95(wins, n),
        "inputs": {
            "resultFile": str(result_path),
            "resultFileSha256": sha256(result_path),
            "taskFileSha256": expected_task_hash,
            "answerFileSha256": sha256(ANSWERS),
            "manifestSha256": sha256(MANIFEST),
            "manifestSources": manifest.get("sources"),
            "resolvedDatasetFingerprints": manifest.get("resolvedDatasetFingerprints"),
            "datasetsLibraryVersion": manifest.get("datasetsLibraryVersion"),
        },
        "bySource": summarize(by_source),
        "byDimension": summarize(by_dimension),
        "byPhenomenon": summarize(by_phenomenon),
        "bySourcePhenomenon": summarize(by_source_phenomenon),
        "notes": [
            "This is a deterministic prompted public-anchor screening subset, not an official full-suite score.",
            "The scorer requires an exact task-file hash/count match and rejects duplicate/extra output IDs before computing the screen.",
            "All current public-fast items are binary A/B choices. A parsed letter outside A/B is an invalid output, not a normal classification prediction.",
            "Invalid/missing outputs count as wrong in screening accuracy and are separately reported through valid-output coverage so refusal/format failures cannot be hidden.",
            "The 95% Wilson intervals quantify binomial screening uncertainty under this fixed sampled set; they do not solve benchmark contamination or distribution-shift concerns.",
            "Compare by-source and per-phenomenon results; do not treat the unweighted overall screening accuracy as the final English Core composite.",
            "The fast-screen sampling distribution is deliberately balanced for WiC/CoLA/PAWS and therefore differs from each benchmark's native/full distribution.",
            "Public-anchor results remain separate from the fresh Pari shadow score to expose possible benchmark memorization/overfitting.",
            "For research-level claims, run benchmark-native official protocols and metrics in addition to this common prompted screen."
        ],
        "detail": detail,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
