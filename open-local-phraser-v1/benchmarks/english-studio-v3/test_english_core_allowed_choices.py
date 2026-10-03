#!/usr/bin/env python3
"""Focused tests for the frozen allowed-choice metadata contract.

Every English Core forced-choice task must freeze exactly one model-visible
answer set. A letter-protocol task freezes the first N letters for its N
rendered options; SemanticQA LCC freezes the ordered 8-category taxonomy names
because it is a native label-name protocol with no lettered options. The set is
derived from structured build-time metadata, never from gold, and the rendered
prompt must agree with it.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def stub_heavy_dependencies() -> None:
    """Stand in for the public-fast builder's dataset libraries.

    The builder imports `datasets`/`huggingface_hub` at module load, but the
    frozen prompt/choice helpers it exposes are pure functions. Stubbing the two
    modules lets the test exercise the real renderer on CPU without installing
    the full data stack or touching the network.
    """
    if "datasets" not in sys.modules:
        stub = types.ModuleType("datasets")
        stub.__version__ = "stub"
        stub.get_dataset_config_names = lambda *a, **k: []
        stub.load_dataset = lambda *a, **k: []
        sys.modules["datasets"] = stub
    if "huggingface_hub" not in sys.modules:
        hub = types.ModuleType("huggingface_hub")
        hub.__version__ = "stub"

        class _Api:
            def dataset_info(self, *a, **k):
                raise RuntimeError("stubbed: no network access in this test")

        hub.HfApi = _Api
        sys.modules["huggingface_hub"] = hub


def load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


screen = load("build_english_core_fixed_screen", "build-english-core-fixed-screen.py")
stub_heavy_dependencies()
public_fast = load("build_english_core_public_fast", "build-english-core-public-fast.py")


SEMANTICQA_LABELS = list(screen.SEMANTICQA_LCC_LABELS)


def letter_row(choices: list[str], **extra: Any) -> dict[str, Any]:
    """A letter-protocol row rendered the way the public-fast builder does."""
    task_id = extra.pop("id", "pub-test-0000")
    shuffled, _ = public_fast.permute_choices(task_id, choices, 0)
    row = {
        "id": task_id,
        "dimension": "grammar_syntax",
        "source": "WiC",
        "phenomenon": "word_sense_discrimination",
        "prompt": public_fast.choice_prompt(
            "Does the target have the same meaning in both sentences?", shuffled
        ),
        "generative": False,
        "allowedChoices": list(public_fast.LETTERS[: len(shuffled)]),
        "answerProtocol": "letter",
    }
    row.update(extra)
    return row


def semanticqa_row(**extra: Any) -> dict[str, Any]:
    """A label-protocol row whose prompt renders the frozen taxonomy."""
    taxonomy = "\n".join(f"{label}\tdescription of {label}" for label in SEMANTICQA_LABELS)
    row = {
        "id": "semanticqa_lcc_000",
        "dimension": "collocation_naturalness",
        "benchmark": screen.SEMANTICQA_LCC_BENCHMARK,
        "generative": False,
        "prompt": (
            f"Categories:\n{taxonomy}\nContext: the collocation is fixed.\n"
            "Collocation: fix a problem\nAnswer with the category name."
        ),
        "answerProtocol": "label",
        "allowedAnswerLabels": list(SEMANTICQA_LABELS),
    }
    row.update(extra)
    return row


def expect_reject(row: dict[str, Any], fragment: str) -> None:
    try:
        screen.validate_allowed_choices(row, "lane", 1)
    except SystemExit as exc:
        assert fragment in str(exc), f"expected {fragment!r} in {exc}"
        return
    raise AssertionError(f"row was accepted but should have been rejected: {row}")


def rendered_option_labels(prompt: str) -> list[str]:
    """Labels the model actually sees, in rendered order."""
    labels: list[str] = []
    for line in prompt.splitlines():
        stripped = line.strip()
        if len(stripped) >= 2 and stripped[0].isalpha() and stripped[1] == ".":
            labels.append(stripped[0])
        elif labels:
            break
    return labels


def test_binary_public_rows_freeze_two_letters() -> None:
    """WiC/CoLA/PAWS rows are binary, so the frozen set is exactly A and B."""
    for task_id in ("pub-wic-0000", "pub-cola-0000", "pub-paws-0000", "pub-blimp-agreement-000"):
        row = letter_row(["same", "different"], id=task_id)
        assert row["allowedChoices"] == ["A", "B"]
        assert screen.validate_allowed_choices(row, "public_fast", 1) == "letter"
        assert rendered_option_labels(row["prompt"]) == ["A", "B"]
        assert row["prompt"].rstrip().endswith("Answer only with the letter.")


def test_binary_option_permutation_keeps_the_frozen_set_truthful() -> None:
    """The frozen set describes the rendered options, not the source order."""
    first_options = set()
    for index in range(40):
        row = letter_row(["acceptable", "unacceptable"], id=f"pub-cola-{index:04d}")
        assert screen.validate_allowed_choices(row, "public_fast", 1) == "letter"
        assert rendered_option_labels(row["prompt"]) == ["A", "B"]
        body = [line for line in row["prompt"].splitlines() if line[:2] in {"A.", "B."}]
        first_options.add(body[0])
    # The permutation is real: either source option can sit behind label A, and
    # the frozen set stays A,B because it describes the rendered labels.
    assert first_options == {"A. acceptable", "A. unacceptable"}


def test_abcd_cases_freeze_four_letters() -> None:
    """Four-option rows freeze A-D and the prompt renders exactly those labels."""
    row = letter_row(["first", "second", "third", "fourth"], id="ec-fc-4", source="Pari")
    assert row["allowedChoices"] == ["A", "B", "C", "D"]
    assert screen.validate_allowed_choices(row, "shadow", 1) == "letter"
    assert rendered_option_labels(row["prompt"]) == ["A", "B", "C", "D"]


def test_three_option_rows_freeze_three_letters() -> None:
    """A three-option row freezes A-C, not the alphabet's full length."""
    row = letter_row(["one", "two", "three"], id="ec-fc-3", source="Pari")
    assert row["allowedChoices"] == ["A", "B", "C"]
    assert screen.validate_allowed_choices(row, "shadow", 1) == "letter"


def test_eight_way_semanticqa_freezes_label_names() -> None:
    """The 8-way lane freezes taxonomy names, never letters."""
    row = semanticqa_row()
    assert row["answerProtocol"] == "label"
    assert row["allowedAnswerLabels"] == SEMANTICQA_LABELS
    assert "allowedChoices" not in row, "label protocol must not claim a letter set"
    assert screen.validate_allowed_choices(row, "semanticqa_lcc", 1) == "label"
    for label in SEMANTICQA_LABELS:
        assert label in row["prompt"]


def test_semanticqa_builder_emits_the_label_protocol() -> None:
    """The producer writes the same contract the assembler validates."""
    source = (HERE / "build-semanticqa-lcc-english-core.py").read_text(encoding="utf-8")
    assert '"answerProtocol": "label"' in source
    assert '"allowedAnswerLabels": list(LABELS)' in source
    # Gold stays in the separate answers file; the task row must not carry it.
    assert '"label": row["label"]' in source


def test_public_fast_builder_emits_the_letter_protocol() -> None:
    """The public-fast producer freezes the set from the rendered choice count."""
    source = (HERE / "build-english-core-public-fast.py").read_text(encoding="utf-8")
    assert '"allowedChoices": list(LETTERS[: len(shuffled)]),' in source
    assert '"answerProtocol": "letter"' in source


def test_forced_choice_without_any_frozen_set_is_rejected() -> None:
    """A missing set is a contract bug, never silently accepted."""
    row = letter_row(["same", "different"])
    del row["allowedChoices"]
    del row["answerProtocol"]
    expect_reject(row, "declares no frozen answer set")


def test_declaring_both_protocols_is_rejected() -> None:
    """Exactly one frozen answer protocol is allowed per task."""
    expect_reject(semanticqa_row(allowedChoices=["A", "B"]), "both allowedChoices and allowedAnswerLabels")


def test_letter_protocol_without_choices_is_rejected() -> None:
    row = letter_row(["same", "different"])
    del row["allowedChoices"]
    expect_reject(row, "answerProtocol 'letter' but allowedChoices is absent")


def test_label_protocol_without_labels_is_rejected() -> None:
    row = semanticqa_row()
    del row["allowedAnswerLabels"]
    expect_reject(row, "answerProtocol 'label' but allowedAnswerLabels is absent")


def test_letters_out_of_order_are_rejected() -> None:
    row = letter_row(["same", "different"])
    row["allowedChoices"] = ["B", "A"]
    expect_reject(row, "must be the first N labels in order")


def test_rendered_option_block_must_match_the_frozen_set() -> None:
    """The prompt the model sees is cross-checked against the frozen set."""
    row = letter_row(["same", "different"], id="pub-wic-9999")
    row["prompt"] = row["prompt"].replace("A. ", "C. ", 1)
    expect_reject(row, "do not match")


def test_non_contiguous_rendered_labels_are_rejected() -> None:
    row = letter_row(["one", "two", "three", "four"], id="ec-fc-4", source="Pari")
    row["prompt"] = row["prompt"].replace("C. ", "E. ", 1)
    expect_reject(row, "do not match")


def test_label_protocol_must_use_the_pinned_taxonomy() -> None:
    expect_reject(
        semanticqa_row(allowedAnswerLabels=list(reversed(SEMANTICQA_LABELS))),
        "must be the ordered SemanticQA 8-category taxonomy",
    )


def test_label_protocol_rejects_duplicates_and_non_strings() -> None:
    duplicated = list(SEMANTICQA_LABELS)
    duplicated[-1] = duplicated[0]
    expect_reject(semanticqa_row(allowedAnswerLabels=duplicated), "must not repeat a category")
    expect_reject(semanticqa_row(allowedAnswerLabels=[*SEMANTICQA_LABELS[:7], 8]), "must be strings")
    expect_reject(semanticqa_row(allowedAnswerLabels=[]), "non-empty array")


def test_label_protocol_is_reserved_for_the_semanticqa_benchmark() -> None:
    expect_reject(semanticqa_row(benchmark="Something-Else"), "reserved for SemanticQA-LCC-8cat")


def test_label_protocol_requires_the_rendered_taxonomy() -> None:
    row = semanticqa_row()
    row["prompt"] = "Categories:\nMagn\tone\nContext: c\nCollocation: x\nAnswer with the category name."
    expect_reject(row, "does not render the allowed categories")


def test_unknown_answer_protocol_is_rejected() -> None:
    expect_reject(letter_row(["same", "different"], answerProtocol="vibes"), "unknown answerProtocol")


def test_existing_shadow_lane_satisfies_the_contract() -> None:
    """The frozen shadow artifact already in the tree validates unchanged."""
    path = HERE / "english-core-shadow.jsonl"
    if not path.is_file():
        print("skipping shadow-lane regression: english-core-shadow.jsonl is not present")
        return
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    forced = 0
    for index, row in enumerate(rows, 1):
        if row.get("generative"):
            assert row.get("allowedChoices") is None, row["id"]
            assert row.get("allowedAnswerLabels") is None, row["id"]
            continue
        assert screen.validate_allowed_choices(row, "shadow", index) == "letter", row["id"]
        forced += 1
    assert forced > 0
    widths = {len(row["allowedChoices"]) for row in rows if not row.get("generative")}
    assert widths & {2, 3, 4}, f"expected binary/three/four-option rows, saw {widths}"


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"{len(tests)} allowed-choice contract tests passed.")


if __name__ == "__main__":
    main()
