#!/usr/bin/env python3
"""CPU-only adversarial fixtures for GitHub issue #43.

One canonical parser/diagnostics contract must define what counts as a usable
Word Studio candidate for both offline scoring and streamed first-1/3/10 timing.
These fixtures cover the twelve adversarial cases named in the issue and prove:

- non-string JSON entries can never become candidate strings;
- Unicode/invisible variants cannot inflate unique depth;
- exact / normalized / near duplicate metrics stay separate;
- protected corruption and unchanged-source status are candidate-level;
- offline `diagnose` and incremental streaming agree on usable unique count.

No model, no GPU, no network, no answer keys.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from word_studio_output_parser import (
    ROUTE_ALTERNATIVES,
    ROUTE_IDENTITY_ALLOWED,
    ROUTE_INTENTIONAL_COMPRESSION,
    CandidateLedger,
    comparison_key,
    diagnose,
    near_duplicate_keys,
    normalize,
    parse_document,
    parse_options,
    partial_candidate_count,
    partial_usable_unique_count,
    usable_unique_count_of,
    route_from_task,
)

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run-english-core-vllm.py"
ZWSP = chr(0x200B)
ZWNJ = chr(0x200C)
NBSP = chr(0x00A0)
RLM = chr(0x200F)
NFD_E_ACUTE = "café"      # decomposed
NFC_E_ACUTE = "café"       # composed


def load_runner():
    """Load the hyphenated runner that owns the shared streaming contract."""
    spec = importlib.util.spec_from_file_location("pari_english_core_vllm_runner_43", RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {RUNNER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def json_options(values) -> str:
    return json.dumps({"options": values}, ensure_ascii=False)


# --- 1. typed JSON entries --------------------------------------------------

def test_typed_json_entries_are_rejected() -> None:
    raw = json_options([None, True, 3, {"x": 1}, ["nested"], "valid"])
    options, mode = parse_options(raw)
    assert mode == "json_object"
    assert options == ["valid"], options

    diag = diagnose(raw)
    assert diag["parsedCount"] == 1
    assert diag["usableUniqueCount"] == 1
    assert diag["invalidEntryCount"] == 5
    assert diag["invalidEntryTypes"] == {"array": 1, "boolean": 1, "null": 1, "number": 1, "object": 1}
    assert "word_studio_typed_invalid_entries" in diag["statuses"]
    # No non-string entry may appear anywhere in the candidate surface.
    for value in diag["options"]:
        assert isinstance(value, str)
    # A top-level JSON scalar is never a candidate list.
    scalar = diagnose("3")
    assert scalar["parsedCount"] == 0
    assert "word_studio_json_wrong_key" in scalar["statuses"]


def test_typed_json_streaming_never_yields_non_strings() -> None:
    raw = json_options([None, "alpha", 7, "beta"])
    values, _mode = __import__("word_studio_output_parser").partial_option_values(raw)
    assert values == ["alpha", "beta"], values
    # Usable depth counts strings only: never the number.
    assert partial_usable_unique_count(raw) == 2
    # The frozen raw counter follows the same typed rule, so the number and the
    # object never appear in any count.
    assert partial_candidate_count(raw) == 2


# --- 2/3. Unicode equivalence and invisible characters -----------------------

def test_nfc_nfd_and_invisible_variants_do_not_inflate_depth() -> None:
    raw = json_options([NFC_E_ACUTE, NFD_E_ACUTE, "clea" + ZWSP + "r", "clear", ZWNJ + "direct"])
    diag = diagnose(raw, requested=10)
    assert diag["parsedCount"] == 5
    assert diag["usableUniqueCount"] == 3, diag["usableUniqueCount"]
    assert diag["uniqueNormalizedCount"] == 3
    assert diag["duplicateTaxonomy"]["normalizedExactDuplicateCount"] == 2
    assert diag["duplicateCount"] == 2

    # Zero-width-only difference collapses.
    assert comparison_key("clear") == comparison_key("clea" + ZWSP + "r")
    # Bidi control characters never create a distinct candidate.
    assert comparison_key("direct") == comparison_key(RLM + "direct")
    # Visually empty candidates are rejected with a dedicated status.
    empty = diagnose(json_options([ZWSP + NBSP, "clear"]))
    assert empty["visuallyEmptyCandidateCount"] == 1
    assert "word_studio_visually_empty_candidate" in empty["statuses"]


def test_fullwidth_folding_is_conservative() -> None:
    # Full-width ASCII folds (issue: full-width punctuation/letters).
    assert comparison_key("ＡＢＣ，１２３") == comparison_key("ABC,123")
    # Conservative: compatibility-only characters keep their meaning even though
    # full NFKC would fold them, so no silent semantic merge is possible.
    assert comparison_key("\u00b2") != comparison_key("2")   # squared vs digit
    assert comparison_key("\u2460") != comparison_key("1")   # circled digit
    assert comparison_key("\u00bd") != comparison_key("1/2")  # vulgar fraction
    # Canonical (NFC) equivalence is intentional and always folded.
    assert comparison_key("\ufb01le") == comparison_key("file")  # fi ligature


# --- 4. duplicate with punctuation / whitespace formatting change ------------

def test_duplicate_taxonomy_is_separate_and_deterministic() -> None:
    raw = json_options([
        "clear and direct wording",
        "Clear, and direct wording",
        "clear  and  direct  wording",
        "a concise summary of the report",
        "a concise summary for the report",
        "rewrite in plain language",
        "use a formal register",
    ])
    diag = diagnose(raw, requested=10)
    taxonomy = diag["duplicateTaxonomy"]
    assert taxonomy["exactRawDuplicateCount"] == 0
    assert taxonomy["normalizedExactDuplicateCount"] == 2  # whitespace/case variants
    assert taxonomy["nearDuplicateCount"] == 1             # summary of/for
    assert taxonomy["uniqueUsableCount"] == 4
    assert diag["usableUniqueCount"] == 4
    # Deterministic: same input, same numbers, every time.
    assert diagnose(raw, requested=10)["duplicateTaxonomy"] == taxonomy


# --- 5. near duplicate vs genuinely different -------------------------------

def test_near_duplicate_heuristic_is_cheap_and_documented() -> None:
    near = [
        ("clear and direct wording", "clear, and direct wording"),
        ("a concise summary of the report", "a concise summary for the report"),
        ("make this shorter", "make this much shorter"),
    ]
    different = [
        ("rewrite in plain language", "use a formal register"),
        ("shorten the sentence", "expand the argument fully"),
        ("a concise summary", "an unrelated anecdote"),
        ("simplify the language", "simplify the wording"),
    ]
    for left, right in near:
        assert near_duplicate_keys(comparison_key(left), comparison_key(right)), (left, right)
    for left, right in different:
        assert not near_duplicate_keys(comparison_key(left), comparison_key(right)), (left, right)
    # Short candidates are never merged by the heuristic.
    assert not near_duplicate_keys("ok", "okay")
    assert not near_duplicate_keys(comparison_key("no"), comparison_key("no."))


# --- 6/7. protected content corruption --------------------------------------

def test_protected_corruption_is_candidate_level() -> None:
    source = "Ship the $4,200 invoice by 3:30 to acme@example.com."
    protected = ["$4,200", "3:30", "acme@example.com"]

    missing = diagnose(
        json_options(["Send the $4,200 invoice at 3:30 to acme@example.com"]), requested=10,
    )
    assert missing["usableUniqueCount"] == 1

    dropped = diagnose(
        json_options(["Send the invoice to acme@example.com", "Pay acme@example.com by 3:30"]),
        source=source, requested=10, protected=protected,
    )
    assert dropped["protectedContentCorruptionCount"] >= 1
    assert "word_studio_protected_corruption" in dropped["statuses"]

    altered = diagnose(
        json_options(["Send the $5,100 invoice by 3:30 to acme@example.com"]),
        source=source, requested=10, protected=protected,
    )
    details = altered["protectedContentDiagnostics"][0]
    assert "$4,200" in details["altered"], details
    assert "word_studio_protected_value_altered" in altered["statuses"]

    # Corrupted candidates are excluded from usable depth.
    ledger = CandidateLedger(source=source, requested=10, protected=protected)
    verdict = ledger.add("Send the $5,100 invoice by 3:30 to acme@example.com")
    assert verdict.reason == "protected_corruption", verdict
    ledger.add("Send the $4,200 invoice by 3:30 to acme@example.com")
    ledger.add("Email acme@example.com before 3:30 about the $4,200 charge")
    # The altered-number candidate is excluded from usable depth; the two intact
    # candidates stay distinct.
    assert ledger.protected_corruption_count == 1
    assert ledger.usable_unique_count == 2, [v.reason for v in ledger.verbatim]


def test_repeated_protected_value_requires_matching_occurrence_count() -> None:
    source = "Keep the SLA at 99.9% and the SLA at 99.9% unchanged."
    protected = ["99.9%"]
    ok = diagnose(
        json_options(["The SLA at 99.9% stays; the SLA at 99.9% is unchanged."]),
        source=source, requested=10, protected=protected,
    )
    assert ok["protectedContentCorruptionCount"] == 0

    # Plain substring presence is present, but the count dropped.
    short = diagnose(
        json_options(["The SLA at 99.9% stays unchanged."]),
        source=source, requested=10, protected=protected,
    )
    details = short["protectedContentDiagnostics"][0]
    assert "99.9%" in details["repeatedMismatch"], details
    assert "word_studio_protected_repeated_mismatch" in short["statuses"]

    # A location-sensitive span that survives but slides into unrelated
    # territory: substring presence alone would pass, so position drift is
    # reported separately (and is not corruption on its own).
    single_source = "The SLA floor is 99.9% and must stay there."
    drift = diagnose(
        json_options(["Totally different wording that still contains 99.9% once somewhere"]),
        source=single_source, requested=10,
        protected=[{"text": "99.9%", "start": 17, "end": 22}],
    )
    assert drift["protectedContentCorruptionCount"] == 0
    assert "word_studio_protected_position_drift" in drift["statuses"]
    assert drift["protectedContentDiagnostics"][0]["positionDrift"] == ["99.9%"]
    # An in-place candidate does not drift.
    stable = diagnose(
        json_options(["The SLA floor is 99.9% and it must stay there."]),
        source=single_source, requested=10,
        protected=[{"text": "99.9%", "start": 17, "end": 22}],
    )
    assert "word_studio_protected_position_drift" not in stable["statuses"]


# --- 8. unchanged source / route semantics ----------------------------------

def test_unchanged_source_is_route_aware() -> None:
    source = "We should ship the feature today."
    raw = json_options([
        source,
        "Release the feature today.",
        "Push the launch to tomorrow.",
    ])
    strict = diagnose(raw, source=source, requested=10)
    assert strict["unchangedSourceCount"] == 1
    assert strict["unchangedSourceUnusableCount"] == 1
    assert strict["usableUniqueCount"] == 2
    assert "contains_unchanged_source" in strict["statuses"]

    # A route whose contract explicitly permits identity output must not be
    # penalized for an unchanged copy.
    identity = diagnose(raw, source=source, requested=10, route=ROUTE_IDENTITY_ALLOWED)
    assert identity["unchangedCountsAsUsable"] is True
    assert identity["unchangedSourceUnusableCount"] == 0
    assert "contains_unchanged_source" not in identity["statuses"]
    assert identity["usableUniqueCount"] == 3

    # intentional_compression is a separate semantic contract.
    compression = diagnose(raw, source=source, requested=10, route=ROUTE_INTENTIONAL_COMPRESSION)
    assert compression["usableUniqueCount"] == 3
    assert "contains_unchanged_source" not in compression["statuses"]


def test_route_from_task_reads_the_declared_contract() -> None:
    assert route_from_task(None) == ROUTE_ALTERNATIVES
    assert route_from_task({"route": "intentional_compression"}) == ROUTE_INTENTIONAL_COMPRESSION
    assert route_from_task({"semanticMode": "intentional_compression"}) == ROUTE_INTENTIONAL_COMPRESSION
    assert route_from_task({"route": "allow_identity"}) == ROUTE_IDENTITY_ALLOWED
    assert route_from_task({"route": "rewrite"}) == ROUTE_ALTERNATIVES
    assert route_from_task({"selectedText": "x"}) == ROUTE_ALTERNATIVES


# --- 9/10. wrappers: fences, prose, commentary ------------------------------

def test_markdown_fenced_output_is_recovered_and_diagnosed() -> None:
    body = json_options(["clear", "plain", "direct", "simple", "readable"])
    fenced = "```json\n" + body + "\n```"
    document = parse_document(fenced)
    assert document.fenced is True
    assert document.mode == "json_object"
    assert len(document.options) == 5
    diag = diagnose(fenced)
    assert "word_studio_markdown_code_fence" in diag["statuses"]
    assert diag["usableUniqueCount"] == 5


def test_prose_and_commentary_are_diagnosed_not_regenerated() -> None:
    # Prose preamble in front of a list stays unparseable (frozen behavior) but
    # is now explained instead of silently zeroed.
    leading = diagnose("Here are ten great alternatives:\n1. one\n2. two")
    assert leading["parsedCount"] == 0
    assert "word_studio_unparseable_list" in leading["statuses"]
    assert "word_studio_leading_prose" in leading["statuses"]

    # Trailing commentary after a valid list keeps the candidates and flags it.
    trailing = diagnose(
        "1. clear\n2. plain\n3. direct\nI hope this helps!",
        requested=10,
    )
    assert trailing["parserMode"] == "numbered_or_bulleted_list"
    assert trailing["parsedCount"] == 3
    assert "word_studio_trailing_commentary" in trailing["statuses"]

    # One fluent paragraph for a multi-option request.
    paragraph = diagnose(
        "The team could ship the feature today, or perhaps wait until the "
        "release is ready and the tests have settled down.",
        requested=10,
    )
    assert paragraph["parsedCount"] == 0
    assert "word_studio_single_paragraph_for_multi_request" in paragraph["statuses"]

    # Wrong JSON key.
    wrong_key = diagnose(json.dumps({"alternatives": ["a", "b"]}), requested=10)
    assert wrong_key["parsedCount"] == 0
    assert "word_studio_json_wrong_key" in wrong_key["statuses"]
    assert wrong_key["jsonWrongKeys"] == ["alternatives"]

    # A commentary line mixed into the candidate list is rejected as a candidate.
    mixed = diagnose(
        json_options(["clear", "Here are some alternatives:", "direct"]),
        requested=10,
    )
    assert mixed["commentaryCandidateCount"] == 1
    assert mixed["usableUniqueCount"] == 2
    assert "contains_commentary" in mixed["statuses"]


# --- 11/12. streaming contract ---------------------------------------------

def _stream_tracker(**kwargs):
    runner = load_runner()
    return runner, runner.ProgressiveOptionTracker(**kwargs)


def test_chunked_stream_with_json_string_spanning_chunks() -> None:
    runner, tracker = _stream_tracker(requested=3)
    chunks = ['{"options":["a very long ', 'first candidate that spans ', 'chunks"']
    accumulated = ""
    for position, chunk in enumerate(chunks):
        accumulated += chunk
        tracker.observe(chunk, accumulated)
        # The closing quote only arrives in the last chunk, so candidate 1
        # completes on chunk 3, never before.
        expected = None if position < len(chunks) - 1 else "set"
        got = tracker.result(accumulated)["firstCandidateLatencySeconds"]
        assert (got is None) == (expected is None), (position, got)
    accumulated += ',"second","third"]}'
    tracker.observe(accumulated[-1], accumulated)
    tracker.finish(accumulated)
    result = tracker.result(accumulated)
    assert tracker.result(accumulated)["firstCandidateLatencySeconds"] is not None
    assert result["firstThreeCandidatesLatencySeconds"] is not None
    assert result["firstTenCandidatesLatencySeconds"] is None
    assert result["progressiveOptionTiming"]["identityExtractionMismatchCount"] == 0


def test_stream_threshold_requires_usable_unique_candidates() -> None:
    # 10 raw completed entries, but only 6 usable unique options: first-10 must
    # stay null even though the raw count reaches 10. The extras are a
    # zero-width duplicate, an unchanged copy of the source, and prose.
    source_copy = "The source sentence under test."
    values = [
        "alpha", "beta", "gamma", "delta", "epsilon", "zeta",
        "alpha", "ALPHA", "alpha" + ZWSP, "Here are some alternatives:", NBSP + ZWSP, source_copy,
    ]
    raw = json_options(values)
    runner, tracker = _stream_tracker(requested=10, source=source_copy)
    for index in range(0, len(raw), 7):
        chunk = raw[index:index + 7]
        tracker.observe(chunk, raw[:index + len(chunk)])
    tracker.finish(raw)
    result = tracker.result(raw)
    evidence = result["progressiveOptionTiming"]
    assert evidence["rawCompletedCandidateCount"] >= 9
    assert evidence["uniqueUsableCandidateCount"] == 6, evidence
    assert result["firstCandidateLatencySeconds"] is not None
    assert result["firstThreeCandidatesLatencySeconds"] is not None
    assert result["firstTenCandidatesLatencySeconds"] is None
    assert result["firstTenCandidatesLatencySeconds"] is None
    assert 10 in evidence["unmetThresholds"]


def test_incremental_and_offline_usable_counts_agree() -> None:
    cases = [
        (json_options(["one", "two", "three", "four", "five"]), None, ROUTE_ALTERNATIVES, None),
        (json_options(["x" * 0 + "clear", "clea" + ZWSP + "r", "plain", "direct"]), None, ROUTE_ALTERNATIVES, None),
        ("1. alpha\n2. beta\n3. alpha\n", None, ROUTE_ALTERNATIVES, None),
        ("1. alpha\n2. beta\nI hope this helps!\n", None, ROUTE_ALTERNATIVES, None),
        (json_options(["Ship $4,200 today", "Pay $5,100 today"]), "Ship $4,200 today", ROUTE_ALTERNATIVES, ["$4,200"]),
        (json_options(["same source", "different"]), "same source", ROUTE_ALTERNATIVES, None),
        (json_options(["same source", "different"]), "same source", ROUTE_IDENTITY_ALLOWED, None),
    ]
    for raw, source, route, protected in cases:
        offline = diagnose(raw, source=source, requested=10, route=route, protected=protected)
        incremental = partial_usable_unique_count(
            raw, source=source, requested=10, route=route, protected=protected
        )
        assert incremental == offline["usableUniqueCount"], (raw, incremental, offline["usableUniqueCount"])


def test_threshold_crossing_happens_once_and_null_preserved() -> None:
    raw = json_options(["a", "b", "c", "d", "e", "f", "g"])  # 7 usable unique only
    runner, tracker = _stream_tracker(requested=10)
    for index in range(0, len(raw), 5):
        chunk = raw[index:index + 5]
        tracker.observe(chunk, raw[:index + len(chunk)])
        tracker.observe(chunk, raw[:index + len(chunk)])  # duplicate re-observation
    tracker.finish(raw)
    result = tracker.result(raw)
    assert result["firstTenCandidatesLatencySeconds"] is None
    crossings = result["progressiveOptionTiming"]["crossings"]
    assert [c["threshold"] for c in crossings] == [1, 3]
    assert result["progressiveOptionTiming"]["uniqueUsableCandidateCount"] == 7
    # Streaming evidence equals the offline usable-unique contract.
    assert result["diagnostics"]["usableUniqueCount"] == 7


def test_normalize_back_compat_and_final_incremental_agreement() -> None:
    """Runners still import `normalize`, and final == incremental must hold."""
    # The old whitespace/case contract is preserved exactly.
    assert normalize("  Clear   and  Direct ") == "clear and direct"
    assert normalize("") == "" and normalize(None) == ""
    # comparison_key is a strict superset: it additionally folds invisible
    # characters, exotic whitespace and full-width ASCII.
    assert comparison_key("clea" + ZWSP + "r") == comparison_key("clear")
    assert comparison_key("ＡＢ") == comparison_key("AB")

    ctx = {
        "source": "clear",
        "requested": 10,
        "route": ROUTE_ALTERNATIVES,
        "protected": ["$4,200"],
    }
    cases = [
        json_options([None, True, 3, {"x": 1}, "valid"]),
        json_options(["café", "café", "clea" + ZWSP + "r", "clear", ZWSP + NBSP]),
        "```json\n" + json_options(["a", "b"]) + "\n```",
        "```\n" + json_options(["only this"]) + "\n```",
        "1. clear\n2. clear\n3. plain\nI hope this helps!\n",
        json_options(["alpha", "beta", "gamma"]),
    ]
    for raw in cases:
        offline = diagnose(raw, **ctx)["usableUniqueCount"]
        assert partial_usable_unique_count(raw, final=True, **ctx) == offline, raw
        # A mid-stream scan can lag the final count but must never exceed it.
        assert partial_usable_unique_count(raw, final=False, **ctx) <= offline, raw


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"word studio usable-contract fixtures passed ({len(tests)} tests)")


if __name__ == "__main__":
    main()
