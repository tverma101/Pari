#!/usr/bin/env python3
"""Focused regression coverage for the #64 scoreView block in the MJS scorers.

The three MJS English Core score producers (shadow, prompt robustness, choice
order robustness) must publish the same frozen scoreView identity and
provenance block that ``english-core-snapshot-binding.mjs`` reads, derived from
the contract constants frozen in ``english_core_choice_views.py``.

Everything here is CPU-only and fabricated: the fixtures score synthetic
results through the real scorer CLIs against the in-tree benchmark snapshot.
No model, GPU, Kaggle session, install, or network call is involved.

Run: python3 test_mjs_score_view_contract.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from english_core_choice_views import (  # noqa: E402
    ALLOWED_LABEL_CONTRACT_VERSION,
    CONTRACT_FILE,
    DENOMINATOR_POLICY_VERSION,
    PRIMARY_SCREENING_VIEW,
    SCORE_VIEW_METRIC_KEYS,
    VIEW_CONTRACT_VERSION,
    score_choice_views,
    summarize_choice_views,
)

SHADOW_SCORER = "score-english-core.mjs"
PROMPT_SCORER = "score-english-core-prompt-robustness.mjs"
CHOICE_ORDER_SCORER = "score-english-core-choice-order-robustness.mjs"
SCORERS = (SHADOW_SCORER, PROMPT_SCORER, CHOICE_ORDER_SCORER)

# The MJS scorers hash the same two files the Python contract names.
JS_CONTRACT_FILE = "english_core_choice_views.py"
JS_PARSER_FILE = "english-core-choice-parser.mjs"

TASK_FILE_BY_SCORER = {
    SHADOW_SCORER: "english-core-shadow.jsonl",
    PROMPT_SCORER: "english-core-prompt-robustness.jsonl",
    CHOICE_ORDER_SCORER: "english-core-choice-order-robustness.jsonl",
}
MANIFEST_BY_SCORER = {
    SHADOW_SCORER: "english-core-shadow.manifest.json",
    PROMPT_SCORER: "english-core-prompt-robustness.manifest.json",
    CHOICE_ORDER_SCORER: "english-core-choice-order-robustness.manifest.json",
}
EXPECTED_REPORT_VERSION = {SHADOW_SCORER: 9, PROMPT_SCORER: 4, CHOICE_ORDER_SCORER: 3}

VALIDATOR = HERE / "validate-english-core-run.py"
VALIDATOR_MODULE = None


def _load_validator():
    spec = importlib.util.spec_from_file_location("mjs_score_view_validator", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


FAILURES: list[str] = []
CHECKS = 0


def check(condition: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(message)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def synthetic_output(row: dict, index: int) -> str:
    """Mix strict letters, recoverable wrappers, and out-of-set labels."""
    if row.get("generative"):
        return "A fixture candidate for the generative case."
    if index % 3 == 0:
        return "Answer: A"
    if index % 3 == 1:
        return "Z"
    return "A"


def build_synthetic_result(task_file_name: str, run_overrides: dict | None = None) -> Path:
    tasks = HERE / task_file_name
    rows = read_jsonl(tasks)
    generative_metrics = {
        row["id"]: list(row.get("scoring") or [])
        for row in json.loads((HERE / "english-core-shadow.seed.json").read_text(encoding="utf-8"))["cases"]
        if row["dimension"] == "generative_expression"
    }
    outputs = []
    for index, row in enumerate(rows):
        record = {"id": row["id"], "output": synthetic_output(row, index), "latencySeconds": 0.1}
        metrics = generative_metrics.get(row["id"])
        if metrics:
            record["metricScores"] = {name: 0.8 for name in metrics}
            record["metricProvenance"] = {
                "kind": "blinded_human",
                "name": "fixture-rater",
                "protocol": "fixture scoring protocol v1",
                "candidateSelfGrade": False,
            }
        outputs.append(record)

    schema_sha = sha256_file(HERE / "english-core-result-schema.json")
    run = {
        "schemaVersion": 1,
        "runId": "fixture-mjs-score-view",
        "timestamp": "2026-10-02T00:00:00Z",
        "status": "completed",
        "complete": True,
        "completedCount": len(rows),
        "model": {
            "name": "fixture",
            "repoOrName": "org/fixture-model",
            "revision": "a" * 40,
            "artifactSha256": "b" * 64,
            "quantization": "bf16",
            "checkpointType": "instruct",
            "runtime": "llama.cpp",
            "runtimeVersion": "1.0",
            "tokenizerName": "org/fixture-model",
            "chatTemplateSha256": "c" * 64,
        },
        "hardware": {"machine": "cpu", "os": "test"},
        "taskFile": str(tasks),
        "taskFileSha256": sha256_file(tasks),
        "taskCount": len(rows),
        "promptModeRequested": "chat",
        "promptAdaptationModesObserved": ["chat_template"],
        "promptAdaptationDetailsObserved": ["fixture"],
        "decoding": {
            "temperature": 0,
            "topP": 1,
            "topK": 0,
            "maxNewTokens": 16,
            "forcedChoiceMaxNewTokens": 4,
            "seed": 1,
        },
        "outputs": outputs,
        "reproducibility": {
            "benchmarkRevision": "d" * 40,
            "rawOutputSha256": VALIDATOR_MODULE.canonical_outputs_sha256(outputs),
            "resultSchemaVersion": 1,
            "resultSchemaSha256": schema_sha,
            "notes": [],
        },
    }
    for key, value in (run_overrides or {}).items():
        run[key] = value
    path = Path(tempfile.mkdtemp()) / "result.json"
    path.write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
    return path


def score(scorer: str, result_path: Path) -> dict:
    completed = subprocess.run(
        ["node", str(HERE / scorer), str(result_path), "--promotion"],
        capture_output=True,
        text=True,
        check=False,
    )
    check(completed.returncode == 0, f"{scorer} exited {completed.returncode}: {completed.stderr.strip()[:400]}")
    return json.loads(completed.stdout) if completed.returncode == 0 else {}


def bind_with_analysis(score_report: dict) -> dict:
    """Ask english-core-snapshot-binding.mjs to consume the published block."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        score_path = tmp / "score.json"
        score_path.write_text(json.dumps(score_report), encoding="utf-8")
        script = tmp / "bind-score-view.mjs"
        script.write_text(
            "import { requireScoreViewContract, selectScoreView } from "
            f"{json.dumps((HERE / 'english-core-snapshot-binding.mjs').as_uri())};\n"
            "import fs from \"node:fs\";\n"
            f"const score = JSON.parse(fs.readFileSync({json.dumps(str(score_path))}, \"utf8\"));\n"
            "const bound = requireScoreViewContract(score, \"Synthetic score\", "
            f"{{ benchmarkDir: {json.dumps(str(HERE))} }});\n"
            "const strict = selectScoreView({ scoreView: bound.scoreView, requested: \"strict\", "
            "label: \"Synthetic score\" });\n"
            "const recoverable = selectScoreView({ scoreView: bound.scoreView, "
            "requested: \"recoverable_anchored\", label: \"Synthetic score\" });\n"
            "process.stdout.write(JSON.stringify({"
            "available: bound.scoreView.available,"
            "selected: bound.scoreView.selected,"
            "strictMetric: bound.scoreView.strict.metric,"
            "recoverableMetric: bound.scoreView.recoverable.metric,"
            "contractVerified: bound.scoreView.contract.verifiedLocally,"
            "parserVerified: bound.scoreView.parser ? bound.scoreView.parser.verifiedLocally : null,"
            "strictExplicit: strict.explicitlyRequested,"
            "recoverableExplicit: recoverable.explicitlyRequested }));\n",
            encoding="utf-8",
        )
        completed = subprocess.run(["node", str(script)], capture_output=True, text=True, check=False)
        check(
            completed.returncode == 0,
            f"snapshot binding rejected the published scoreView: {completed.stderr.strip()[:400]}",
        )
        return json.loads(completed.stdout) if completed.returncode == 0 else {}


def bind_rejects(score_report: dict, *extra_args: str) -> str:
    """Return the binding error when the artifact must be rejected, else ""."""
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        score_path = tmp / "score.json"
        score_path.write_text(json.dumps(score_report), encoding="utf-8")
        script = tmp / "bind-score-view.mjs"
        script.write_text(
            "import { requireScoreViewContract } from "
            f"{json.dumps((HERE / 'english-core-snapshot-binding.mjs').as_uri())};\n"
            "import fs from \"node:fs\";\n"
            f"const score = JSON.parse(fs.readFileSync({json.dumps(str(score_path))}, \"utf8\"));\n"
            f"requireScoreViewContract(score, \"Synthetic score\", {{ benchmarkDir: {json.dumps(str(HERE))} }});\n",
            encoding="utf-8",
        )
        completed = subprocess.run(["node", str(script)], capture_output=True, text=True, check=False)
        return completed.stderr if completed.returncode != 0 else ""


def assert_frozen_score_view_block(scorer: str, report: dict) -> None:
    view = report.get("scoreView")
    check(isinstance(view, dict), f"{scorer} publishes no scoreView object")
    if not isinstance(view, dict):
        return

    check(
        view.get("parseViewContractVersion") == VIEW_CONTRACT_VERSION,
        f"{scorer} scoreView.parseViewContractVersion drifted from the frozen contract",
    )
    check(
        view.get("denominatorPolicyVersion") == DENOMINATOR_POLICY_VERSION,
        f"{scorer} scoreView.denominatorPolicyVersion drifted from the frozen policy",
    )
    check(
        view.get("allowedLabelContractVersion") == ALLOWED_LABEL_CONTRACT_VERSION,
        f"{scorer} scoreView.allowedLabelContractVersion drifted from the frozen policy",
    )
    check(
        view.get("selected") == PRIMARY_SCREENING_VIEW,
        f"{scorer} scoreView.selected must be the primary screening view",
    )
    check(
        view.get("primaryScreeningView") == PRIMARY_SCREENING_VIEW,
        f"{scorer} scoreView.primaryScreeningView must name the primary screening view",
    )
    check(
        view.get("metricKeys") == dict(SCORE_VIEW_METRIC_KEYS),
        f"{scorer} scoreView.metricKeys must match the frozen per-view metric keys",
    )
    for name, metric in SCORE_VIEW_METRIC_KEYS.items():
        branch = view.get(name)
        check(isinstance(branch, dict), f"{scorer} scoreView.{name} branch is missing")
        if isinstance(branch, dict):
            check(branch.get("name") == name, f"{scorer} scoreView.{name}.name drifted")
            check(branch.get("metric") == metric, f"{scorer} scoreView.{name}.metric drifted")
            check(branch.get("metricKey") == metric, f"{scorer} scoreView.{name}.metricKey drifted")

    check(view.get("contractFile") == CONTRACT_FILE, f"{scorer} scoreView must name {CONTRACT_FILE}")
    check(
        view.get("contractSha256") == sha256_file(HERE / JS_CONTRACT_FILE),
        f"{scorer} scoreView.contractSha256 does not match the on-disk frozen contract bytes",
    )
    check(view.get("parserFile") == JS_PARSER_FILE, f"{scorer} scoreView must name {JS_PARSER_FILE}")
    check(
        view.get("parserSha256") == sha256_file(HERE / JS_PARSER_FILE),
        f"{scorer} scoreView.parserSha256 does not match the on-disk parser bytes",
    )
    check(
        view.get("taskFileSha256") == report.get("taskFileSha256"),
        f"{scorer} scoreView.taskFileSha256 disagrees with the score artifact task bytes",
    )
    check(
        view.get("taskManifestSha256") == sha256_file(HERE / MANIFEST_BY_SCORER[scorer]),
        f"{scorer} scoreView.taskManifestSha256 does not match its manifest bytes",
    )
    check(
        isinstance(view.get("sourceResultSha256"), str) and len(view["sourceResultSha256"]) == 64,
        f"{scorer} scoreView.sourceResultSha256 must pin the scored result bytes",
    )
    check(view.get("sourceRunId") == report.get("runId"), f"{scorer} scoreView.sourceRunId must name the scored run")
    check(report.get("scoreViewsSeparated") is True, f"{scorer} must mark scoreViewsSeparated")


def score_all() -> dict[str, dict]:
    reports = {}
    for scorer in SCORERS:
        report = score(scorer, build_synthetic_result(TASK_FILE_BY_SCORER[scorer]))
        reports[scorer] = report
    return reports


def test_every_mjs_scorer_publishes_the_frozen_score_view_block(reports) -> None:
    for scorer, report in reports.items():
        if report:
            assert_frozen_score_view_block(scorer, report)


def test_analysis_side_consumes_every_mjs_score_view(reports) -> None:
    for scorer, report in reports.items():
        if not report:
            continue
        bound = bind_with_analysis(report)
        check(bound.get("available") is True, f"{scorer} score view is not available to the analysis")
        check(bound.get("selected") == PRIMARY_SCREENING_VIEW, f"{scorer} analysis did not resolve the primary view")
        check(bound.get("strictMetric") == SCORE_VIEW_METRIC_KEYS["strict"], f"{scorer} bound the wrong strict metric")
        check(
            bound.get("recoverableMetric") == SCORE_VIEW_METRIC_KEYS[PRIMARY_SCREENING_VIEW],
            f"{scorer} bound the wrong recoverable metric",
        )
        check(bound.get("contractVerified") is True, f"{scorer} contract bytes were not verifiable")
        check(bound.get("parserVerified") is True, f"{scorer} parser bytes were not verifiable")
        check(bound.get("strictExplicit") is True, f"{scorer} strict view is not selectable")
        check(bound.get("recoverableExplicit") is True, f"{scorer} recoverable view is not selectable")


def test_strict_and_recoverable_views_stay_separate(reports) -> None:
    for scorer, report in reports.items():
        views = report.get("choiceViews")
        check(isinstance(views, dict), f"{scorer} publishes no choiceViews aggregate")
        if not isinstance(views, dict):
            continue
        check(views.get("denominatorPolicy") == DENOMINATOR_POLICY_VERSION, f"{scorer} denominator policy drifted")
        denominator = views.get("fixedDenominator")
        check(isinstance(denominator, int) and denominator > 0, f"{scorer} needs a positive fixed denominator")
        strict = views.get("strictAccuracyFixedDenominator")
        recoverable = views.get("recoverableAccuracyFixedDenominator")
        check(isinstance(strict, (int, float)) and isinstance(recoverable, (int, float)), f"{scorer} must publish both view metrics")
        if isinstance(strict, (int, float)) and isinstance(recoverable, (int, float)):
            check(recoverable > strict, f"{scorer} folded format-recovery gains into strict accuracy")
        recovered_only = views.get("recoverableOnlyCount")
        check(isinstance(recovered_only, int) and recovered_only > 0, f"{scorer} must expose recoverable-only items")
        check(
            views.get("outcomes", {}).get("recoverable_only_correct_format_recovery", 0) <= recovered_only,
            f"{scorer} reports more format-recovery gains than it has recoverable-only items",
        )
        check(views.get("excludedRuntimeUnqualified") == 0, f"{scorer} excluded runtime-qualified items")


def test_javascript_view_aggregate_matches_the_python_contract(reports) -> None:
    """The MJS aggregate must equal english_core_choice_views over the same rows.

    The MJS scorers re-implement the frozen policy in JavaScript. This recomputes
    the aggregate with the Python contract module from the same per-item rows the
    scorer published, so a policy drift on either side fails here instead of
    silently producing two different numbers for one view.
    """
    report = reports.get(SHADOW_SCORER, {})
    detail = [row for row in report.get("detail", []) if row.get("forcedChoiceViewsApplicable")]
    check(bool(detail), "shadow score carries no forced-choice view rows to compare")
    if not detail:
        return

    task_rows = {row["id"]: row for row in read_jsonl(HERE / TASK_FILE_BY_SCORER[SHADOW_SCORER])}
    python_rows = []
    for row in detail:
        published = row["choiceViews"]
        rebuilt = score_choice_views(
            published["rawOutput"],
            allowed_choices=published["allowedChoices"],
            gold=published["goldLabelForComparison"],
            missing=published["outcome"] == "missing_output",
            finish_reason=published["finishReason"],
            truncated=published["truncatedOutput"],
        )
        for key in (
            "strictParsedChoice",
            "recoverableParsedChoice",
            "strictProtocolValid",
            "recoverableProtocolValid",
            "strictCorrect",
            "recoverableCorrect",
            "viewsDisagree",
            "recoveredOnly",
            "outcome",
            "choiceStatus",
        ):
            check(
                rebuilt[key] == published[key],
                f"JS/Python disagree on {key} for {row.get('id')}",
            )
        python_rows.append(rebuilt)
        check(
            published["allowedChoices"] == task_rows[row["id"]]["allowedChoices"],
            f"{row.get('id')} view allowedChoices drifted from the frozen task set",
        )

    python_summary = summarize_choice_views(python_rows)
    js_summary = report["choiceViews"]
    for key in (
        "denominatorPolicy",
        "parseViewContractVersion",
        "allowedLabelContractVersion",
        "fixedDenominator",
        "excludedRuntimeUnqualified",
        "strictAccuracyFixedDenominator",
        "recoverableAccuracyFixedDenominator",
        "strictAccuracyGivenStrictValid",
        "recoverableAccuracyGivenRecoverableValid",
        "recoverableOnlyCount",
        "strictRecoverableDisagreementCount",
    ):
        check(
            js_summary.get(key) == python_summary.get(key),
            f"JS/Python aggregate drift on {key}: {js_summary.get(key)!r} vs {python_summary.get(key)!r}",
        )
    check(js_summary.get("outcomes") == python_summary.get("outcomes"), "JS/Python outcome counts drifted")


def test_analysis_fails_closed_on_a_drifted_score_view(reports) -> None:
    """A half-declared or drifted view block must be rejected, never completed."""
    base = reports.get(SHADOW_SCORER, {})
    if not base:
        return

    drifted = json.loads(json.dumps(base))
    drifted["scoreView"]["denominatorPolicyVersion"] = "some-other-denominator-v9"
    check(
        "denominator policy" in bind_rejects(drifted),
        "the analysis must reject a drifted denominator policy",
    )

    drifted = json.loads(json.dumps(base))
    drifted["scoreView"]["metricKeys"]["strict"] = "strictAccuracyFixedDenominatorV2"
    check("strict" in bind_rejects(drifted), "the analysis must reject an unknown strict metric key")

    drifted = json.loads(json.dumps(base))
    del drifted["scoreView"]["contractSha256"]
    check("contractSha256" in bind_rejects(drifted), "the analysis must reject an unverifiable contract hash")

    drifted = json.loads(json.dumps(base))
    drifted["scoreView"]["taskFileSha256"] = "0" * 64
    check("measure" in bind_rejects(drifted) or "taskFile" in bind_rejects(drifted), "the analysis must reject a view measured over other task bytes")

    partial = json.loads(json.dumps(base))
    partial["scoreView"] = {"parseViewContractVersion": VIEW_CONTRACT_VERSION}
    check("denominator policy" in bind_rejects(partial), "the analysis must reject a partial view contract")


def test_shadow_scorer_keeps_legacy_fields_measuring_the_recoverable_view(reports) -> None:
    report = reports.get(SHADOW_SCORER, {})
    detail = [row for row in report.get("detail", []) if row.get("forcedChoiceViewsApplicable")]
    check(bool(detail), "shadow score carries no forced-choice detail rows")
    for row in detail:
        views = row.get("choiceViews")
        check(isinstance(views, dict), f"shadow detail row {row.get('id')} publishes no choiceViews")
        if not isinstance(views, dict):
            continue
        check(
            row.get("parsedLetter") == views.get("recoverableParsedChoice"),
            f"shadow detail row {row.get('id')} legacy parsedLetter no longer matches the recoverable view",
        )
        check(
            row.get("predicted") == views.get("recoverableParsedChoice"),
            f"shadow detail row {row.get('id')} legacy predicted no longer matches the recoverable view",
        )
        if views.get("recoverableCorrect") is True and views.get("strictCorrect") is not True:
            check(
                views.get("outcome") == "recoverable_only_correct_format_recovery",
                f"shadow detail row {row.get('id')} mislabelled a format-recovery gain",
            )


def test_generative_cases_are_outside_the_forced_choice_views(reports) -> None:
    report = reports.get(SHADOW_SCORER, {})
    generative = [row for row in report.get("detail", []) if row.get("dimension") == "generative_expression"]
    check(bool(generative), "shadow score carries no generative detail rows")
    for row in generative:
        check(row.get("forcedChoiceViewsApplicable") is False, f"generative row {row.get('id')} claims forced-choice views")
        check("choiceViews" not in row, f"generative row {row.get('id')} carries forced-choice view parses")


def test_runtime_unqualified_runs_leave_the_denominator() -> None:
    path = build_synthetic_result(
        TASK_FILE_BY_SCORER[SHADOW_SCORER],
        {"status": "failed", "complete": False, "completedCount": 1, "runId": "fixture-failed"},
    )
    report = score(SHADOW_SCORER, path)
    if not report:
        return
    runtime = report.get("runtimeQualification", {})
    check(runtime.get("runtimeQualified") is False, "a failed run must not be runtime qualified")
    check(
        runtime.get("runtimeQualificationReason") == "run_status_failed",
        "the runtime-unqualified reason must name the failing run status",
    )
    views = report.get("choiceViews", {})
    check(views.get("fixedDenominator") == 0, "a runtime-unqualified run must leave the denominator empty")
    check(views.get("excludedRuntimeUnqualified", 0) > 0, "a runtime-unqualified run must be reported as excluded")
    check(views.get("strictAccuracyFixedDenominator") is None, "a runtime-unqualified run must not publish a strict zero")
    check(
        views.get("recoverableAccuracyFixedDenominator") is None,
        "a runtime-unqualified run must not publish a recoverable zero",
    )


def test_legacy_key_limitations_are_named_not_hidden(reports) -> None:
    for scorer, report in reports.items():
        aliases = report.get("legacyScoreViewAliases")
        check(isinstance(aliases, dict), f"{scorer} publishes no legacyScoreViewAliases")
        if not isinstance(aliases, dict):
            continue
        check(bool(aliases), f"{scorer} legacyScoreViewAliases is empty")
        for key, named_view in aliases.items():
            check(
                named_view == PRIMARY_SCREENING_VIEW,
                f"{scorer} legacy key {key} is not named as the recoverable anchored view",
            )


def test_scorer_versions_advanced_with_the_contract() -> None:
    for scorer, version in EXPECTED_REPORT_VERSION.items():
        text = (HERE / scorer).read_text(encoding="utf-8")
        match = re.search(r"^\s*version:\s*(\d+),\s*$", text, flags=re.MULTILINE)
        check(match is not None, f"{scorer} declares no integer report version")
        if match:
            check(int(match.group(1)) == version, f"{scorer} report version is {match.group(1)}, expected {version}")


def main() -> int:
    global VALIDATOR_MODULE
    VALIDATOR_MODULE = _load_validator()
    reports = score_all()
    test_every_mjs_scorer_publishes_the_frozen_score_view_block(reports)
    test_analysis_side_consumes_every_mjs_score_view(reports)
    test_strict_and_recoverable_views_stay_separate(reports)
    test_javascript_view_aggregate_matches_the_python_contract(reports)
    test_analysis_fails_closed_on_a_drifted_score_view(reports)
    test_shadow_scorer_keeps_legacy_fields_measuring_the_recoverable_view(reports)
    test_generative_cases_are_outside_the_forced_choice_views(reports)
    test_runtime_unqualified_runs_leave_the_denominator()
    test_legacy_key_limitations_are_named_not_hidden(reports)
    test_scorer_versions_advanced_with_the_contract()

    for scorer in SCORERS:
        report = reports.get(scorer) or {}
        views = report.get("choiceViews", {}) if report else {}
        print(
            f"{scorer}: scoreView={'yes' if report.get('scoreView') else 'NO'} "
            f"contract={(report.get('scoreView') or {}).get('contractSha256', '-')[:12]} "
            f"denominator={views.get('fixedDenominator')} "
            f"strict={views.get('strictAccuracyFixedDenominator')} "
            f"recoverable={views.get('recoverableAccuracyFixedDenominator')}"
        )
    if FAILURES:
        for failure in FAILURES:
            print(f"FAIL {failure}")
        print(f"{len(FAILURES)} of {CHECKS} MJS score-view checks failed")
        return 1
    print(f"OK: {CHECKS} MJS score-view checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
