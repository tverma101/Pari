#!/usr/bin/env python3
"""Focused tests for the frozen strict/recoverable forced-choice score views (#64).

Covers the per-item parallel views, the fixed-denominator aggregates, the
runtime-unqualified exclusion, gold-independent parsing, the scorer-reported
score-view contract, and Python/JS parser parity over the shared fixture file.
Nothing here reaches the network, a GPU, or a real run artifact.
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from english_core_choice_parser import parse_choice  # noqa: E402
from english_core_choice_views import (  # noqa: E402
    ALLOWED_LABEL_CONTRACT_VERSION,
    DENOMINATOR_POLICY_VERSION,
    OUTCOME_AMBIGUOUS,
    OUTCOME_INVALID_PROTOCOL,
    OUTCOME_MISSING_OUTPUT,
    OUTCOME_RECOVERABLE_ONLY_CORRECT,
    OUTCOME_RUNTIME_UNQUALIFIED,
    OUTCOME_STRICT_AND_RECOVERABLE_CORRECT,
    OUTCOME_STRICT_AND_RECOVERABLE_WRONG,
    OUTCOME_TRUNCATED,
    PRIMARY_SCREENING_VIEW,
    SCORE_VIEW_METRIC_KEYS,
    VIEW_CONTRACT_VERSION,
    legacy_view_aliases,
    run_runtime_qualification,
    score_choice_views,
    score_view_contract,
    summarize_choice_views,
    with_score_view,
)

FIXTURES = json.loads((HERE / "english-core-choice-view-fixtures.json").read_text())
CASES = {case["id"]: case for case in FIXTURES["cases"]}


def _view(case_id: str, *, gold=None, **kwargs) -> dict:
    case = CASES[case_id]
    return score_choice_views(
        case["raw"],
        allowed_choices=case["allowedChoices"],
        gold=case["gold"] if gold is None else gold,
        **kwargs,
    )


def test_contract_constants_match_fixture_declarations() -> None:
    assert VIEW_CONTRACT_VERSION == FIXTURES["viewContractVersion"]
    assert DENOMINATOR_POLICY_VERSION == FIXTURES["denominatorPolicy"]
    assert ALLOWED_LABEL_CONTRACT_VERSION == FIXTURES["allowedLabelContractVersion"]
    assert SCORE_VIEW_METRIC_KEYS["strict"] == "strictAccuracyFixedDenominator"
    assert SCORE_VIEW_METRIC_KEYS[PRIMARY_SCREENING_VIEW] == "recoverableAccuracyFixedDenominator"


def test_python_parser_matches_fixture_projection_per_case() -> None:
    for case in FIXTURES["cases"]:
        parsed = parse_choice(case["raw"], case["allowedChoices"])
        for json_key, attribute in (
            ("letter", "letter"),
            ("anchoredLabel", "anchored_label"),
            ("invalidOptionLabel", "invalid_option_label"),
        ):
            assert getattr(parsed, attribute) == case[json_key], (case["id"], json_key)
        if case.get("knownParserStatusDivergence"):
            # The parity divergence between the Python and JS parsers on this one
            # input is a shared-parser issue (#44), not a view-contract issue. Both
            # sides still resolve no choice, which is what the view contract needs.
            assert parsed.status == case["pythonStatus"]
        else:
            assert parsed.status == case["status"], case["id"]


def test_strict_and_recoverable_views_are_separate_per_item() -> None:
    for case in FIXTURES["cases"]:
        view = _view(case["id"])
        for key in (
            "strictParsedChoice",
            "recoverableParsedChoice",
            "strictProtocolValid",
            "recoverableProtocolValid",
            "strictCorrect",
            "recoverableCorrect",
            "viewsDisagree",
            "outcome",
        ):
            assert view[key] == case[key], (case["id"], key, view[key], case[key])
        # Raw output and the frozen allowed set are always preserved per item.
        assert view["rawOutput"] == case["raw"]
        assert view["allowedChoices"] == case["allowedChoices"]
        assert view["allowedChoicesFrozen"] is True
        # A correct recoverable answer never mutates strict correctness.
        if view["recoverableCorrect"] and not view["strictCorrect"]:
            assert view["outcome"] == OUTCOME_RECOVERABLE_ONLY_CORRECT
            assert view["strictParsedChoice"] is None
        if view["strictCorrect"]:
            assert view["recoverableCorrect"] is True


def test_issue_case_letter_only_and_answer_wrapper() -> None:
    # Issue test 1 & 3: a bare letter is both-valid; "Answer: A" is strictly
    # invalid yet recoverable as A.
    bare = _view("bare-letter-allowed")
    assert bare["strictProtocolValid"] and bare["recoverableProtocolValid"]
    assert bare["outcome"] == OUTCOME_STRICT_AND_RECOVERABLE_CORRECT

    wrapped = _view("answer-wrapper-recoverable-only")
    assert wrapped["strictProtocolValid"] is False
    assert wrapped["recoverableProtocolValid"] is True
    assert wrapped["strictParsedChoice"] is None
    assert wrapped["recoverableParsedChoice"] == "A"
    assert wrapped["outcome"] == OUTCOME_RECOVERABLE_ONLY_CORRECT


def test_issue_ambiguity_never_chooses_one() -> None:
    for case_id in ("ambiguous-two-labels", "ambiguous-two-labels-including-gold"):
        view = _view(case_id)
        assert view["strictParsedChoice"] is None
        assert view["recoverableParsedChoice"] is None
        assert view["strictCorrect"] is False
        assert view["recoverableCorrect"] is False


def test_issue_impossible_label_invalid_in_both_views() -> None:
    for case_id in ("impossible-label-both-views-invalid", "impossible-label-inside-wrapper-invalid"):
        view = _view(case_id)
        assert view["strictProtocolValid"] is False
        assert view["recoverableProtocolValid"] is False
        assert view["invalidOptionLabelStatus"] is True
        assert view["outcome"] == OUTCOME_INVALID_PROTOCOL


def test_issue_wrong_allowed_choice_is_a_linguistic_miss_not_a_protocol_failure() -> None:
    view = _view("allowed-choice-selected-wrongly")
    assert view["strictProtocolValid"] and view["recoverableProtocolValid"]
    assert view["strictCorrect"] is False and view["recoverableCorrect"] is False
    assert view["outcome"] == OUTCOME_STRICT_AND_RECOVERABLE_WRONG


def test_fixed_denominator_aggregate_matches_fixture() -> None:
    for aggregate in FIXTURES["aggregateCases"]:
        rows = [_view(case_id) for case_id in aggregate["caseIds"]]
        summary = summarize_choice_views(rows)
        assert summary["fixedDenominator"] == aggregate["fixedDenominator"]
        for key in (
            "excludedRuntimeUnqualified",
            "strictValidOutputCount",
            "strictCorrectCount",
            "strictAccuracyFixedDenominator",
            "strictValidOutputCoverage",
            "recoverableValidOutputCount",
            "recoverableCorrectCount",
            "recoverableAccuracyFixedDenominator",
            "recoverableValidOutputCoverage",
            "strictRecoverableDisagreementCount",
            "recoverableOnlyCount",
            "invalidOptionLabelCount",
        ):
            assert summary[key] == aggregate[key], (aggregate["id"], key, summary[key], aggregate[key])
        for outcome, count in aggregate["outcomes"].items():
            assert summary["outcomes"][outcome] == count, (aggregate["id"], outcome)


def test_invalid_strict_output_is_a_zero_under_the_fixed_denominator() -> None:
    # Issue test 8: the invalid item still occupies one denominator slot and is a
    # zero for both views, while remaining labelled a protocol failure.
    rows = [
        _view("bare-letter-allowed"),
        _view("impossible-label-both-views-invalid"),
    ]
    summary = summarize_choice_views(rows)
    assert summary["fixedDenominator"] == 2
    assert summary["strictCorrectCount"] == 1
    assert summary["strictAccuracyFixedDenominator"] == 0.5
    assert summary["recoverableCorrectCount"] == 1
    assert summary["recoverableAccuracyFixedDenominator"] == 0.5
    assert summary["outcomes"][OUTCOME_INVALID_PROTOCOL] == 1


def test_bonsai_recovery_delta_keeps_strict_view_unchanged() -> None:
    # Issue test 7 / replay regression: the recoverable view improves while the
    # strict view does not move, and no gold-guided repair is involved.
    delta = FIXTURES["bonsaiRecoveryDelta"]
    rows = [_view(case_id) for case_id in delta["caseIds"]]
    summary = summarize_choice_views(rows)
    assert summary["fixedDenominator"] == delta["fixedDenominator"]
    assert summary["strictAccuracyFixedDenominator"] == delta["strictAccuracyFixedDenominator"]
    assert summary["recoverableAccuracyFixedDenominator"] == delta["recoverableAccuracyFixedDenominator"]
    assert summary["recoverableAccuracyFixedDenominator"] > summary["strictAccuracyFixedDenominator"]
    assert summary["recoverableOnlyCount"] == delta["recoverableOnlyCount"]


def test_parsing_never_depends_on_gold() -> None:
    # The same raw output produces identical parses regardless of the gold label:
    # no gold-guided parse selection or repair is representable.
    case = CASES["answer-wrapper-recoverable-only"]
    for gold in ("A", "B", None):
        view = score_choice_views(
            case["raw"],
            allowed_choices=case["allowedChoices"],
            gold=gold,
        )
        assert view["strictParsedChoice"] is None
        assert view["recoverableParsedChoice"] == "A"
        assert view["choiceStatus"] == "recoverable_allowed_choice"
    # A gold of None leaves correctness not-evaluable rather than a false zero.
    view = score_choice_views(case["raw"], allowed_choices=case["allowedChoices"], gold=None)
    assert view["strictCorrect"] is None
    assert view["recoverableCorrect"] is None


def test_missing_and_runtime_unqualified_are_not_english_zeros() -> None:
    # Missing output is an in-denominator protocol failure.
    missing = score_choice_views("", allowed_choices=["A", "B"], gold="A", missing=True)
    assert missing["outcome"] == OUTCOME_MISSING_OUTPUT
    assert missing["strictCorrect"] is False and missing["recoverableCorrect"] is False

    # Runtime-unqualified is excluded from the denominator entirely.
    unqualified = score_choice_views("A", allowed_choices=["A", "B"], gold="A", runtime_unqualified=True)
    assert unqualified["outcome"] == OUTCOME_RUNTIME_UNQUALIFIED
    assert unqualified["strictCorrect"] is None
    assert unqualified["recoverableCorrect"] is None
    summary = summarize_choice_views([missing, unqualified])
    assert summary["fixedDenominator"] == 1  # only the in-denominator missing item
    assert summary["excludedRuntimeUnqualified"] == 1


def test_run_runtime_qualification_rejects_short_or_failed_runs() -> None:
    assert run_runtime_qualification({"status": "completed", "complete": True, "completedCount": 10, "taskCount": 10})["runtimeQualified"] is True
    short = run_runtime_qualification({"status": "completed", "complete": True, "completedCount": 9, "taskCount": 10})
    assert short["runtimeQualified"] is False
    assert "completed_count" in short["runtimeQualificationReason"]
    failed = run_runtime_qualification({"status": "failed"})
    assert failed["runtimeQualified"] is False
    assert failed["runtimeQualificationReason"] == "run_status_failed"
    incomplete = run_runtime_qualification({"status": "completed", "complete": False})
    assert incomplete["runtimeQualified"] is False


def test_truncated_output_is_labelled_without_losing_a_committed_choice() -> None:
    truncated_no_choice = score_choice_views("A bec", allowed_choices=["A", "B"], gold="A", truncated=True)
    assert truncated_no_choice["outcome"] == OUTCOME_TRUNCATED
    truncated_with_choice = score_choice_views("A", allowed_choices=["A", "B"], gold="A", finish_reason="length")
    assert truncated_with_choice["truncatedOutput"] is True
    # A truncated output that still committed to an allowed label keeps its correctness.
    assert truncated_with_choice["outcome"] == OUTCOME_STRICT_AND_RECOVERABLE_CORRECT


def test_ambiguous_outcome_is_reported_separately() -> None:
    ambiguous = _view("ambiguous-two-labels-including-gold")
    assert ambiguous["ambiguous"] is True
    summary = summarize_choice_views([ambiguous])
    assert summary["ambiguousOutputCount"] == 1
    assert summary["outcomes"][OUTCOME_AMBIGUOUS] == 1


def test_legacy_aliases_name_the_view_they_measure() -> None:
    summary = summarize_choice_views([_view("answer-wrapper-recoverable-only")])
    aliases = legacy_view_aliases(summary)
    assert aliases["accuracyInvalidAsWrong"] == summary["recoverableAccuracyFixedDenominator"]
    assert aliases["accuracyInvalidAsWrongScoreView"] == PRIMARY_SCREENING_VIEW
    assert aliases["strictAndRecoverableViewsSeparated"] is True


def test_score_view_contract_is_complete_for_js_consumers() -> None:
    contract = score_view_contract(
        contract_path=HERE / "english_core_choice_views.py",
        task_file_sha256="a" * 64,
        task_manifest_sha256="b" * 64,
        source_result_sha256="c" * 64,
        source_run_id="run-1",
    )
    assert contract["parseViewContractVersion"] == VIEW_CONTRACT_VERSION
    assert contract["denominatorPolicyVersion"] == DENOMINATOR_POLICY_VERSION
    assert contract["selected"] == PRIMARY_SCREENING_VIEW
    assert contract["metricKeys"] == SCORE_VIEW_METRIC_KEYS
    assert contract["strict"]["metricKey"] == "strictAccuracyFixedDenominator"
    assert contract[PRIMARY_SCREENING_VIEW]["metricKey"] == "recoverableAccuracyFixedDenominator"
    assert len(contract["contractSha256"]) == 64
    assert len(contract["parserSha256"]) == 64
    assert contract["sourceRunId"] == "run-1"


def test_with_score_view_attaches_contract_and_aliases() -> None:
    summary = summarize_choice_views([_view("bare-letter-allowed")])
    report = with_score_view(
        {"choiceViews": summary},
        score_view_contract(contract_path=HERE / "english_core_choice_views.py"),
    )
    assert report["scoreView"]["parseViewContractVersion"] == VIEW_CONTRACT_VERSION
    assert report["scoreViewsSeparated"] is True
    assert report["accuracyInvalidAsWrong"] == summary["recoverableAccuracyFixedDenominator"]


def test_shadow_analysis_side_accepts_the_published_score_view_contract() -> None:
    """The #65 JS analysis must be able to read and select both views (#64 test 10).

    This scores a synthetic four-item public-fast result, then asks
    english-core-snapshot-binding.mjs to bind and select each view. It proves the
    published contract is consumable, not just self-consistent.
    """
    import contextlib
    import hashlib
    import tempfile

    module_path = HERE / "score-english-core-public-fast.py"
    spec = importlib.util.spec_from_file_location("score_public_fast_contract", module_path)
    scorer = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(scorer)

    tasks = [
        {
            "id": f"t{index}",
            "dimension": "agreement",
            "source": "BLiMP",
            "phenomenon": "num",
            "prompt": "x",
            "generative": False,
            "allowedChoices": ["A", "B"],
            "answerProtocol": "letter",
        }
        for index in range(4)
    ]
    with tempfile.TemporaryDirectory() as raw_tmp:
        tmp = Path(raw_tmp)
        tasks_path = tmp / "english-core-public-fast.jsonl"
        tasks_path.write_text("\n".join(json.dumps(task) for task in tasks) + "\n")
        answers_path = tmp / "english-core-public-fast.answers.json"
        answers_path.write_text(json.dumps({"answers": {f"t{i}": "A" for i in range(4)}}))
        manifest_path = tmp / "english-core-public-fast.manifest.json"
        manifest_path.write_text(json.dumps({"cases": 4}))
        result_path = tmp / "result.json"
        result_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "runId": "run-contract",
                    "taskFileSha256": hashlib.sha256(tasks_path.read_bytes()).hexdigest(),
                    "taskCount": 4,
                    "outputs": [
                        {"id": "t0", "output": "A", "latencySeconds": 0.1},
                        {"id": "t1", "output": "Answer: A", "latencySeconds": 0.1},
                        {"id": "t2", "output": "Z", "latencySeconds": 0.1},
                        {"id": "t3", "output": "B", "latencySeconds": 0.1},
                    ],
                }
            )
        )
        scorer.TASKS = tasks_path
        scorer.ANSWERS = answers_path
        scorer.MANIFEST = manifest_path
        scorer.validate_result = lambda path, **kwargs: {
            "schemaValidation": {
                "resultSchemaVersion": 1,
                "validationMode": "promotion",
                "schemaSha256": "a" * 64,
                "validatorContractVersion": "v1",
            }
        }
        argv = sys.argv
        sys.argv = ["score-english-core-public-fast.py", str(result_path)]
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                scorer.main()
        finally:
            sys.argv = argv
        report = json.loads(buffer.getvalue())

    views = report["choiceViews"]
    assert views["strictAccuracyFixedDenominator"] == 0.25
    assert views["recoverableAccuracyFixedDenominator"] == 0.5
    assert report["accuracyInvalidAsWrongScoreView"] == PRIMARY_SCREENING_VIEW

    with tempfile.TemporaryDirectory() as raw_tmp:
        score_path = Path(raw_tmp) / "score.json"
        score_path.write_text(json.dumps(report))
        script_path = Path(raw_tmp) / "check-score-view.mjs"
        script_path.write_text(
            "import { requireScoreViewContract, selectScoreView } from "
            f"{json.dumps((HERE / 'english-core-snapshot-binding.mjs').as_uri())};\n"
            "import fs from \"node:fs\";\n"
            f"const score = JSON.parse(fs.readFileSync({json.dumps(str(score_path))}, \"utf8\"));\n"
            "const bound = requireScoreViewContract(score, \"Public-fast score\", "
            f"{{ benchmarkDir: {json.dumps(str(HERE))} }});\n"
            "const strict = selectScoreView({ scoreView: bound.scoreView, requested: \"strict\", label: \"Public-fast score\" });\n"
            "const recoverable = selectScoreView({ scoreView: bound.scoreView, requested: \"recoverable_anchored\", label: \"Public-fast score\" });\n"
            "process.stdout.write(JSON.stringify({"
            "available: bound.scoreView.available,"
            "selected: bound.scoreView.selected,"
            "strictMetric: bound.scoreView.strict.metric,"
            "recoverableMetric: bound.scoreView.recoverable.metric,"
            "contractVerified: bound.scoreView.contract.verifiedLocally,"
            "strictExplicit: strict.explicitlyRequested,"
            "recoverableExplicit: recoverable.explicitlyRequested }));\n"
        )
        completed = subprocess.run(
            ["node", str(script_path)], capture_output=True, text=True, check=False
        )
        assert completed.returncode == 0, completed.stderr
        bound = json.loads(completed.stdout)
    assert bound["available"] is True
    assert bound["selected"] == PRIMARY_SCREENING_VIEW
    assert bound["strictMetric"] == SCORE_VIEW_METRIC_KEYS["strict"]
    assert bound["recoverableMetric"] == SCORE_VIEW_METRIC_KEYS[PRIMARY_SCREENING_VIEW]
    assert bound["contractVerified"] is True
    assert bound["strictExplicit"] is True
    assert bound["recoverableExplicit"] is True


def test_public_fast_scorer_group_summaries_publish_both_views() -> None:
    module_path = HERE / "score-english-core-public-fast.py"
    spec = importlib.util.spec_from_file_location("score_public_fast", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    rows = [
        _view("bare-letter-allowed"),
        _view("answer-wrapper-recoverable-only"),
        _view("impossible-label-both-views-invalid"),
    ]
    group = module.summarize({"BLiMP::agreement": rows})["BLiMP::agreement"]
    assert group["cases"] == 3
    assert group["fixedDenominator"] == 3
    assert group["choiceViews"]["strictAccuracyFixedDenominator"] == summary_value(rows, "strictAccuracyFixedDenominator")
    assert group["choiceViews"]["recoverableAccuracyFixedDenominator"] == summary_value(rows, "recoverableAccuracyFixedDenominator")
    # Legacy keys mirror the recoverable view and say so.
    assert group["accuracyInvalidAsWrongScoreView"] == PRIMARY_SCREENING_VIEW
    assert group["validOutputCoverageScoreView"] == PRIMARY_SCREENING_VIEW


def test_full_classification_scorer_publishes_both_views_and_withholds_runtime_failures() -> None:
    """The full-distribution prompted lane must behave like public-fast (#64).

    Checks that the class predictions driving accuracy/MCC come from the
    recoverable anchored view, that the strict view is published beside it, and
    that a runtime-unqualified run produces no English zero.
    """
    import contextlib
    import hashlib
    import tempfile

    module_path = HERE / "score-english-core-public-full-classification.py"
    spec = importlib.util.spec_from_file_location("score_public_full_contract", module_path)
    scorer = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(scorer)

    ids = [f"full-wic-{index:05d}" for index in range(4)]
    tasks = [
        {
            "id": task_id,
            "source": "WiC",
            "dimension": "lexical_context",
            "phenomenon": "p",
            "prompt": "x",
            "generative": False,
        }
        for task_id in ids
    ]
    outputs = [
        {"id": ids[0], "output": "A", "latencySeconds": 0.1},
        {"id": ids[1], "output": "Answer: A", "latencySeconds": 0.1},
        {"id": ids[2], "output": "Z", "latencySeconds": 0.1},
        {"id": ids[3], "output": "B", "latencySeconds": 0.1},
    ]

    def run_scorer(extra_run_fields: dict) -> dict:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp)
            tasks_path = tmp / "english-core-public-full-classification.jsonl"
            tasks_path.write_text("\n".join(json.dumps(task) for task in tasks) + "\n")
            answers_path = tmp / "english-core-public-full-classification.answers.json"
            answers_path.write_text(
                json.dumps(
                    {
                        "answers": {
                            task_id: {"letter": "A", "goldLabel": 1, "labelByLetter": {"A": 1, "B": 0}}
                            for task_id in ids
                        }
                    }
                )
            )
            manifest_path = tmp / "english-core-public-full-classification.manifest.json"
            manifest_path.write_text(json.dumps({"cases": 4}))
            result_path = tmp / "result.json"
            result_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "runId": "run-full",
                        "taskFileSha256": hashlib.sha256(tasks_path.read_bytes()).hexdigest(),
                        "taskCount": 4,
                        "outputs": outputs,
                        **extra_run_fields,
                    }
                )
            )
            scorer.TASKS = tasks_path
            scorer.ANSWERS = answers_path
            scorer.MANIFEST = manifest_path
            scorer.validate_result = lambda path, **kwargs: {
                "schemaValidation": {
                    "resultSchemaVersion": 1,
                    "validationMode": "promotion",
                    "schemaSha256": "a" * 64,
                    "validatorContractVersion": "v1",
                }
            }
            argv = sys.argv
            sys.argv = ["score-english-core-public-full-classification.py", str(result_path)]
            buffer = io.StringIO()
            try:
                with contextlib.redirect_stdout(buffer):
                    scorer.main()
            finally:
                sys.argv = argv
            return json.loads(buffer.getvalue())

    report = run_scorer({})
    views = report["choiceViews"]
    assert views["strictAccuracyFixedDenominator"] == 0.25
    assert views["recoverableAccuracyFixedDenominator"] == 0.5
    assert report["scoreView"]["metricKeys"] == SCORE_VIEW_METRIC_KEYS
    # The recovered wrapper still yields the class prediction that drives the
    # classification metrics, and it is published as the recoverable view.
    recovered_row = next(row for row in report["detail"] if row["id"] == ids[1])
    assert recovered_row["recoverableCorrect"] is True
    assert recovered_row["strictCorrect"] is False
    assert recovered_row["predictedLabel"] == 1
    assert recovered_row["strictParsedChoice"] is None
    # An invalid label leaves the lane incomplete rather than silently excluded.
    assert report["bySource"]["WiC"]["completeForClassificationMetrics"] is False
    assert "mcc" not in report["bySource"]["WiC"]

    failed = run_scorer({"status": "failed", "complete": False})
    assert failed["runtimeQualification"]["runtimeQualified"] is False
    assert failed["choiceViews"]["fixedDenominator"] == 0
    assert failed["choiceViews"]["excludedRuntimeUnqualified"] == 4
    assert failed["choiceViews"]["strictAccuracyFixedDenominator"] is None
    assert failed["choiceViews"]["recoverableAccuracyFixedDenominator"] is None
    assert all(row["strictCorrect"] is None for row in failed["detail"])


def summary_value(rows, key):
    return summarize_choice_views(rows)[key]


def test_javascript_parser_parity_on_shared_fixtures() -> None:
    parser_module = HERE / "english-core-choice-parser.mjs"
    if not parser_module.exists():
        raise AssertionError("english-core-choice-parser.mjs is missing; JS parity cannot be verified")
    script = HERE / "_parity_choice_views.mjs"
    script.write_text(
        f'import {{ parseChoice }} from "{parser_module.as_uri()}";\n'
        "import fs from \"node:fs\";\n"
        f"const fixtures = JSON.parse(fs.readFileSync({json.dumps(str(HERE / 'english-core-choice-view-fixtures.json'))}, \"utf8\"));\n"
        "const out = {};\n"
        "for (const c of fixtures.cases) {\n"
        "  const p = parseChoice(c.raw, c.allowedChoices);\n"
        "  out[c.id] = { status: p.status, letter: p.letter ?? null, anchoredLabel: p.anchoredLabel ?? null, invalidOptionLabel: p.invalidOptionLabel ?? null };\n"
        "}\n"
        "process.stdout.write(JSON.stringify(out));\n"
    )
    try:
        completed = subprocess.run(
            ["node", str(script)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        js = json.loads(completed.stdout)
    finally:
        script.unlink(missing_ok=True)

    for case in FIXTURES["cases"]:
        expected = js[case["id"]]
        assert expected["letter"] == case["letter"], case["id"]
        assert expected["invalidOptionLabel"] == case["invalidOptionLabel"], case["id"]
        if not case.get("knownParserStatusDivergence"):
            assert expected["anchoredLabel"] == case["anchoredLabel"], case["id"]
            assert expected["status"] == case["status"], case["id"]
        else:
            # Documented shared-parser divergence (#44, not this issue): Python
            # reports ambiguous_multiple_choices with anchored label A, JS reports
            # no_anchored_answer with no anchored label. The view contract only
            # needs agreement on the resolved choice, which both sides keep null,
            # so neither correctness path can select one of the two labels.
            assert expected["status"] == case["jsStatus"], case["id"]


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failures = 0
    for test in tests:
        try:
            test()
        except AssertionError as error:
            failures += 1
            print(f"FAIL {test.__name__}: {error}")
        except Exception as error:  # noqa: BLE001
            failures += 1
            print(f"ERROR {test.__name__}: {error}")
        else:
            print(f"ok   {test.__name__}")
    if failures:
        raise SystemExit(f"{failures} of {len(tests)} choice-view tests failed")
    print(f"{len(tests)} choice-view tests passed")


if __name__ == "__main__":
    main()
