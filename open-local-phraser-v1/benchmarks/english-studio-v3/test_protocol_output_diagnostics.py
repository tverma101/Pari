#!/usr/bin/env python3
from protocol_output_diagnostics import classify_choice
from word_studio_output_parser import diagnose


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

    print("protocol output diagnostics fixtures passed")


if __name__ == "__main__":
    main()
