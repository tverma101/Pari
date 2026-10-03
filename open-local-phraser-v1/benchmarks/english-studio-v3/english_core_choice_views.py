"""Frozen strict/recoverable forced-choice score views for English Core.

Issue #64 requires prompted forced-choice lanes to publish two parallel, never
conflated views of the same raw output:

``strict``
    Protocol compliance only. The output must be the bare allowed option label
    (``A``/``A.``/``A)``/``A:``/``A-``) and the label must be inside the task's
    frozen ``allowedChoices`` set.

``recoverable``
    Conservative anchored recovery. The already-declared answer wrappers
    (``Answer: A``, ``The answer is A``, ``Option A``, ``I choose A``) and an
    anchored label followed by an explanation are tolerated, still subject to
    the same frozen allowed set.

Both views are derived from one parse of the preserved raw output through the
shared task-aware taxonomy in :mod:`english_core_choice_parser` (issue #44).
The gold label reaches this module only as an already-parsed letter that is
compared after the fact: it is never consulted to select, accept, or repair a
parse, and a gold-guided repair is not representable in this code path. A
correct recoverable answer can therefore never mutate strict correctness, and a
format-recovery gain can never be reported as a model-generation gain.

Frozen denominator policy ``fixed-screening-denominator-v1``: every task
instance in the frozen lane is exactly one unit of the denominator. A strict or
recoverable protocol failure contributes a zero to that view's fixed-denominator
accuracy while remaining labelled as a protocol failure. A runtime-unqualified
or otherwise non-English run is not an item at all: it is reported through
``runtimeQualification`` and excluded from every correctness denominator, so a
missing run can never become an English zero.

Native/official benchmark lanes keep their own official evaluator contract and
must not be routed through this module.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Iterable

from english_core_choice_parser import (
    ALLOWED_CHOICE_STATUSES,
    STATUS_AMBIGUOUS,
    STATUS_EMPTY,
    STATUS_NO_ANCHORED_ANSWER,
    STATUS_STRICT_ALLOWED,
    STATUS_RECOVERABLE_INVALID_LABEL,
    STATUS_STRICT_INVALID_LABEL,
    STATUS_WHITESPACE,
    allowed_choices_from_task,
    parse_choice,
)

VIEW_CONTRACT_VERSION = "strict-recoverable-choice-views-v1"
DENOMINATOR_POLICY_VERSION = "fixed-screening-denominator-v1"
ALLOWED_LABEL_CONTRACT_VERSION = "allowed-choices-frozen-v1"
PRIMARY_SCREENING_VIEW = "recoverable_anchored"

# The metric keys this module publishes per view. The JS analysis side
# (english-core-snapshot-binding.mjs) hard-codes the same names and fails closed
# if a score artifact names anything else, so both sides must move together.
STRICT_SCORE_VIEW = "strict"
SCORE_VIEW_METRIC_KEYS = {
    STRICT_SCORE_VIEW: "strictAccuracyFixedDenominator",
    PRIMARY_SCREENING_VIEW: "recoverableAccuracyFixedDenominator",
}
SCORE_VIEW_NAMES = tuple(SCORE_VIEW_METRIC_KEYS)

# The contract file identity a score artifact must publish so a later analysis
# run can prove which bytes produced the score.
CONTRACT_FILE = "english_core_choice_views.py"
PARSER_FILE = "english_core_choice_parser.py"

# A run/result is only English evidence when it actually produced the whole
# frozen lane under a runtime-qualified run. Anything else is infrastructure
# state and must stay outside the correctness denominator (#28, #64 test 9).
QUALIFIED_RUN_STATUSES = frozenset({"completed", "passed", "ok", "success", None})
RUNTIME_UNQUALIFIED_RUN_STATUSES = frozenset(
    {"runtime_unqualified", "failed", "incomplete", "error", "crashed", "aborted", "timeout"}
)

# Detail-row outcomes. These keep the issue's four concepts separate.
OUTCOME_STRICT_AND_RECOVERABLE_CORRECT = "strict_and_recoverable_correct"
OUTCOME_RECOVERABLE_ONLY_CORRECT = "recoverable_only_correct_format_recovery"
OUTCOME_STRICT_AND_RECOVERABLE_WRONG = "strict_and_recoverable_wrong_allowed_choice"
OUTCOME_INVALID_PROTOCOL = "invalid_protocol_output"
OUTCOME_MISSING_OUTPUT = "missing_output"
OUTCOME_AMBIGUOUS = "ambiguous_multiple_choices"
OUTCOME_NON_ANSWER = "non_answer_no_anchored_label"
OUTCOME_TRUNCATED = "truncated_output"
OUTCOME_RUNTIME_UNQUALIFIED = "runtime_unqualified_excluded_from_denominator"

_REFUSAL_MARKERS = (
    "i cannot",
    "i can't",
    "i can not",
    "i won't",
    "i will not",
    "i'm unable",
    "i am unable",
    "unable to",
    "cannot comply",
    "as an ai",
    "i apologize",
    "sorry, ",
    "no answer",
)
_REASONING_MARKERS = (
    "<think",
    "let me think",
    "reasoning:",
    "explanation:",
    "because",
    "since the",
)
_TRUNCATION_FINISH_REASONS = frozenset({"length", "max_tokens", "token_limit", "max_new_tokens"})


def run_runtime_qualification(run: Any) -> dict[str, Any]:
    """Classify whether a result artifact may enter an English denominator.

    A run that reports itself incomplete/failed/runtime-unqualified, or whose
    completed count is short of the frozen task count, is infrastructure state.
    It is surfaced as ``runtime_unqualified`` with its reason and is excluded
    from every strict/recoverable correctness denominator by the callers.
    """
    if not isinstance(run, dict):
        return {
            "runtimeQualified": False,
            "runtimeQualificationReason": "result_is_not_an_object",
        }
    status = run.get("status")
    status_text = str(status).strip().lower() if status is not None else None
    if status_text is not None and status_text in RUNTIME_UNQUALIFIED_RUN_STATUSES:
        return {"runtimeQualified": False, "runtimeQualificationReason": f"run_status_{status_text}"}
    if run.get("complete") is False:
        return {"runtimeQualified": False, "runtimeQualificationReason": "run_reports_incomplete"}
    completed = run.get("completedCount")
    task_count = run.get("taskCount")
    if isinstance(completed, int) and isinstance(task_count, int) and task_count > 0 and completed < task_count:
        return {
            "runtimeQualified": False,
            "runtimeQualificationReason": (
                f"completed_count_{completed}_below_task_count_{task_count}"
            ),
        }
    return {
        "runtimeQualified": True,
        "runtimeQualificationReason": None,
        "runStatus": status_text if status_text in QUALIFIED_RUN_STATUSES else status_text,
    }


def _markers(raw: str, markers: Iterable[str]) -> bool:
    lowered = raw.lower()
    return any(marker in lowered for marker in markers)


def outcome_for_views(
    *,
    strict_parsed: str | None,
    recoverable_parsed: str | None,
    strict_correct: bool | None,
    recoverable_correct: bool | None,
    choice_status: str,
    missing: bool,
    runtime_unqualified: bool,
    ambiguous: bool,
    truncated: bool,
    refusal_like: bool,
) -> str:
    """One explicit per-item label that never merges the issue's four concepts."""
    if runtime_unqualified:
        return OUTCOME_RUNTIME_UNQUALIFIED
    if missing:
        return OUTCOME_MISSING_OUTPUT
    if strict_correct and recoverable_correct:
        return OUTCOME_STRICT_AND_RECOVERABLE_CORRECT
    if recoverable_correct and not strict_correct:
        # A format-recovery gain. Never an English/generation improvement.
        return OUTCOME_RECOVERABLE_ONLY_CORRECT
    if strict_parsed is not None and recoverable_parsed is not None and not recoverable_correct:
        # An allowed option was selected incorrectly: a linguistic/task miss.
        return OUTCOME_STRICT_AND_RECOVERABLE_WRONG
    if truncated:
        # Truncation is only the reported cause when the item produced no
        # usable choice at all. A truncated output that still committed to an
        # allowed label keeps its correctness outcome above.
        return OUTCOME_TRUNCATED
    if ambiguous:
        return OUTCOME_AMBIGUOUS
    if refusal_like:
        return OUTCOME_NON_ANSWER
    if choice_status in (STATUS_EMPTY, STATUS_WHITESPACE, STATUS_NO_ANCHORED_ANSWER):
        return OUTCOME_NON_ANSWER
    return OUTCOME_INVALID_PROTOCOL


def score_choice_views(
    raw_output: Any,
    *,
    task: Any = None,
    allowed_choices: Any = None,
    gold: Any = None,
    finish_reason: Any = None,
    truncated: bool = False,
    missing: bool = False,
    runtime_unqualified: bool = False,
) -> dict[str, Any]:
    """Derive the strict and recoverable views of one forced-choice output.

    ``gold`` is used only to compare against the already-parsed labels. It is
    never used to choose, repair, or reject a parse, and a ``None`` gold leaves
    both correctness fields ``None`` (not evaluable) rather than zero.
    """
    if allowed_choices is None:
        allowed_choices = allowed_choices_from_task(task)
    parse = parse_choice(raw_output, allowed_choices)
    raw = parse.raw_output

    status = parse.status
    strict_parsed = parse.letter if status == STATUS_STRICT_ALLOWED else None
    recoverable_parsed = parse.letter if status in ALLOWED_CHOICE_STATUSES else None

    strict_valid = strict_parsed is not None
    recoverable_valid = recoverable_parsed is not None

    strict_correct: bool | None = None
    recoverable_correct: bool | None = None
    if gold is not None and not runtime_unqualified:
        strict_correct = bool(strict_valid and strict_parsed == gold)
        recoverable_correct = bool(recoverable_valid and recoverable_parsed == gold)

    finish_text = str(finish_reason).strip().lower() if finish_reason is not None else None
    # Truncation is whatever the run already recorded: an explicit boolean or a
    # recognized length stop reason. It never changes a parse, it only labels
    # the item as a truncated output instead of an ordinary non-answer.
    truncated = bool(truncated) or finish_text in _TRUNCATION_FINISH_REASONS
    ambiguous = bool(status == STATUS_AMBIGUOUS or parse.ambiguous)
    refusal_like = _markers(raw, _REFUSAL_MARKERS)
    reasoning_present = _markers(raw, _REASONING_MARKERS)
    invalid_label = status in (STATUS_STRICT_INVALID_LABEL, STATUS_RECOVERABLE_INVALID_LABEL)

    return {
        "parseViewContractVersion": VIEW_CONTRACT_VERSION,
        "denominatorPolicyVersion": DENOMINATOR_POLICY_VERSION,
        "rawOutput": raw,
        "rawOutputPreserved": True,
        "allowedChoices": list(parse.allowed_choices) if parse.allowed_choices else None,
        "allowedChoicesFrozen": parse.allowed_set_frozen,
        "finishReason": finish_reason,
        "strictParsedChoice": strict_parsed,
        "recoverableParsedChoice": recoverable_parsed,
        "strictProtocolValid": strict_valid,
        "recoverableProtocolValid": recoverable_valid,
        "strictCorrect": strict_correct,
        "recoverableCorrect": recoverable_correct,
        "viewsDisagree": strict_parsed != recoverable_parsed,
        "recoveredOnly": bool(recoverable_valid and not strict_valid),
        "choiceStatus": status,
        "ambiguous": ambiguous,
        "refusalLike": refusal_like,
        "reasoningMarkersPresent": reasoning_present,
        "truncatedOutput": truncated,
        "invalidOptionLabel": parse.invalid_option_label,
        "invalidOptionLabelStatus": bool(invalid_label),
        "anchoredLabel": parse.anchored_label,
        "goldLabelForComparison": gold,
        "outcome": outcome_for_views(
            strict_parsed=strict_parsed,
            recoverable_parsed=recoverable_parsed,
            strict_correct=strict_correct,
            recoverable_correct=recoverable_correct,
            choice_status=status,
            missing=missing,
            runtime_unqualified=runtime_unqualified,
            ambiguous=ambiguous,
            truncated=truncated,
            refusal_like=refusal_like,
        ),
    }


def wilson95(successes: int, n: int) -> list[float] | None:
    if n <= 0:
        return None
    z = 1.959963984540054
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt((p * (1 - p) / n) + (z * z / (4 * n * n))) / denom
    return [round(max(0.0, center - half), 6), round(min(1.0, center + half), 6)]


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def summarize_choice_views(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the parallel views under the frozen fixed denominator.

    Runtime-unqualified rows are removed from the denominator entirely and
    reported separately, so infrastructure failure never becomes an English
    zero. Every other row stays in the denominator exactly once; a protocol
    failure is a zero for its view and is additionally visible in coverage and
    in the per-status counts.
    """
    excluded = [row for row in rows if row.get("outcome") == OUTCOME_RUNTIME_UNQUALIFIED]
    scored_rows = [row for row in rows if row.get("outcome") != OUTCOME_RUNTIME_UNQUALIFIED]
    denominator = len(scored_rows)

    strict_valid = sum(1 for row in scored_rows if row.get("strictProtocolValid"))
    recoverable_valid = sum(1 for row in scored_rows if row.get("recoverableProtocolValid"))
    strict_correct = sum(1 for row in scored_rows if row.get("strictCorrect") is True)
    recoverable_correct = sum(1 for row in scored_rows if row.get("recoverableCorrect") is True)
    disagreements = sum(1 for row in scored_rows if row.get("viewsDisagree"))
    recoverable_only = sum(1 for row in scored_rows if row.get("recoveredOnly"))
    ambiguous_count = sum(1 for row in scored_rows if row.get("ambiguous"))

    def outcome_count(name: str) -> int:
        return sum(1 for row in scored_rows if row.get("outcome") == name)

    return {
        "denominatorPolicy": DENOMINATOR_POLICY_VERSION,
        "parseViewContractVersion": VIEW_CONTRACT_VERSION,
        "allowedLabelContractVersion": ALLOWED_LABEL_CONTRACT_VERSION,
        "fixedDenominator": denominator,
        "excludedRuntimeUnqualified": len(excluded),
        "strictValidOutputCoverage": _rate(strict_valid, denominator),
        "strictValidOutputCount": strict_valid,
        "strictAccuracyFixedDenominator": _rate(strict_correct, denominator),
        "strictCorrectCount": strict_correct,
        "strictAccuracyFixedDenominatorWilson95": wilson95(strict_correct, denominator),
        "recoverableValidOutputCoverage": _rate(recoverable_valid, denominator),
        "recoverableValidOutputCount": recoverable_valid,
        "recoverableAccuracyFixedDenominator": _rate(recoverable_correct, denominator),
        "recoverableCorrectCount": recoverable_correct,
        "recoverableAccuracyFixedDenominatorWilson95": wilson95(recoverable_correct, denominator),
        # Conditional views are published for diagnosis only and never replace
        # the fixed-denominator screening metrics above.
        "strictAccuracyGivenStrictValid": _rate(strict_correct, strict_valid),
        "recoverableAccuracyGivenRecoverableValid": _rate(recoverable_correct, recoverable_valid),
        "strictRecoverableDisagreementCount": disagreements,
        "strictRecoverableDisagreementRate": _rate(disagreements, denominator),
        "recoverableOnlyCount": recoverable_only,
        "recoverableOnlyRate": _rate(recoverable_only, denominator),
        "outcomes": {
            OUTCOME_STRICT_AND_RECOVERABLE_CORRECT: outcome_count(OUTCOME_STRICT_AND_RECOVERABLE_CORRECT),
            OUTCOME_RECOVERABLE_ONLY_CORRECT: outcome_count(OUTCOME_RECOVERABLE_ONLY_CORRECT),
            OUTCOME_STRICT_AND_RECOVERABLE_WRONG: outcome_count(OUTCOME_STRICT_AND_RECOVERABLE_WRONG),
            OUTCOME_INVALID_PROTOCOL: outcome_count(OUTCOME_INVALID_PROTOCOL),
            OUTCOME_MISSING_OUTPUT: outcome_count(OUTCOME_MISSING_OUTPUT),
            OUTCOME_AMBIGUOUS: outcome_count(OUTCOME_AMBIGUOUS),
            OUTCOME_NON_ANSWER: outcome_count(OUTCOME_NON_ANSWER),
            OUTCOME_TRUNCATED: outcome_count(OUTCOME_TRUNCATED),
            OUTCOME_RUNTIME_UNQUALIFIED: len(excluded),
        },
        "ambiguousOutputCount": ambiguous_count,
        "ambiguousOutputRate": _rate(ambiguous_count, denominator),
        "nonAnswerOutputCount": outcome_count(OUTCOME_NON_ANSWER),
        "nonAnswerOutputRate": _rate(outcome_count(OUTCOME_NON_ANSWER), denominator),
        "invalidOptionLabelCount": sum(
            1 for row in scored_rows if row.get("invalidOptionLabelStatus")
        ),
        "refusalOutputCount": sum(1 for row in scored_rows if row.get("refusalLike")),
        "truncatedOutputCount": sum(1 for row in scored_rows if row.get("truncatedOutput")),
        "invalidOptionLabelsObserved": sorted(
            {
                row.get("invalidOptionLabel")
                for row in scored_rows
                if row.get("invalidOptionLabel")
            }
        ),
    }


def legacy_view_aliases(views: dict[str, Any]) -> dict[str, Any]:
    """Explicitly name which view the pre-#64 metric keys represented.

    ``accuracyInvalidAsWrong`` was computed from the anchored recoverable parse
    before issue #64 existed. Those keys are kept for existing consumers, but
    they now carry the name of the view they actually measure instead of
    silently standing in for strict letter-only accuracy.
    """
    return {
        "accuracyInvalidAsWrong": views.get("recoverableAccuracyFixedDenominator"),
        "accuracyInvalidAsWrongScoreView": PRIMARY_SCREENING_VIEW,
        "validOutputCoverage": views.get("recoverableValidOutputCoverage"),
        "validOutputCoverageScoreView": PRIMARY_SCREENING_VIEW,
        "strictAndRecoverableViewsSeparated": True,
    }


def file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def score_view_contract(
    *,
    contract_path: Path,
    parser_path: Path | None = None,
    allowed_label_contract_version: str = ALLOWED_LABEL_CONTRACT_VERSION,
    task_file_sha256: str | None = None,
    task_manifest_sha256: str | None = None,
    source_result_sha256: str | None = None,
    source_run_id: str | None = None,
) -> dict[str, Any]:
    """Build the ``scoreView`` block a scored artifact must publish.

    The JS analysis side (``english-core-snapshot-binding.mjs``) reads this
    block to name the view it compared. It fails closed when the declared
    contract version, denominator policy, metric keys, or contract bytes do not
    match, so this function publishes exactly the keys that side requires and
    binds the two source files whose bytes define the scoring behavior.
    """
    contract_path = Path(contract_path)
    parser_path = Path(parser_path) if parser_path is not None else contract_path.parent / PARSER_FILE
    return {
        "parseViewContractVersion": VIEW_CONTRACT_VERSION,
        "denominatorPolicyVersion": DENOMINATOR_POLICY_VERSION,
        "allowedLabelContractVersion": allowed_label_contract_version,
        "selected": PRIMARY_SCREENING_VIEW,
        "primaryScreeningView": PRIMARY_SCREENING_VIEW,
        "metricKeys": dict(SCORE_VIEW_METRIC_KEYS),
        STRICT_SCORE_VIEW: {
            "name": STRICT_SCORE_VIEW,
            "metric": SCORE_VIEW_METRIC_KEYS[STRICT_SCORE_VIEW],
            "metricKey": SCORE_VIEW_METRIC_KEYS[STRICT_SCORE_VIEW],
        },
        PRIMARY_SCREENING_VIEW: {
            "name": PRIMARY_SCREENING_VIEW,
            "metric": SCORE_VIEW_METRIC_KEYS[PRIMARY_SCREENING_VIEW],
            "metricKey": SCORE_VIEW_METRIC_KEYS[PRIMARY_SCREENING_VIEW],
        },
        "contractFile": CONTRACT_FILE,
        "contractSha256": file_sha256(contract_path),
        "parserFile": Path(parser_path).name,
        "parserSha256": file_sha256(parser_path) if Path(parser_path).exists() else None,
        "taskFileSha256": task_file_sha256,
        "taskManifestSha256": task_manifest_sha256,
        "sourceResultSha256": source_result_sha256,
        "sourceRunId": source_run_id,
    }


def with_score_view(report: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    """Attach the score-view contract and the legacy aliases to one report.

    The aliases stay at the top level so existing consumers keep reading a
    number, but each one now carries the name of the view it actually measures
    instead of silently standing in for strict letter-only accuracy.
    """
    views = report.get("choiceViews") or {}
    report["scoreView"] = contract
    report["scoreViewsSeparated"] = True
    report.update(legacy_view_aliases(views))
    return report
