"""Regression test for the shared Python forced-choice parser.

Covers the historical accepted/rejected sets, the task-aware allowed-choice
contract from GitHub issue #44, and the frozen Unicode/anchoring policy.
"""

from english_core_choice_parser import (
    STATUS_AMBIGUOUS,
    STATUS_EMPTY,
    STATUS_NO_ANCHORED_ANSWER,
    STATUS_RECOVERABLE_ALLOWED,
    STATUS_RECOVERABLE_INVALID_LABEL,
    STATUS_STRICT_ALLOWED,
    STATUS_STRICT_INVALID_LABEL,
    STATUS_WHITESPACE,
    allowed_choices_from_task,
    normalize_allowed_choices,
    parse_choice,
    parse_choice_letter,
)

accepted = {
    "A": "A",
    "A.": "A",
    "b)": "B",
    "Answer: C": "C",
    "Answer = D": "D",
    "Answer is E": "E",
    "The answer is F": "F",
    "The answer: G": "G",
    "Option H": "H",
    "  i  ": "I",
    "I choose J": "J",
    "I'd pick K.": "K",
    "I would select L": "L",
    "My choice is M": "M",
    "A. same": "A",
    "A. acceptable": "A",
    "B) This is the better-formed option.": "B",
    "C: Because it fits the context.": "C",
    "D) a short explanation\nwith detail": "D",
    "The answer is A because the verb agrees.": "A",
    "The answer is A because...": "A",
    "Answer: B — it preserves the meaning.": "B",
    "Option C: the second clause is grammatical.": "C",
    "I choose D because it directly answers the question.": "D",
    "My answer is E because it fits the context.": "E",
    "F is the correct answer.": "F",
    "G because it matches the example.": "G",
    "A because it sounds better": "A",
}

rejected = [
    "",
    "A or B",
    "Probably A",
    "ANSWERA",
    "Option A or B",
    "A, B",
    "A. or B",
    "A. B. is also plausible",
    "A. and B both work",
    "A. B or C",
    "A. A or B",
    "I choose A or B",
    "The answer is A or B",
    "A is correct or B is correct",
]

for text, expected in accepted.items():
    actual = parse_choice_letter(text)
    assert actual == expected, (text, expected, actual)

for text in rejected:
    actual = parse_choice_letter(text)
    assert actual is None, (text, actual)


# --- Issue #44: the parser is task-aware and never consults the gold answer ---

AB = ["A", "B"]
ABCD = ["A", "B", "C", "D"]

# (text, allowedChoices, expected status, expected letter, expected invalid label)
task_aware = [
    # 1. valid boundary labels on both a 2-choice and a >2-choice task.
    ("A", AB, STATUS_STRICT_ALLOWED, "A", None),
    ("B", AB, STATUS_STRICT_ALLOWED, "B", None),
    ("A", ABCD, STATUS_STRICT_ALLOWED, "A", None),
    ("D", ABCD, STATUS_STRICT_ALLOWED, "D", None),
    # 2/3. one letter beyond the allowed set, including Z on an A/B task.
    ("C", AB, STATUS_STRICT_INVALID_LABEL, None, "C"),
    ("Z", AB, STATUS_STRICT_INVALID_LABEL, None, "Z"),
    ("E", ABCD, STATUS_STRICT_INVALID_LABEL, None, "E"),
    # 4. allowed label plus explanation stays a valid recoverable choice.
    ("Answer: B", AB, STATUS_RECOVERABLE_ALLOWED, "B", None),
    ("B. it preserves the meaning", AB, STATUS_RECOVERABLE_ALLOWED, "B", None),
    # 5. invalid label plus explanation is malformed, not a wrong answer.
    ("Answer: C because it fits", AB, STATUS_RECOVERABLE_INVALID_LABEL, None, "C"),
    ("C because it fits the context", AB, STATUS_RECOVERABLE_INVALID_LABEL, None, "C"),
    # 6. allowed + invalid labels together are reported as an invalid label.
    ("Answer: A. Answer: Z", AB, STATUS_RECOVERABLE_INVALID_LABEL, None, "Z"),
    # 7. self-correction from A to B is ambiguous, not first-label-wins.
    ("A. Actually B", AB, STATUS_AMBIGUOUS, None, None),
    ("Answer: A. Wait, B is better", AB, STATUS_AMBIGUOUS, None, None),
    ("A. Actually Z", AB, STATUS_RECOVERABLE_INVALID_LABEL, None, "Z"),
    # 8. repeated same answer marker is a restatement, not a conflict.
    ("Answer: A. Answer: A", AB, STATUS_RECOVERABLE_ALLOWED, "A", None),
    ("Answer: A. Answer: B", AB, STATUS_AMBIGUOUS, None, None),
    # 9. full-width and confusable letters never normalize into a choice.
    ("\uff21", AB, STATUS_NO_ANCHORED_ANSWER, None, None),  # full-width A
    ("\uff22", AB, STATUS_NO_ANCHORED_ANSWER, None, None),  # full-width B
    ("Answer: \uff21", AB, STATUS_NO_ANCHORED_ANSWER, None, None),
    ("\u0410", AB, STATUS_NO_ANCHORED_ANSWER, None, None),  # Cyrillic A
    ("\u212a", AB, STATUS_NO_ANCHORED_ANSWER, None, None),  # Kelvin sign
    ("\u017f", AB, STATUS_NO_ANCHORED_ANSWER, None, None),  # long s
    ("\u0131", AB, STATUS_NO_ANCHORED_ANSWER, None, None),  # dotless i
    ("\u0130", AB, STATUS_NO_ANCHORED_ANSWER, None, None),  # I with dot above
    ("Answer: \u212a", AB, STATUS_NO_ANCHORED_ANSWER, None, None),
    # 10. lowercase ASCII is folded; other case mappings are not.
    ("b", AB, STATUS_STRICT_ALLOWED, "B", None),
    ("answer: b", AB, STATUS_RECOVERABLE_ALLOWED, "B", None),
    # Markdown/code fences, leading bullets, and list markers are not anchored.
    ("```\nA\n```", AB, STATUS_NO_ANCHORED_ANSWER, None, None),
    ("`A`", AB, STATUS_NO_ANCHORED_ANSWER, None, None),
    ("**A**", AB, STATUS_NO_ANCHORED_ANSWER, None, None),
    ("- A", AB, STATUS_NO_ANCHORED_ANSWER, None, None),
    ("* A", AB, STATUS_NO_ANCHORED_ANSWER, None, None),
    ("\u2022 A", AB, STATUS_NO_ANCHORED_ANSWER, None, None),  # bullet
    ("1. A", AB, STATUS_NO_ANCHORED_ANSWER, None, None),
    # Multi-choice separators stay ambiguous / non-answers.
    ("A/B", AB, STATUS_NO_ANCHORED_ANSWER, None, None),
    ("A & B", AB, STATUS_NO_ANCHORED_ANSWER, None, None),
    ("both A and B", AB, STATUS_NO_ANCHORED_ANSWER, None, None),
    ("Answer: A or B", AB, STATUS_AMBIGUOUS, None, None),
    ("Answer: A / B", AB, STATUS_AMBIGUOUS, None, None),
    # Empty / whitespace outputs keep their dedicated statuses.
    ("", AB, STATUS_EMPTY, None, None),
    (None, AB, STATUS_EMPTY, None, None),
    ("   \n\t ", AB, STATUS_WHITESPACE, None, None),
    # Prose that merely mentions a later allowed letter is not rescanned.
    ("Probably A because it sounds better", AB, STATUS_NO_ANCHORED_ANSWER, None, None),
    ("Answer: B. The clause ending here. A is not it.", AB, STATUS_RECOVERABLE_ALLOWED, "B", None),
]

for text, allowed, status, letter, invalid in task_aware:
    result = parse_choice(text, allowed)
    assert result.status == status, (text, allowed, status, result.status)
    assert result.letter == letter, (text, allowed, letter, result.letter)
    assert result.invalid_option_label == invalid, (text, allowed, invalid, result.invalid_option_label)
    assert result.allowed_set_frozen, (text, allowed)
    if status in (STATUS_STRICT_ALLOWED, STATUS_RECOVERABLE_ALLOWED):
        assert result.letter in allowed, (text, result.letter)
    else:
        assert result.letter is None, (text, result.letter)

# Strict and recoverable views share one allowed-set rule.
for text, allowed, status, letter, _invalid in task_aware:
    result = parse_choice(text, allowed)
    if result.strict_form:
        assert status == STATUS_STRICT_ALLOWED, (text, status)
        assert result.letter == letter
    assert parse_choice_letter(text, allowed) == result.letter, text

# An impossible label reduces protocol-valid coverage for both views.
for text in ("Z", "C", "Answer: C", "C because it fits"):
    strict_result = parse_choice(text, AB)
    assert strict_result.letter is None, text
    assert strict_result.status in (
        STATUS_STRICT_INVALID_LABEL,
        STATUS_RECOVERABLE_INVALID_LABEL,
    ), (text, strict_result.status)


# --- The parser has no gold-answer input at all ---------------------------

import inspect

from english_core_choice_parser import ChoiceParse

for func in (parse_choice, parse_choice_letter, allowed_choices_from_task, normalize_allowed_choices):
    params = set(inspect.signature(func).parameters)
    assert not (params & {"answer", "answers", "gold", "goldLabel", "expected", "expectedLetter", "label"}), (
        func.__name__,
        params,
    )

signature = inspect.signature(ChoiceParse)
assert not (set(signature.parameters) & {"answer", "answers", "gold", "goldLabel", "expected", "expectedLetter"})

# The only task fields the parser reads are the frozen allowed-label set.
assert allowed_choices_from_task({"id": "x", "allowedChoices": ["B", "A"]}) == ("A", "B")
assert allowed_choices_from_task({"id": "x", "allowed_choices": ["A", "B"]}) == ("A", "B")
assert allowed_choices_from_task({"id": "x"}) is None
assert allowed_choices_from_task({"id": "x", "allowedChoices": None}) is None

# Ambiguity is never resolved by a gold label: two gold values give the same
# result, so the allowed set cannot be leaking the answer.
for gold in ("A", "B"):
    result = parse_choice("Answer: A. Answer: B", AB)
    assert result.status == STATUS_AMBIGUOUS and result.letter is None, gold


# --- Allowed-choice set validation is strict ------------------------------

assert normalize_allowed_choices("AB") == ("A", "B")
assert normalize_allowed_choices(["A", "A", "B"]) == ("A", "B")
assert normalize_allowed_choices(["D", "A"]) == ("A", "D")

for bad in ([], ["AA"], ["A", 2], [""], ["\u00c4"], {"A": True}, "A B", ["A", ""], ["a", "b"]):
    try:
        normalize_allowed_choices(bad)
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError(f"expected ValueError for {bad!r}")


# --- Unfrozen task files keep the historical permissive behavior ----------

legacy = parse_choice("Z")
assert legacy.letter == "Z"
assert legacy.status == STATUS_STRICT_ALLOWED
assert legacy.allowed_set_frozen is False
assert parse_choice_letter("Z") == "Z"

print(
    {
        "accepted": len(accepted),
        "rejected": len(rejected),
        "taskAware": len(task_aware),
        "status": "pass",
    }
)
