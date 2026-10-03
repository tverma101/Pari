#!/usr/bin/env python3
"""Annotate benchmark outputs with deterministic protocol diagnostics.

This module never opens answer keys and never changes a model score. It separates
format/protocol behavior from linguistic correctness so runtime or formatting
problems are not mistaken for bad English.

Two frozen forced-choice answer protocols are supported, and each one is
accepted only when its declared metadata and row shape agree:

``letter``
    ``allowedChoices`` is a non-empty array of single ASCII ``A-Z`` labels. The
    shared letter parser in ``english_core_choice_parser`` owns parsing and its
    behavior is unchanged.

``label``
    ``allowedAnswerLabels`` is the ordered SemanticQA LCC 8-category taxonomy
    (``Magn``, ``AntiMagn``, ``Ver``, ``AntiVer``, ``Bon``, ``AntiBon``,
    ``Son``, ``Oper1``). The model answers with a category *name*, so parsing is
    a taxonomy-membership question, not a letter question. Scoring a label row
    with the letter parser would report a correct answer as a malformed choice
    and an out-of-domain letter as valid, which would silently corrupt
    protocol-valid coverage.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from english_core_choice_parser import (
    STATUS_EMPTY,
    STATUS_RECOVERABLE_ALLOWED,
    STATUS_RECOVERABLE_INVALID_LABEL,
    STATUS_AMBIGUOUS,
    STATUS_STRICT_ALLOWED,
    STATUS_STRICT_INVALID_LABEL,
    STATUS_NO_ANCHORED_ANSWER,
    STATUS_WHITESPACE,
    allowed_choices_from_task,
    parse_choice,
)
from word_studio_output_parser import diagnose as diagnose_word_studio
from word_studio_output_parser import route_from_task

# The label taxonomy is pinned from the benchmark's own frozen metadata (the same
# tuple build-english-core-fixed-screen.py validates task rows against) and is
# restated here so the diagnostic layer stays importable without the builder and
# never re-derives the set from prompt prose or gold.
SEMANTICQA_LCC_LABELS = ("Magn", "AntiMagn", "Ver", "AntiVer", "Bon", "AntiBon", "Son", "Oper1")
SEMANTICQA_LCC_BENCHMARK = "SemanticQA-LCC-8cat"

PROTOCOL_LETTER = "letter"
PROTOCOL_LABEL = "label"
ANSWER_PROTOCOLS = (PROTOCOL_LETTER, PROTOCOL_LABEL)

@dataclass(frozen=True)
class AnswerProtocolContract:
    """The resolved frozen answer contract for one task row.

    ``allowed`` is the ordered accepted-label set (letters for the letter
    protocol, category names for the label protocol) or ``None`` when the row
    freezes nothing. ``issues`` records why a row is unusable; a non-empty tuple
    always accompanies ``usable=False`` so diagnostics can explain the fault.
    """

    protocol: str | None
    allowed: tuple[str, ...] | None
    usable: bool
    issues: tuple[str, ...] = ()

    @property
    def issue_codes(self) -> list[str]:
        return list(self.issues)

STRICT_CHOICE_RE = re.compile(r"^\s*([A-Z])\s*$")
AMBIGUOUS_CHOICE_RE = re.compile(
    r"(?:^|\b)([A-Z])\s*(?:/|\bor\b|\band\b|&)\s*([A-Z])(?:\b|$)", re.I
)
REFUSAL_RE = re.compile(
    r"\b(?:i\s+(?:can(?:not|'t)|won't|will not)|unable to|cannot comply|"
    r"i must refuse|i have to refuse|as an ai)\b",
    re.I,
)
REASONING_RE = re.compile(
    r"(?:<think>|</think>|\b(?:let me think|reasoning|analysis|step[- ]by[- ]step)\b)",
    re.I,
)
ANSWER_CUE_RE = re.compile(r"\b(?:answer|option|choice|select|pick)\b", re.I)


LABEL_COMPARE_STRIP_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def label_compare_key(value: str) -> str:
    """Conservative comparison key for an answer label.

    Casefolds and collapses punctuation/whitespace so ``"Anti-Magn"`` and
    ``"anti_magn"`` compare equal against the same frozen category, without
    ever rewriting the text that is reported. NFC keeps canonically equivalent
    spellings from splitting one category into two.
    """
    folded = unicodedata.normalize("NFC", str(value or "")).casefold()
    return LABEL_COMPARE_STRIP_RE.sub("", folded)


def normalize_answer_labels(value: Any) -> tuple[str, ...]:
    """Validate and canonicalize an ordered label protocol answer set."""
    if isinstance(value, str):
        raise ValueError("allowedAnswerLabels must be an array, not a string")
    if not isinstance(value, (list, tuple)):
        raise ValueError(
            f"allowedAnswerLabels must be an array, got {type(value).__name__}"
        )
    labels: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            raise ValueError(f"allowedAnswerLabels entries must be strings, got {type(entry).__name__}")
        text = entry.strip()
        if not text:
            raise ValueError("allowedAnswerLabels entries must not be empty")
        if any(unicodedata.category(ch).startswith("C") for ch in text):
            raise ValueError(f"allowedAnswerLabels entry carries a control character: {entry!r}")
        labels.append(text)
    if not labels:
        raise ValueError("allowedAnswerLabels must not be empty")
    keys = [label_compare_key(text) for text in labels]
    if len(set(keys)) != len(keys):
        raise ValueError("allowedAnswerLabels must not repeat a category")
    return tuple(labels)


def resolve_answer_protocol(task: Any) -> AnswerProtocolContract:
    """Resolve and validate one task row's frozen answer protocol.

    A row is usable only when its declared protocol, its answer set and its row
    shape agree. Everything else is reported as an issue rather than guessed:
    a row that freezes nothing would otherwise be scored under a permissive
    default that accepts labels the model was never allowed to produce.

    Rules, in order:

    - both answer sets present, or a set present for a protocol that does not
      declare it, is contradictory metadata;
    - an unknown ``answerProtocol`` value is malformed metadata;
    - ``letter`` requires ``allowedChoices`` and must not be a generative row;
    - ``label`` requires ``allowedAnswerLabels`` to be exactly the pinned
      SemanticQA taxonomy, on the SemanticQA benchmark, and must not be a
      generative row;
    - an undeclared protocol is inferred only when exactly one set is present;
    - a row with no declared protocol and no set is reported, not assumed.
    """
    if not isinstance(task, dict):
        return AnswerProtocolContract(None, None, False, ("task_row_not_an_object",))

    generative = bool(task.get("generative"))
    declared = task.get("answerProtocol", task.get("answer_protocol"))
    if declared is not None and not isinstance(declared, str):
        return AnswerProtocolContract(None, None, False, ("answerProtocol_not_a_string",))
    declared = declared.strip() if isinstance(declared, str) else None
    if declared == "":
        declared = None

    has_letters = task.get("allowedChoices") is not None
    has_labels = task.get("allowedAnswerLabels") is not None
    issues: list[str] = []

    if has_letters and has_labels:
        return AnswerProtocolContract(
            declared, None, False, ("both_allowed_choices_and_allowed_labels",)
        )

    if generative:
        # A generative row legitimately freezes nothing: that is the correct
        # shape, and it has no answer protocol to resolve.
        if declared is None and not has_letters and not has_labels:
            return AnswerProtocolContract(None, None, True)
        issues = ["generative_row_declares_frozen_answer_protocol"]
        if declared is not None:
            issues.append("generative_row_declares_answerProtocol")
        if has_letters:
            issues.append("generative_row_declares_allowedChoices")
        if has_labels:
            issues.append("generative_row_declares_allowedAnswerLabels")
        return AnswerProtocolContract(declared, None, False, tuple(issues))

    if declared is not None and declared not in ANSWER_PROTOCOLS:
        return AnswerProtocolContract(
            declared, None, False, ("unknown_answer_protocol",)
        )

    if declared is None:
        # An undeclared protocol is only inferred from an unambiguous row shape.
        if has_letters:
            declared = PROTOCOL_LETTER
        elif has_labels:
            declared = PROTOCOL_LABEL
        else:
            return AnswerProtocolContract(
                None, None, False, ("forced_choice_without_frozen_answer_set",)
            )

    if declared == PROTOCOL_LETTER:
        if has_labels:
            return AnswerProtocolContract(
                declared, None, False, ("letter_protocol_with_allowed_answer_labels",)
            )
        if not has_letters:
            return AnswerProtocolContract(
                declared, None, False, ("letter_protocol_without_allowedChoices",)
            )
        try:
            allowed = allowed_choices_from_task(task)
        except ValueError as exc:
            return AnswerProtocolContract(
                declared, None, False, (f"allowedChoices_malformed: {exc}",)
            )
        if not allowed:
            return AnswerProtocolContract(
                declared, None, False, ("letter_protocol_without_allowedChoices",)
            )
        return AnswerProtocolContract(declared, tuple(allowed), True)

    # Label protocol: the frozen set must be the pinned ordered taxonomy, so an
    # answer can never be read against a re-derived or reordered set.
    if has_letters:
        return AnswerProtocolContract(
            declared, None, False, ("label_protocol_with_allowedChoices",)
        )
    if not has_labels:
        return AnswerProtocolContract(
            declared, None, False, ("label_protocol_without_allowedAnswerLabels",)
        )
    try:
        labels = normalize_answer_labels(task.get("allowedAnswerLabels"))
    except ValueError as exc:
        return AnswerProtocolContract(
            declared, None, False, (f"allowedAnswerLabels_malformed: {exc}",)
        )
    if labels != SEMANTICQA_LCC_LABELS:
        return AnswerProtocolContract(
            declared, labels, False, ("allowedAnswerLabels_not_pinned_taxonomy",)
        )
    benchmark = task.get("benchmark")
    if benchmark != SEMANTICQA_LCC_BENCHMARK:
        return AnswerProtocolContract(
            declared, labels, False, ("label_protocol_wrong_benchmark",)
        )
    if not isinstance(task.get("prompt"), str) or any(
        label not in task["prompt"] for label in labels
    ):
        return AnswerProtocolContract(
            declared, labels, False, ("label_protocol_prompt_missing_categories",)
        )
    return AnswerProtocolContract(declared, labels, True)


LABEL_ANSWER_RE = re.compile(
    r"^(?:the\s+)?(?P<label>[\w\-]+)\s*[.!,]?$", re.UNICODE
)
LABEL_EXPLANATION_RE = re.compile(
    r"(?:^|\n)\s*(?:because|since|explanation|reasoning|i (?:chose|think))\b",
    re.I,
)
LABEL_IN_PROSE_RE = re.compile(
    r"(?:^|\n)\s*(?:categories?|options?|choices?)\s*[:\n]", re.I
)


def classify_label(
    text: str,
    finish_reason: str | None = None,
    allowed_labels: Any = None,
) -> dict[str, Any]:
    """Classify one label-protocol completion against its frozen taxonomy.

    The letter parser is deliberately not reused here: its bare-label and
    anchored-wrapper rules are single ASCII letters, so a correct category name
    would come back as a malformed choice and a letter such as ``"D"`` would
    come back valid even though no such category exists. This classifier answers
    the only question a label row poses - is the answer one of the frozen
    categories - and applies the same prose/refusal/truncation diagnostics.
    """
    raw = str(text or "")
    stripped = raw.strip()
    allowed = normalize_answer_labels(
        allowed_labels if allowed_labels is not None else SEMANTICQA_LCC_LABELS
    )
    keys = {label_compare_key(label): label for label in allowed}

    statuses: list[str] = []
    if raw == "":
        statuses.append(STATUS_EMPTY)
    elif not stripped:
        statuses.append(STATUS_WHITESPACE)

    if finish_reason in {"length", "max_tokens", "token_limit"}:
        statuses.append("max_tokens_truncation")

    refusal = bool(REFUSAL_RE.search(stripped))
    if refusal:
        statuses.append("refusal_or_nonanswer")
    has_reasoning = bool(REASONING_RE.search(stripped))
    if stripped.startswith("<think>") and "</think>" not in stripped:
        statuses.append("unclosed_thinking_block")

    matched: str | None = None
    invalid: str | None = None
    bare = bool(LABEL_ANSWER_RE.fullmatch(stripped))
    # Only an anchored single-token answer is accepted; prose that happens to
    # contain a category name is not an answer.
    prose_shape = bool(LABEL_IN_PROSE_RE.search(stripped)) or bool(
        LABEL_EXPLANATION_RE.search(stripped)
    )
    if not prose_shape:
        candidate = LABEL_ANSWER_RE.fullmatch(stripped)
        if candidate:
            label = candidate.group("label")
            matched = keys.get(label_compare_key(label))
            if matched is None:
                invalid = label

    if stripped and matched is None:
        if invalid is not None:
            statuses.append("invalid_option_label")
        elif has_reasoning and not ANSWER_CUE_RE.search(stripped):
            statuses.append("reasoning_only_no_answer")
        elif not refusal:
            statuses.append("malformed_choice")
    elif matched is not None and not bare:
        statuses.append("reasoning_leak_with_answer")

    if invalid is not None:
        statuses.append(STATUS_RECOVERABLE_INVALID_LABEL)
    elif matched is not None:
        statuses.append(STATUS_RECOVERABLE_ALLOWED)
    elif not statuses:
        statuses.append(STATUS_NO_ANCHORED_ANSWER)

    return {
        "protocolVersion": 2,
        "statuses": list(dict.fromkeys(statuses)),
        "choiceStatus": (
            STATUS_RECOVERABLE_INVALID_LABEL if invalid is not None
            else STATUS_RECOVERABLE_ALLOWED if matched is not None
            else STATUS_NO_ANCHORED_ANSWER
        ),
        "allowedAnswerLabels": list(allowed),
        "allowedAnswerLabelsFrozen": True,
        "strictLabelOnly": matched if bare else None,
        "recoverableExplicitChoice": matched,
        "recoverableDiffersFromStrict": bool(matched and not bare),
        "invalidOptionLabel": invalid,
        "reasoningMarkersPresent": has_reasoning,
        "refusalLike": refusal,
        "finishReason": finish_reason,
    }


def classify_choice(
    text: str,
    finish_reason: str | None = None,
    allowed_choices: Any = None,
) -> dict[str, Any]:
    raw = str(text or "")
    stripped = raw.strip()
    allowed = allowed_choices_from_task({"allowedChoices": allowed_choices})
    parse = parse_choice(raw, allowed)
    strict = STRICT_CHOICE_RE.fullmatch(raw)
    recoverable = parse.letter
    ambiguous = bool(AMBIGUOUS_CHOICE_RE.search(stripped))
    has_reasoning = bool(REASONING_RE.search(stripped))
    refusal = bool(REFUSAL_RE.search(stripped))
    statuses: list[str] = []

    if raw == "":
        statuses.append(STATUS_EMPTY)
    elif not stripped:
        statuses.append(STATUS_WHITESPACE)

    if finish_reason in {"length", "max_tokens", "token_limit"}:
        statuses.append("max_tokens_truncation")
    if ambiguous:
        statuses.append("ambiguous_multiple_choices")
    if refusal:
        statuses.append("refusal_or_nonanswer")

    # An out-of-domain label is a protocol violation, not an English miss: it
    # reduces protocol-valid coverage and is reported separately from a wrong
    # allowed choice. The allowed set is frozen task metadata; gold is never read.
    if parse.status in (STATUS_STRICT_INVALID_LABEL, STATUS_RECOVERABLE_INVALID_LABEL):
        statuses.append("invalid_option_label")

    if stripped:
        if recoverable is None:
            if has_reasoning and not ANSWER_CUE_RE.search(stripped):
                statuses.append("reasoning_only_no_answer")
            elif (
                not ambiguous
                and not refusal
                and parse.status
                not in (
                    STATUS_AMBIGUOUS,
                    STATUS_STRICT_INVALID_LABEL,
                    STATUS_RECOVERABLE_INVALID_LABEL,
                )
            ):
                statuses.append("malformed_choice")
        elif strict is None:
            if has_reasoning or len(stripped) > 2:
                statuses.append("reasoning_leak_with_answer")

    if stripped.startswith("<think>") and "</think>" not in stripped:
        statuses.append("unclosed_thinking_block")

    if not statuses:
        statuses.append("ok")

    return {
        "protocolVersion": 2,
        "statuses": statuses,
        # A prose-level multi-choice signal with no anchored label is still an
        # ambiguous answer, so the canonical status matches the statuses list.
        "choiceStatus": (
            STATUS_AMBIGUOUS if ambiguous and not parse.anchored_label else parse.status
        ),
        "allowedChoices": list(parse.allowed_choices) if parse.allowed_choices else None,
        "allowedChoicesFrozen": parse.allowed_set_frozen,
        "strictLetterOnly": strict.group(1) if (strict and parse.letter) else None,
        "anchoredLabel": parse.anchored_label,
        "invalidOptionLabel": parse.invalid_option_label,
        "recoverableExplicitChoice": recoverable,
        "recoverableDiffersFromStrict": bool(recoverable and not (strict and parse.letter)),
        "ambiguous": ambiguous,
        "refusalLike": refusal,
        "reasoningMarkersPresent": has_reasoning,
        "finishReason": finish_reason,
    }


def load_tasks(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        task_id = row.get("id")
        if not task_id or task_id in rows:
            raise SystemExit(f"invalid/duplicate task id in {path}: {task_id!r}")
        rows[task_id] = row
    return rows


def expected_token_limit(result: dict[str, Any], task: dict[str, Any]) -> int | None:
    if isinstance(task.get("maxNewTokens"), int):
        return int(task["maxNewTokens"])
    decoding = result.get("decoding") or {}
    key = "maxNewTokens" if task.get("generative") else "forcedChoiceMaxNewTokens"
    value = decoding.get(key)
    return int(value) if isinstance(value, int) else None


def annotate(result: dict[str, Any], tasks: dict[str, dict[str, Any]]) -> dict[str, Any]:
    annotated: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    missing_allowed_choices: list[str] = []
    protocol_faults: list[dict[str, Any]] = []
    protocol_coverage: Counter[str] = Counter()
    output_rows = result.get("outputs", [])
    output_ids = [row.get("id") for row in output_rows if isinstance(row, dict)]
    duplicate_output_ids = sorted({str(x) for x in output_ids if output_ids.count(x) > 1})
    foreign_output_ids = sorted(str(x) for x in set(output_ids) - set(tasks))
    missing_output_ids = sorted(str(x) for x in set(tasks) - set(output_ids))

    for output in output_rows:
        if not isinstance(output, dict):
            continue
        task_id = output.get("id")
        task = tasks.get(task_id)
        if task is None:
            continue
        text = str(output.get("output") or "")
        finish_reason = output.get("finishReason")
        token_limit = expected_token_limit(result, task)
        token_count = output.get("completionTokenCount")
        likely_limit = (
            finish_reason is None
            and isinstance(token_count, int)
            and isinstance(token_limit, int)
            and token_count >= token_limit
        )
        is_word_studio = str(task.get("suite") or "").startswith("word_studio_")
        if is_word_studio:
            if task.get("allowedChoices") is not None or task.get("allowedAnswerLabels") is not None:
                raise SystemExit(
                    f"unexpected frozen answer set on generative word-studio task {task_id}"
                )
            compare_source = task.get("selectedText") or task.get("sourceText")
            # Route and protected spans come from the task row, so the offline
            # report uses the same usable-unique contract as the streamed timing
            # path in word_studio_output_parser (Issue #43).
            diag = diagnose_word_studio(
                text,
                source=compare_source,
                requested=int(task.get("requestedCount") or 10),
                route=route_from_task(task),
                protected=task.get("protectedSpans"),
            )
            if finish_reason in {"length", "max_tokens", "token_limit"}:
                diag["statuses"] = list(dict.fromkeys([*diag["statuses"], "max_tokens_truncation"]))
            elif likely_limit:
                diag["statuses"] = list(dict.fromkeys([*diag["statuses"], "max_tokens_truncation_suspected"]))
            diag["finishReason"] = finish_reason
            diag["completionTokenCount"] = token_count
            diag["expectedTokenLimit"] = token_limit
            diag["kind"] = "word_studio"
        elif not task.get("generative"):
            contract = resolve_answer_protocol(task)
            if not contract.usable:
                # Unusable protocol metadata is a structural fault, not a score:
                # the row is annotated with the reason and never parsed as if it
                # had a valid frozen answer set.
                protocol_faults.append(
                    {
                        "id": str(task_id),
                        "answerProtocol": contract.protocol,
                        "issues": contract.issue_codes,
                    }
                )
                diag = {
                    "protocolVersion": 2,
                    "kind": "forced_choice_unusable_protocol",
                    "statuses": ["unusable_answer_protocol_metadata"],
                    # The declared value is kept as evidence, but it is not
                    # reported as an active `answerProtocol`: protocol coverage
                    # must count only rows whose contract actually resolved.
                    "declaredAnswerProtocol": contract.protocol,
                    "protocolIssues": contract.issue_codes,
                    "allowedChoices": (
                        list(contract.allowed)
                        if contract.protocol == PROTOCOL_LETTER and contract.allowed
                        else None
                    ),
                    "allowedAnswerLabels": (
                        list(contract.allowed)
                        if contract.protocol == PROTOCOL_LABEL and contract.allowed
                        else None
                    ),
                    "recoverableExplicitChoice": None,
                    "strictLetterOnly": None,
                    "recoverableDiffersFromStrict": False,
                    "ambiguous": False,
                    "refusalLike": False,
                    "reasoningMarkersPresent": bool(REASONING_RE.search(text)),
                    "finishReason": finish_reason,
                }
            elif contract.protocol == PROTOCOL_LABEL:
                diag = classify_label(text, finish_reason, contract.allowed)
                diag["kind"] = "forced_choice_label"
                diag["answerProtocol"] = PROTOCOL_LABEL
                diag["benchmark"] = task.get("benchmark")
                if likely_limit and "max_tokens_truncation" not in diag["statuses"]:
                    diag["statuses"].append("max_tokens_truncation_suspected")
                diag["completionTokenCount"] = token_count
                diag["expectedTokenLimit"] = token_limit
            else:
                if contract.protocol == PROTOCOL_LETTER and task.get("allowedChoices") is None:
                    missing_allowed_choices.append(str(task_id))
                diag = classify_choice(text, finish_reason, task.get("allowedChoices"))
                diag["kind"] = "forced_choice"
                diag["answerProtocol"] = PROTOCOL_LETTER
                if likely_limit and "max_tokens_truncation" not in diag["statuses"]:
                    diag["statuses"].append("max_tokens_truncation_suspected")
                diag["completionTokenCount"] = token_count
                diag["expectedTokenLimit"] = token_limit
            if contract.usable and likely_limit and "max_tokens_truncation" not in diag["statuses"]:
                diag["statuses"].append("max_tokens_truncation_suspected")
            diag.setdefault("completionTokenCount", token_count)
            diag.setdefault("expectedTokenLimit", token_limit)
        else:
            if task.get("allowedChoices") is not None or task.get("allowedAnswerLabels") is not None:
                raise SystemExit(
                    f"unexpected frozen answer set on generative task {task_id}"
                )
            statuses: list[str] = []
            if text == "":
                statuses.append("empty_output")
            elif not text.strip():
                statuses.append("whitespace_only")
            if REFUSAL_RE.search(text):
                statuses.append("refusal_or_nonanswer")
            if finish_reason in {"length", "max_tokens", "token_limit"}:
                statuses.append("max_tokens_truncation")
            elif likely_limit:
                statuses.append("max_tokens_truncation_suspected")
            if text.strip().startswith("<think>") and "</think>" not in text:
                statuses.append("unclosed_thinking_block")
            if not statuses:
                statuses.append("ok")
            diag = {
                "protocolVersion": 2,
                "kind": "generative",
                "statuses": statuses,
                "finishReason": finish_reason,
                "completionTokenCount": token_count,
                "expectedTokenLimit": token_limit,
                "reasoningMarkersPresent": bool(REASONING_RE.search(text)),
            }
        for status in diag["statuses"]:
            counts[status] += 1
        # Only a row whose frozen contract resolved counts toward coverage; an
        # unusable row is a structural fault, not a letter or label observation.
        if diag.get("answerProtocol"):
            protocol_coverage[str(diag["answerProtocol"])] += 1
        annotated.append({"id": task_id, "diagnostics": diag})

    structural_statuses = []
    if duplicate_output_ids:
        structural_statuses.append("duplicate_output_ids")
    if foreign_output_ids:
        structural_statuses.append("foreign_output_ids")
    if missing_output_ids:
        structural_statuses.append("missing_output_ids")
    if missing_allowed_choices:
        structural_statuses.append("forced_choice_tasks_without_allowedChoices")
    if protocol_faults:
        structural_statuses.append("unusable_answer_protocol_metadata")
    if len(output_rows) != len(tasks):
        structural_statuses.append("wrong_number_of_outputs")

    return {
        # Bumped from 3: answerProtocolCoverage, unusableAnswerProtocolMetadata and
        # declaredAnswerProtocol are new, and label rows now report
        # kind=forced_choice_label instead of forced_choice.
        "version": 4,
        "sourceRunId": result.get("runId"),
        "expectedTaskCount": len(tasks),
        "outputCount": len(output_rows),
        "annotatedCount": len(annotated),
        "structuralStatuses": structural_statuses or ["ok"],
        "duplicateOutputIds": duplicate_output_ids,
        "foreignOutputIds": foreign_output_ids,
        "missingOutputIds": missing_output_ids,
        "forcedChoiceTasksWithoutAllowedChoices": sorted(missing_allowed_choices),
        "answerProtocolCoverage": {
            protocol: protocol_coverage.get(protocol, 0) for protocol in ANSWER_PROTOCOLS
        },
        "unusableAnswerProtocolMetadata": sorted(
            protocol_faults, key=lambda item: str(item["id"])
        ),
        "statusCounts": dict(sorted(counts.items())),
        # Row-ordered, never id-keyed: a repeated output id must not collapse
        # two different rows into one usable-depth number.
        "usableUniqueCounts": [
            {
                "id": row["id"],
                "usableUniqueCount": row["diagnostics"]["usableUniqueCount"],
                "requestedCount": row["diagnostics"].get("requestedCount"),
            }
            for row in annotated
            if row["diagnostics"].get("kind") == "word_studio"
            and row["diagnostics"].get("usableUniqueCount") is not None
        ],
        "rows": annotated,
        "interpretation": [
            "Diagnostics are protocol/format observations only; they do not replace lane-specific English scoring.",
            "recoverableExplicitChoice uses a frozen conservative parser and never consults gold labels.",
            "Both the strict and recoverable views enforce each task's frozen allowedChoices; a label outside that set is invalid_option_label, not a wrong English answer.",
            "invalid_option_label reduces protocol-valid coverage. Any coverage change it causes is a parser/protocol correction, not a model-generation change.",
            "max_tokens_truncation_suspected is diagnostic when the runtime omitted an explicit finish reason but consumed the declared token limit.",
            "word_studio usableUniqueCount is the canonical usable-depth metric; raw parsed counts may include duplicates, unchanged copies, protected corruption and commentary.",
            "Both letter and label rows are validated against their own declared frozen answer set; a response outside that set is invalid_option_label, not a wrong English answer.",
            "Letter rows are parsed by the frozen letter parser. Label rows are parsed against the ordered SemanticQA taxonomy, so a category name is never read as a malformed letter and a stray letter is never read as a valid category.",
            "unusable_answer_protocol_metadata means a forced-choice row's declared protocol, answer set and row shape disagree; such rows are annotated with the reason and never scored.",
            "Runtime failures are handled separately by kaggle_failure_taxonomy.py and must not become English zeros.",
        ],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("result", type=Path)
    ap.add_argument("tasks", type=Path)
    ap.add_argument("output", type=Path)
    args = ap.parse_args()
    result = json.loads(args.result.read_text(encoding="utf-8"))
    tasks = load_tasks(args.tasks)
    report = annotate(result, tasks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"statusCounts": report["statusCounts"], "structuralStatuses": report["structuralStatuses"]}, indent=2))
    if report["structuralStatuses"] != ["ok"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
