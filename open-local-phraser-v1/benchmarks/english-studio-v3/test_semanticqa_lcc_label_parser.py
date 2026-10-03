#!/usr/bin/env python3
"""Focused tests for the SemanticQA LCC tolerant answer-label parser.

`score-semanticqa-lcc-english-core.py` is a format-tolerant diagnostic, not the
official exact-match evaluator. It may recover one clear category from harmless
wrappers (`Answer: Magn`, `Magn.`, `anti_magn`) but must never invent a category
the model did not answer, because a false recovery raises
`validOutputCoverage` and can turn an unparsed output into a scored hit.

The frozen taxonomy mixes case and contains a digit (`Oper1`), and several
categories are prefixes of longer words. The regression these tests pin is the
token boundary: an ASCII-alphabetic boundary recovered `Magn2` as `Magn` and
`Oper10` as `Oper1`, so an out-of-taxonomy token became a valid label. The
boundary is therefore ASCII alphanumeric.

The expected taxonomy is restated here rather than imported from a sibling
parser module, so this file pins the scorer's own contract and cannot be broken
by an unrelated parser refactor.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

HERE = Path(__file__).resolve().parent
SCORER_PATH = HERE / "score-semanticqa-lcc-english-core.py"

EXPECTED_LABELS = (
    "Magn",
    "AntiMagn",
    "Ver",
    "AntiVer",
    "Bon",
    "AntiBon",
    "Son",
    "Oper1",
)


def load_scorer() -> ModuleType:
    """Import the scorer by path; its filename is not an importable identifier."""
    spec = importlib.util.spec_from_file_location(
        "pari_score_semanticqa_lcc_english_core", SCORER_PATH
    )
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load scorer module from {SCORER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_taxonomy_is_the_frozen_eight_categories() -> None:
    scorer = load_scorer()
    assert scorer.LABELS == EXPECTED_LABELS, (
        f"scorer taxonomy drifted from the pinned 8-category set: {scorer.LABELS!r}"
    )
    assert scorer.LABEL_SET == set(EXPECTED_LABELS)


def test_standalone_labels_are_recovered() -> None:
    parse = load_scorer().parse_prediction
    for label in EXPECTED_LABELS:
        assert parse(label) == label, f"bare label {label!r} must be recovered"


def test_case_variants_are_recovered() -> None:
    parse = load_scorer().parse_prediction
    assert parse("MAGN") == "Magn"
    assert parse("OPER1") == "Oper1"
    assert parse("antimagn") == "AntiMagn"
    assert parse("aNtIvEr") == "AntiVer"
    assert parse("SoN") == "Son"


def test_surrounding_whitespace_is_tolerated() -> None:
    parse = load_scorer().parse_prediction
    assert parse("   Magn   ") == "Magn"
    assert parse("\tOper1\n") == "Oper1"
    assert parse("\n  antiVer  \n") == "AntiVer"


def test_punctuation_and_wrapper_phrasing_is_tolerated() -> None:
    parse = load_scorer().parse_prediction
    cases = {
        "Magn.": "Magn",
        "Magn!": "Magn",
        "Magn,": "Magn",
        "Answer: Magn": "Magn",
        "Answer: Oper1": "Oper1",
        "The answer is Magn.": "Magn",
        "The answer is Oper1": "Oper1",
        "Category: Son": "Son",
        "Magn (large degree of surprise)": "Magn",
    }
    for text, expected in cases.items():
        assert parse(text) == expected, f"{text!r} should recover {expected!r}"


def test_punctuation_separated_joins_keep_their_untouched_behavior() -> None:
    """Pin current behavior for separator-joined text, deliberately not endorsed.

    ``anti_magn``/``Anti-Magn``/``Anti_Bon`` are recovered as the trailing
    ``Magn``/``Bon`` token, because the scorer's tolerant contract splits on
    punctuation and then recovers one clear label, whereas
    ``protocol_output_diagnostics.label_compare_key`` reads the same strings as
    ``AntiMagn``/``AntiBon``. That divergence predates the digit-boundary fix and
    is out of its scope, so it is recorded here rather than silently changed.
    """
    parse = load_scorer().parse_prediction
    assert parse("anti_magn") == "Magn"
    assert parse("Anti-Magn") == "Magn"
    assert parse("Anti_Bon") == "Bon"


def test_digits_adjacent_to_a_label_are_not_recovered() -> None:
    """The regression: a longer alphanumeric token is not the category."""
    parse = load_scorer().parse_prediction
    for text in (
        "Magn2",
        "Magn0",
        "Magn01",
        "Magn2 is the answer",
        "Oper10",
        "Oper11",
        "Oper100",
        "Son1",
        "Son10",
        "Bon3",
        "Ver2",
        "AntiMagn2",
        "AntiVer7",
        "The category is Oper10",
    ):
        assert parse(text) is None, (
            f"{text!r} is not a bare taxonomy label and must not be recovered"
        )


def test_letters_adjacent_to_a_label_are_not_recovered() -> None:
    parse = load_scorer().parse_prediction
    for text in (
        "Magnita",
        "AMagn",
        "Magnx",
        "Oper1x",
        "Operl",
        "IncepOper1",
        "Very",
        "Bonus",
        "Verm",
        "Song",
    ):
        assert parse(text) is None, (
            f"{text!r} is a longer word, not a taxonomy label"
        )


def test_two_categories_are_ambiguous_and_refused() -> None:
    parse = load_scorer().parse_prediction
    for text in (
        "Magn and Ver",
        "Magn or Oper1",
        "Magn-Oper1",
        "Answer: Magn, though Ver is possible",
        "AntiMagn Ver",
        "Bon, Son",
    ):
        assert parse(text) is None, (
            f"{text!r} names two categories and must be ambiguous"
        )


def test_non_answers_and_empty_outputs_are_refused() -> None:
    parse = load_scorer().parse_prediction
    for text in ("", "   ", None, "I cannot answer", "unknown", "none of the above"):
        assert parse(text) is None, f"{text!r} is not a recoverable label"


def test_invalid_and_wrapped_outputs_separate_from_valid_coverage() -> None:
    """Only the wrapped real answer is a valid output; the rest stay invalid."""
    parse = load_scorer().parse_prediction
    rows = (
        ("Magn", "Magn2", None),
        ("Oper1", "Oper10", None),
        ("Magn", "Answer: Magn", "Magn"),
    )
    predictions = [parse(text) for _, text, _ in rows]
    assert predictions == [None, None, "Magn"], (
        f"out-of-taxonomy tokens must stay invalid, got {predictions!r}"
    )
    assert [pred == gold for (gold, _, _), pred in zip(rows, predictions)] == [
        False,
        False,
        True,
    ]


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"{len(tests)} SemanticQA LCC label parser tests passed.")


if __name__ == "__main__":
    main()
