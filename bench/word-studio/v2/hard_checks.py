"""Code checks run on every option before Claude judges it (#87).

A ``fail`` flag means the option breaks a rule the prompt states plainly, so it
is below the relevance bar without being judged. A ``warn`` flag is shown to the
judge but decides nothing: a paraphrase can drop "not" and stay correct ("will
not be able" -> "will be unable"), so only the judge can say.

These checks never read a model name and never produce a quality score.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

WORD_STUDIO = Path(__file__).resolve().parent.parent
if str(WORD_STUDIO) not in sys.path:
    sys.path.insert(0, str(WORD_STUDIO))

from v2.prompts import SENTENCE_KINDS  # noqa: E402
from word_studio_output_parser import (  # noqa: E402
    WORD_RE,
    comparison_key,
    near_duplicate_keys,
    parse_document,
    word_count,
)

CHECKS_VERSION = "ws2-hard-checks-v1"

#: Flags that put an option below the bar without judging. Everything else warns.
FAIL_FLAGS = {
    "empty": "the option is empty",
    "beyond_requested": "the option comes after the number of options the task asked for",
    "duplicate": "the same as, or a near copy of, an earlier option in this list",
    "echo": "repeats the selected text unchanged",
    "too_many_words": "tap_word allows at most three words, phrase_to_word exactly one",
    "missing_word": "word_sentences option does not contain the target word or a form of it",
    "not_shorter": "condense option is not shorter than the original",
    "number_changed": "a number in the original is missing from the option",
    "quote_dropped": "a quotation in the original is missing or altered in the option",
    "invented_number": "the option contains a number that is not in the paragraph",
}
WARN_FLAGS = {
    "negation_changed": "the original and the option disagree on negation words",
    "name_dropped": "a capitalised name in the original is missing from the option",
    "length_off": "paraphrase length is under half or over 1.75 times the original",
    "new_quotation": "the option has quoted text that is not in the paragraph",
    "copies_paragraph": "the option repeats a sentence already in the paragraph",
}

TAP_MAX_WORDS = 3
NUMBER_RE = re.compile(r"\d+(?:[.,:/]\d+)*%?")
NEGATIONS = frozenset({"not", "no", "never", "none", "nobody", "nothing", "neither", "nor", "nowhere",
                       "cannot", "without"})
QUOTED_RE = re.compile(r"[\"“”]([^\"“”]{3,})[\"“”]")
SENTENCE_SPLIT_RE = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\"”’)]))\s+")


def words(text: str) -> list[str]:
    return WORD_RE.findall(comparison_key(text))


def numbers(text: str) -> list[str]:
    return NUMBER_RE.findall(text)


def has_negation(text: str) -> bool:
    tokens = words(text)
    return any(t in NEGATIONS or t.endswith("n't") or t.endswith("n’t") for t in tokens)


def unquote(text: str) -> str:
    return comparison_key(text.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'"))


def names(sentence: str) -> list[str]:
    """Capitalised words that are not the first word of the sentence."""
    tokens = WORD_RE.findall(sentence)
    return [t for t in tokens[1:] if t[0].isupper() and t[1:].islower() and t != "I"]


SUFFIXES = sorted(["ations", "ation", "ition", "ments", "ment", "ness", "ities", "ity", "ence", "ance", "ent",
                   "ant", "ive", "ing", "ies", "ied", "ed", "es", "al", "ly", "s", "e", "y"], key=len, reverse=True)


def stem(word: str) -> str:
    """Strip one common suffix, keeping at least four letters: "deprivation" and "deprived" -> "depriv"."""
    key = comparison_key(word)
    for suffix in SUFFIXES:
        if key.endswith(suffix) and len(key) - len(suffix) >= 4:
            return key[: -len(suffix)]
    return key


def uses_word(text: str, word: str) -> bool:
    """True if ``text`` has ``word`` or a form of it. Lenient on purpose: the judge checks the usage."""
    target = stem(word)
    return any(t.startswith(target) or stem(t) == target for t in words(text))


def format_of(doc: Any) -> str:
    if not doc.options:
        return "unparseable"
    clean = (doc.mode == "json_object" and not doc.fenced and not doc.leading_prose and not doc.trailing_prose
             and not doc.invalid_entries)
    return "strict" if clean else "lenient"


def option_flags(task: dict[str, Any], text: str, earlier: list[str]) -> list[str]:
    kind = task["kind"]
    flags: list[str] = []
    key = comparison_key(text)
    if not key:
        return ["empty"]
    if any(key == e or near_duplicate_keys(key, e) for e in earlier):
        flags.append("duplicate")
    selected = (task.get("selection") or {}).get("text")
    if selected and key == comparison_key(selected):
        flags.append("echo")
    if kind == "tap_word" and word_count(text) > TAP_MAX_WORDS:
        flags.append("too_many_words")
    if kind == "phrase_to_word" and word_count(text) != 1:
        flags.append("too_many_words")
    if kind == "word_sentences":
        if not uses_word(text, task["word"]):
            flags.append("missing_word")
    if kind in SENTENCE_KINDS and selected:
        if kind == "condense" and word_count(text) >= word_count(selected):
            flags.append("not_shorter")
        option_numbers = numbers(text)
        if any(option_numbers.count(n) < numbers(selected).count(n) for n in set(numbers(selected))):
            flags.append("number_changed")
        for quote in task.get("quotes") or []:
            if unquote(quote["text"]) in unquote(selected) and unquote(quote["text"]) not in unquote(text):
                flags.append("quote_dropped")
                break
        if has_negation(selected) != has_negation(text):
            flags.append("negation_changed")
        option_key = unquote(text)
        if any(unquote(n) not in option_key for n in names(selected)):
            flags.append("name_dropped")
        if kind == "paraphrase":
            ratio = word_count(text) / max(1, word_count(selected))
            if ratio < 0.5 or ratio > 1.75:
                flags.append("length_off")
    paragraph = task["paragraph"]
    if any(n not in numbers(paragraph) for n in numbers(text)):
        flags.append("invented_number")
    if kind in SENTENCE_KINDS or kind == "word_sentences":
        paragraph_key = unquote(paragraph)
        if any(unquote(q) not in paragraph_key for q in QUOTED_RE.findall(text)):
            flags.append("new_quotation")
    if kind == "word_sentences":
        sentences = {comparison_key(s) for s in SENTENCE_SPLIT_RE.split(paragraph)}
        if key in sentences:
            flags.append("copies_paragraph")
    return flags


def check(task: dict[str, Any], output: dict[str, Any] | None) -> dict[str, Any]:
    """Check one candidate's output for one task. ``output`` is the runner's output record."""
    requested = task["requested_options"]
    result: dict[str, Any] = {"checks_version": CHECKS_VERSION, "task_id": task["id"], "requested": requested}
    if output is None or output.get("status") != "ok":
        result.update(format="no_output", parse_mode=None, returned=0, truncated=False, options=[],
                      error=(output or {}).get("error"))
        return result
    doc = parse_document(output.get("raw_text") or "")
    options = []
    earlier: list[str] = []
    for index, text in enumerate(doc.options):
        flags = option_flags(task, text, earlier)
        if index >= requested:
            flags.insert(0, "beyond_requested")
        earlier.append(comparison_key(text))
        fail = [f for f in flags if f in FAIL_FLAGS]
        warn = [f for f in flags if f in WARN_FLAGS]
        options.append({"index": index, "text": text, "fail": fail, "warn": warn, "judge": not fail})
    result.update(
        format=format_of(doc),
        parse_mode=doc.mode,
        returned=len(doc.options),
        truncated=output.get("finish_reason") == "length",
        options=options,
    )
    return result
