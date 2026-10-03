#!/usr/bin/env python3
import json

from protocol_output_diagnostics import (
    SEMANTICQA_LCC_BENCHMARK,
    SEMANTICQA_LCC_LABELS,
    annotate,
    classify_choice,
    classify_label,
    label_compare_key,
    resolve_answer_protocol,
)
from word_studio_output_parser import diagnose, route_from_task


def expect(status: str, text: str, *, finish_reason=None) -> None:
    got = classify_choice(text, finish_reason)["statuses"]
    assert status in got, (status, text, got)


def main() -> None:
    clean = classify_choice("A")
    assert clean["statuses"] == ["ok"]
    assert clean["strictLetterOnly"] == "A"
    assert clean["recoverableExplicitChoice"] == "A"

    explained = classify_choice("A. same")
    assert explained["recoverableExplicitChoice"] == "A"
    assert explained["strictLetterOnly"] is None
    assert "reasoning_leak_with_answer" in explained["statuses"]

    expect("ambiguous_multiple_choices", "A or B")
    expect("malformed_choice", "I think the first sentence is better")
    expect("reasoning_only_no_answer", "<think>Let me think step-by-step</think>")
    expect("unclosed_thinking_block", "<think>analysis that never closes")
    expect("refusal_or_nonanswer", "I can't answer that")
    expect("max_tokens_truncation", "A", finish_reason="length")
    expect("empty_output", "")
    expect("whitespace_only", "   \n")

    good_ws = diagnose('{"options":["clear","easy to follow","straightforward","simple","readable","understandable","plain","direct","accessible","easy to understand"]}')
    assert good_ws["parsedCount"] == 10
    assert good_ws["uniqueNormalizedCount"] == 10
    assert good_ws["statuses"] == ["ok"]

    bad_ws = diagnose("1. clear\n2. clear\n3. understandable", requested=10)
    assert "word_studio_too_few_candidates" in bad_ws["statuses"]
    assert bad_ws["duplicateCount"] == 1

    prose_ws = diagnose("Here are some alternatives: clear, simple, easy to understand")
    assert "word_studio_unparseable_list" in prose_ws["statuses"]

    assert route_from_task({"semanticMode": "intentional_compression"}) == "intentional_compression"

    letter_protocol()
    label_protocol()
    malformed_protocol_metadata()
    word_studio_annotate()
    print("protocol output diagnostics fixtures passed")


def word_studio_annotate() -> None:
    """The offline report must use the same usable-unique contract as streaming.

    Issue #43: `usableUniqueCounts` is the canonical usable-depth metric, route
    and protected spans come from the task row, and raw parsed counts may include
    duplicates, unchanged copies, protected corruption and commentary.
    """
    source = "We should ship the feature today."
    tasks = {
        "ws-1": {
            "id": "ws-1",
            "suite": "word_studio_protocol_smoke_v1",
            "generative": True,
            "requestedCount": 10,
            "selectedText": source,
            "sourceText": source,
        },
        "ws-2": {
            "id": "ws-2",
            "suite": "word_studio_protocol_smoke_v1",
            "generative": True,
            "requestedCount": 3,
            "selectedText": "Ship it.",
            "semanticMode": "intentional_compression",
        },
        "ws-3": {
            "id": "ws-3",
            "suite": "word_studio_protocol_smoke_v1",
            "generative": True,
            "requestedCount": 3,
            "selectedText": "Ship it.",
            "protectedSpans": ["$4,200"],
        },
    }
    result = {
        "runId": "run-43",
        "decoding": {"maxNewTokens": 64},
        "outputs": [
            # 6 usable unique out of 8 parsed entries: an unchanged copy, a
            # zero-width duplicate and a prose line never advance depth.
            {"id": "ws-1", "output": json.dumps({"options": [
                "alpha", "beta", "gamma", "delta", "epsilon", "zeta",
                "alpha", source,
            ]}), "completionTokenCount": 40},
            # intentional_compression permits identity output.
            {"id": "ws-2", "output": json.dumps({"options": ["Ship it.", "gut", "ship"]}), "completionTokenCount": 12},
            # protected value altered -> candidate excluded from usable depth.
            {"id": "ws-3", "output": json.dumps({"options": ["Send the $5,100 today", "Send $4,200"]}), "completionTokenCount": 14},
            {"id": "ws-1", "output": json.dumps({"options": ["duplicate id"]})},
        ],
    }
    report = annotate(result, tasks)
    # The duplicate ws-1 row is the last one, so index by position, not by id.
    rows = [row["diagnostics"] for row in report["rows"]]
    ws1, ws2, ws3 = rows[0], rows[1], rows[2]
    assert ws1["kind"] == "word_studio"
    assert ws1["usableUniqueCount"] == 6, ws1
    assert ws1["unchangedSourceUnusableCount"] == 1
    assert ws1["duplicateTaxonomy"]["normalizedExactDuplicateCount"] == 1
    assert "contains_unchanged_source" in ws1["statuses"]
    # Repeated output ids are a structural fault, not a score.
    assert report["structuralStatuses"] == ["duplicate_output_ids", "wrong_number_of_outputs"]
    assert report["duplicateOutputIds"] == ["ws-1"]

    # intentional_compression route is not penalized for an unchanged copy.
    assert ws2["route"] == "intentional_compression"
    assert ws2["unchangedCountsAsUsable"] is True
    assert "contains_unchanged_source" not in ws2["statuses"]

    # Protected corruption is a candidate-level diagnostic.
    assert ws3["protectedContentCorruptionCount"] == 1
    assert "word_studio_protected_corruption" in ws3["statuses"]
    assert ws3["usableUniqueCount"] == 1

    assert report["usableUniqueCounts"] == [
        {"id": "ws-1", "usableUniqueCount": 6, "requestedCount": 10},
        {"id": "ws-2", "usableUniqueCount": 3, "requestedCount": 3},
        {"id": "ws-3", "usableUniqueCount": 1, "requestedCount": 3},
        {"id": "ws-1", "usableUniqueCount": 1, "requestedCount": 10},
    ], report["usableUniqueCounts"]
    assert report["statusCounts"]["ok"] >= 0
    assert any("usableUniqueCount" in note for note in report["interpretation"])


def label_row(**extra) -> dict:
    """A SemanticQA label-protocol row shaped like the real builder output."""
    taxonomy = "\n".join(f"{label}\tdescription of {label}" for label in SEMANTICQA_LCC_LABELS)
    row = {
        "id": "semanticqa_lcc_000",
        "generative": False,
        "benchmark": SEMANTICQA_LCC_BENCHMARK,
        "prompt": (
            f"Categories:\n{taxonomy}\nContext: the collocation is fixed.\n"
            "Collocation: fix a problem\nAnswer with the category name."
        ),
        "answerProtocol": "label",
        "allowedAnswerLabels": list(SEMANTICQA_LCC_LABELS),
    }
    row.update(extra)
    return row


def letter_row(**extra) -> dict:
    row = {
        "id": "pub-test-0000",
        "generative": False,
        "prompt": "A. same\nB. different\nAnswer only with the letter.",
        "answerProtocol": "letter",
        "allowedChoices": ["A", "B"],
    }
    row.update(extra)
    return row


def one_row_diag(task: dict, output: str) -> dict:
    """Annotate a single task/output pair and return its diagnostics."""
    report = annotate({"runId": "protocol-fixture", "outputs": [{"id": task["id"], "output": output}]}, {task["id"]: task})
    return report["rows"][0]["diagnostics"], report


def letter_protocol() -> None:
    """Letter rows keep the frozen letter parser and its reported shape."""
    task = letter_row()
    contract = resolve_answer_protocol(task)
    assert contract.usable and contract.protocol == "letter"
    assert contract.allowed == ("A", "B")

    valid, report = one_row_diag(task, "A")
    assert valid["kind"] == "forced_choice"
    assert valid["answerProtocol"] == "letter"
    assert valid["recoverableExplicitChoice"] == "A"
    assert valid["allowedChoices"] == ["A", "B"]
    # The letter parser's own status surface is unchanged: an allowed bare
    # letter reports "ok" and exposes strict/recoverable views.
    assert valid["statuses"] == ["ok"]
    assert valid["choiceStatus"] == "strict_allowed_choice"
    assert valid["strictLetterOnly"] == "A"
    assert report["answerProtocolCoverage"]["letter"] == 1
    assert report["structuralStatuses"] == ["ok"]

    out_of_domain, _ = one_row_diag(task, "D")
    assert out_of_domain["recoverableExplicitChoice"] is None
    assert "invalid_option_label" in out_of_domain["statuses"]

    explained, _ = one_row_diag(task, "A. same")
    assert explained["recoverableExplicitChoice"] == "A"
    assert "reasoning_leak_with_answer" in explained["statuses"]

    # A letter set that is not first-N-in-order is malformed metadata, not a score.
    contract = resolve_answer_protocol(letter_row(allowedChoices=["B", "A"]))
    assert contract.usable  # the shared parser sorts the set; order is not fatal
    diag, _ = one_row_diag(letter_row(allowedChoices=["AA"]), "A")
    assert diag["kind"] == "forced_choice_unusable_protocol"
    assert diag["protocolIssues"][0].startswith("allowedChoices_malformed")


def label_protocol() -> None:
    """Valid SemanticQA label rows are scored against the frozen taxonomy."""
    task = label_row()
    contract = resolve_answer_protocol(task)
    assert contract.usable and contract.protocol == "label"
    assert contract.allowed == SEMANTICQA_LCC_LABELS

    # Every one of the eight native categories is accepted.
    for label in SEMANTICQA_LCC_LABELS:
        diag, _ = one_row_diag(task, label)
        assert diag["kind"] == "forced_choice_label"
        assert diag["recoverableExplicitChoice"] == label, label
        assert diag["statuses"] == ["recoverable_allowed_choice"], label
        assert diag["allowedAnswerLabels"] == list(SEMANTICQA_LCC_LABELS)
        assert diag["allowedAnswerLabelsFrozen"] is True
        assert diag["strictLabelOnly"] == label

    valid, report = one_row_diag(task, "Bon")
    assert valid["benchmark"] == SEMANTICQA_LCC_BENCHMARK
    assert report["answerProtocolCoverage"] == {"letter": 0, "label": 1}
    assert report["structuralStatuses"] == ["ok"]
    assert report["unusableAnswerProtocolMetadata"] == []

    # Case and trailing punctuation resolve to the frozen category name.
    for variant, expected in [("bon.", "Bon"), ("bon", "Bon"), ("ANTI-MAGN", "AntiMagn")]:
        diag, _ = one_row_diag(task, variant)
        assert diag["recoverableExplicitChoice"] == expected, variant
        assert diag["recoverableDiffersFromStrict"] is False

    # A letter is not a category, and an unknown word is not a category either.
    for out_of_domain in ["D", "Z", "Nonsense", "Magnitude"]:
        diag, _ = one_row_diag(task, out_of_domain)
        assert diag["recoverableExplicitChoice"] is None, out_of_domain
        assert diag["invalidOptionLabel"] == out_of_domain, out_of_domain
        assert "invalid_option_label" in diag["statuses"]

    # Prose that merely mentions a category is not an anchored answer.
    prose, _ = one_row_diag(task, "I think it is Bon because it is additive")
    assert prose["recoverableExplicitChoice"] is None
    assert "malformed_choice" in prose["statuses"]

    # Shared protocol diagnostics still apply to label rows.
    assert "empty_output" in classify_label("", None)["statuses"]
    assert "whitespace_only" in classify_label("   ", None)["statuses"]
    assert "refusal_or_nonanswer" in classify_label("I cannot answer that", None)["statuses"]
    assert "max_tokens_truncation" in classify_label("Bon", "length")["statuses"]
    assert "unclosed_thinking_block" in classify_label("<think>Bon", None)["statuses"]

    # The comparison key folds case, punctuation and whitespace without ever
    # rewriting the text that is reported.
    assert label_compare_key("Anti-Magn") == label_compare_key("anti_magn")
    assert label_compare_key("Bon.") == label_compare_key("bon")
    assert label_compare_key(" Bon ") == label_compare_key("Bon")
    assert label_compare_key("Oper1") != label_compare_key("Operl")
    assert label_compare_key("Bon") != label_compare_key("AntiBon")


def malformed_protocol_metadata() -> None:
    """Malformed, missing and contradictory metadata is reported, never guessed."""
    expected_issues = {
        "both answer sets": ("both_allowed_choices_and_allowedAnswerLabels", "both_allowed_choices_and_allowed_labels"),
        "letter protocol with labels": ("letter_protocol_with_allowedAnswerLabels", "letter_protocol_with_allowed_answer_labels"),
        "label protocol with letters": ("label_protocol_with_allowedChoices",),
        "unknown protocol": ("unknown_answer_protocol",),
        "non-string protocol": ("answerProtocol_not_a_string",),
        "reordered taxonomy": ("allowedAnswerLabels_not_pinned_taxonomy",),
        "shortened taxonomy": ("allowedAnswerLabels_not_pinned_taxonomy",),
        "wrong benchmark": ("label_protocol_wrong_benchmark",),
        "prompt missing category": ("label_protocol_prompt_missing_categories",),
        "duplicated category": ("allowedAnswerLabels_malformed",),
        "labels as string": ("allowedAnswerLabels_malformed",),
        "non-string label entry": ("allowedAnswerLabels_malformed",),
        "empty label array": ("allowedAnswerLabels_malformed",),
        "no answer set": ("forced_choice_without_frozen_answer_set",),
        "letter protocol missing choices": ("letter_protocol_without_allowedChoices",),
        "label protocol missing labels": ("label_protocol_without_allowedAnswerLabels",),
    }
    rows = {
        "both answer sets": label_row(allowedChoices=["A", "B"]),
        "letter protocol with labels": label_row(answerProtocol="letter"),
        "label protocol with letters": label_row(allowedAnswerLabels=None, allowedChoices=["A"]),
        "unknown protocol": label_row(answerProtocol="ranking"),
        "non-string protocol": label_row(answerProtocol=7),
        "reordered taxonomy": label_row(allowedAnswerLabels=list(reversed(SEMANTICQA_LCC_LABELS))),
        "shortened taxonomy": label_row(allowedAnswerLabels=list(SEMANTICQA_LCC_LABELS[:4])),
        "wrong benchmark": label_row(benchmark="Some-Other-Benchmark"),
        "prompt missing category": label_row(prompt="Answer with the category name."),
        "duplicated category": label_row(allowedAnswerLabels=["Magn", "Magn", *SEMANTICQA_LCC_LABELS[2:]]),
        "labels as string": label_row(allowedAnswerLabels="Magn"),
        "non-string label entry": label_row(allowedAnswerLabels=[1, *SEMANTICQA_LCC_LABELS[1:]]),
        "empty label array": label_row(allowedAnswerLabels=[]),
        "no answer set": {"id": "semanticqa_lcc_000", "generative": False, "prompt": "Answer."},
        "letter protocol missing choices": letter_row(allowedChoices=None),
        "label protocol missing labels": label_row(allowedAnswerLabels=None),
    }
    for name, task in rows.items():
        contract = resolve_answer_protocol(task)
        assert contract.usable is False, name
        assert contract.issue_codes, name
        assert any(
            issue.startswith(expected_issues[name]) for issue in contract.issue_codes
        ), (name, contract.issue_codes)

        # A malformed row is annotated with the reason and never parsed as if it
        # had a valid frozen answer set.
        diag, report = one_row_diag(task, "Bon")
        assert diag["kind"] == "forced_choice_unusable_protocol", name
        assert diag["statuses"] == ["unusable_answer_protocol_metadata"], name
        assert diag["recoverableExplicitChoice"] is None, name
        assert "unusable_answer_protocol_metadata" in report["structuralStatuses"], name
        assert report["unusableAnswerProtocolMetadata"][0]["id"] == task["id"], name
        assert report["unusableAnswerProtocolMetadata"][0]["issues"], name
        assert report["answerProtocolCoverage"] == {"letter": 0, "label": 0}, name

    # A missing protocol is inferred only from an unambiguous row shape.
    for task, expected in [
        (label_row(answerProtocol=None), "label"),
        (letter_row(answerProtocol=None), "letter"),
    ]:
        contract = resolve_answer_protocol(task)
        assert contract.usable and contract.protocol == expected, task

    # A generative row must not freeze an answer set at all.
    generative = {"id": "gen-0", "generative": True, "prompt": "Write a summary."}
    assert resolve_answer_protocol(generative).usable
    bad_generative = dict(generative, answerProtocol="label", allowedAnswerLabels=list(SEMANTICQA_LCC_LABELS))
    contract = resolve_answer_protocol(bad_generative)
    assert contract.usable is False
    assert "generative_row_declares_allowedAnswerLabels" in contract.issue_codes


if __name__ == "__main__":
    main()
