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

print({"accepted": len(accepted), "rejected": len(rejected), "status": "pass"})
