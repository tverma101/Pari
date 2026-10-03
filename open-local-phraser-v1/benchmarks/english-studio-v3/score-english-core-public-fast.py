"""Score a result.json from english-core-public-fast.jsonl.

Usage:
    python score-english-core-public-fast.py public-result.json

This remains a prompted screening protocol, not an official native score for
BLiMP/WiC/CoLA/PAWS. Source-level results are the primary view.

Issue #64: the lane publishes strict letter-only and recoverable anchored
accuracy as two separate frozen views over one fixed denominator, per item and
per group. A protocol failure is a zero for both views and stays labelled a
protocol failure; a runtime-unqualified run is excluded from the denominator
entirely so infrastructure state can never become an English zero. The legacy
``accuracyInvalidAsWrong`` key is kept for existing consumers and now names the
view it measures (recoverable anchored) instead of standing in for strict
accuracy.
"""

import hashlib
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

from english_core_choice_parser import allowed_choices_from_task
from english_core_choice_views import (
    PRIMARY_SCREENING_VIEW,
    run_runtime_qualification,
    score_choice_views,
    score_view_contract,
    summarize_choice_views,
    with_score_view,
)
from english_core_result_contract import validate_result

HERE = Path(__file__).resolve().parent
CONTRACT = HERE / "english_core_choice_views.py"
TASKS = HERE / "english-core-public-fast.jsonl"
ANSWERS = HERE / "english-core-public-fast.answers.json"
MANIFEST = HERE / "english-core-public-fast.manifest.json"


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
    """Per-group strict/recoverable views plus the pre-#64 legacy keys.

    The legacy keys mirror the recoverable anchored view, which is what the
    single ``parse_choice_letter`` call produced before issue #64 existed.
    """
    result = {}
    for key, rows in sorted(groups.items()):
        views = summarize_choice_views(rows)
        wins = views["recoverableCorrectCount"]
        valid = views["recoverableValidOutputCount"]
        n = views["fixedDenominator"]
        group = {
            # `cases` keeps its pre-#64 meaning: every evaluated row. The
            # fixed denominator is named separately so a reader can never mistake
            # one for the other.
            "cases": len(rows),
            "fixedDenominator": n,
            "excludedRuntimeUnqualified": views["excludedRuntimeUnqualified"],
            "correct": wins,
            "validOutputs": valid,
            "choiceViews": views,
            "strictCorrect": views["strictCorrectCount"],
            "recoverableCorrect": views["recoverableCorrectCount"],
            "validOutputCoverage": views["recoverableValidOutputCoverage"],
            "accuracyInvalidAsWrong": views["recoverableAccuracyFixedDenominator"],
            "wilson95InvalidAsWrong": wilson95(wins, n),
            "accuracyInvalidAsWrongScoreView": PRIMARY_SCREENING_VIEW,
            "validOutputCoverageScoreView": PRIMARY_SCREENING_VIEW,
        }
        result[key] = group
    return result


def main() -> None:
    flags = {arg for arg in sys.argv[1:] if arg.startswith("--")}
    paths = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    if len(paths) != 1 or flags - {"--promotion", "--compat-legacy-v0"}:
        raise SystemExit("Usage: python score-english-core-public-fast.py <result.json> [--promotion | --compat-legacy-v0]")
    if not TASKS.exists() or not ANSWERS.exists() or not MANIFEST.exists():
        raise SystemExit("Build public fast tasks first; task, answer, and manifest files are required.")

    result_path = Path(paths[0]).resolve()
    validation = validate_result(result_path, promotion="--promotion" in flags, compat_legacy_v0="--compat-legacy-v0" in flags)
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
    runtime = run_runtime_qualification(run)

    for task in tasks:
        got = outputs.get(task["id"])
        expected = answers[task["id"]]
        allowed_choices = allowed_choices_from_task(task)
        if allowed_choices is None:
            raise SystemExit(
                f"Public-fast task {task['id']} does not freeze allowedChoices; "
                "the issue #64 strict/recoverable views require the frozen label contract."
            )
        if expected not in allowed_choices:
            raise SystemExit(f"Answer key {expected} for {task['id']} is outside its frozen allowedChoices")
        views = score_choice_views(
            got.get("output", "") if got else "",
            task=task,
            gold=expected,
            finish_reason=got.get("finishReason") if got else None,
            truncated=bool(got.get("truncated")) if got else False,
            missing=got is None,
            runtime_unqualified=not runtime["runtimeQualified"],
        )
        phenomenon = task.get("phenomenon") or "unspecified"
        record = {
            "id": task["id"],
            "source": task["source"],
            "dimension": task["dimension"],
            "phenomenon": phenomenon,
            "expected": expected,
            # Pre-#64 keys, preserved so existing consumers keep working. They
            # are the recoverable anchored view, not strict letter-only.
            "parsedLetter": views["recoverableParsedChoice"],
            "predicted": views["recoverableParsedChoice"],
            "score": int(views["recoverableCorrect"] is True),
            "status": (
                "scored"
                if views["recoverableProtocolValid"]
                else ("missing" if got is None else "invalid_output")
            ),
            # Issue #64 per-item views. Both are always present and never merged.
            "choiceViews": views,
            "strictParsedChoice": views["strictParsedChoice"],
            "recoverableParsedChoice": views["recoverableParsedChoice"],
            "strictProtocolValid": views["strictProtocolValid"],
            "recoverableProtocolValid": views["recoverableProtocolValid"],
            "strictCorrect": views["strictCorrect"],
            "recoverableCorrect": views["recoverableCorrect"],
            "viewsDisagree": views["viewsDisagree"],
            "outcome": views["outcome"],
        }
        detail.append(record)
        by_source[task["source"]].append(record)
        by_dimension[task["dimension"]].append(record)
        by_phenomenon[phenomenon].append(record)
        by_source_phenomenon[f"{task['source']}::{phenomenon}"].append(record)

    views_summary = summarize_choice_views(detail)
    wins = views_summary["recoverableCorrectCount"]
    valid = views_summary["recoverableValidOutputCount"]
    n = views_summary["fixedDenominator"]
    report = {
        "version": 5,
        "schemaVersion": 1,
        "artifactType": "pari.english-core.public-fast-score",
        "inputResultSchema": validation.get("schemaValidation"),
        "runId": run.get("runId"),
        "model": run.get("model"),
        # Mirrors the shadow scorer's top-level task binding so a #64 score view
        # can be reconciled against the exact model-visible task bytes.
        "taskFile": str(TASKS),
        "taskFileSha256": expected_task_hash,
        "cases": len(detail),
        "fixedDenominator": n,
        "excludedRuntimeUnqualified": views_summary["excludedRuntimeUnqualified"],
        "runtimeQualification": runtime,
        "choiceViews": views_summary,
        "strictCorrect": views_summary["strictCorrectCount"],
        "recoverableCorrect": views_summary["recoverableCorrectCount"],
        "correct": wins,
        "validOutputs": valid,
        "validOutputCoverage": views_summary["recoverableValidOutputCoverage"],
        "accuracyInvalidAsWrong": views_summary["recoverableAccuracyFixedDenominator"],
        "wilson95InvalidAsWrong": wilson95(wins, n),
        "inputs": {
            "resultFile": str(result_path),
            "resultFileSha256": sha256(result_path),
            "taskFileSha256": expected_task_hash,
            "taskManifestSha256": sha256(MANIFEST),
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
            "Issue #64: strictAccuracyFixedDenominator and recoverableAccuracyFixedDenominator are separate views over one fixed denominator; neither substitutes for the other and a recoverable-only gain is never reported as a generation gain.",
            "Invalid/missing outputs count as wrong in both views and are separately reported through coverage and per-item outcomes so refusal/format failures cannot be hidden.",
            "A runtime-unqualified or short run is excluded from the denominator and reported under runtimeQualification instead of becoming an English zero.",
            "The 95% Wilson intervals quantify binomial screening uncertainty under this fixed sampled set; they do not solve benchmark contamination or distribution-shift concerns.",
            "Compare by-source and per-phenomenon results; do not treat the unweighted overall screening accuracy as the final English Core composite.",
            "The fast-screen sampling distribution is deliberately balanced for WiC/CoLA/PAWS and therefore differs from each benchmark's native/full distribution.",
            "Public-anchor results remain separate from the fresh Pari shadow score to expose possible benchmark memorization/overfitting.",
            "For research-level claims, run benchmark-native official protocols and metrics in addition to this common prompted screen."
        ],
        "detail": detail,
    }
    with_score_view(
        report,
        score_view_contract(
            contract_path=CONTRACT,
            task_file_sha256=expected_task_hash,
            task_manifest_sha256=sha256(MANIFEST),
            source_result_sha256=sha256(result_path),
            source_run_id=run.get("runId"),
        ),
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
