"""Regression test for the shared Python forced-choice parser."""

from english_core_choice_parser import parse_choice_letter

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
}

rejected = [
    "",
    "A because it sounds better",
    "The answer is A because...",
    "A or B",
    "Probably A",
    "I choose A",
    "ANSWERA",
    "Option A or B",
    "A, B",
]

for text, expected in accepted.items():
    actual = parse_choice_letter(text)
    assert actual == expected, (text, expected, actual)

for text in rejected:
    actual = parse_choice_letter(text)
    assert actual is None, (text, actual)

print({"accepted": len(accepted), "rejected": len(rejected), "status": "pass"})
