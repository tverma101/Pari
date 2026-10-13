#!/usr/bin/env python3
"""Focused tests for the shared protected-content contract (issue #51).

These tests exercise ``studio_backend/protected_content.py`` and consume the
same language-neutral fixture corpus as the TypeScript app
(``tests/fixtures/protected-content-contract-v1.json``). CPU-only; no model, no
network. Run directly (``python3 test_studio_protected_content.py``) or via
pytest.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from studio_backend.protected_content import (  # noqa: E402
    PROTECTED_CONTENT_CONTRACT_VERSION,
    ProtectedContentError,
    compute_protected_span_sha256,
    compute_selection_sha256,
    compute_source_sha256,
    evaluate_protected_content,
    exact_occurrences,
    extract_protected_spans,
    normalize_protected_spans,
    protected_spans_for_evaluation,
    span_from_wire,
    utf16_length,
)
from studio_backend.range_encoding import RANGE_ENCODING_VERSION  # noqa: E402


FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "protected-content-contract-v1.json"
)


def utf16_to_index(text: str, offset: int) -> int:
    """Convert a UTF-16 code-unit offset to a Python string index."""

    units = 0
    for index, char in enumerate(text):
        if units == offset:
            return index
        units += 2 if ord(char) > 0xFFFF else 1
        if units > offset:
            raise AssertionError("offset inside a surrogate pair")
    if units == offset:
        return len(text)
    raise AssertionError("offset out of range")


def reported_span_ids(result) -> list[str]:
    return sorted(
        set(
            list(result.missing_span_ids)
            + list(result.altered_span_ids)
            + list(result.repeated_mismatch_span_ids)
            + list(result.position_drift_span_ids)
            + list(result.introduced_span_ids)
        )
    )


class SharedFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_header(self) -> None:
        self.assertEqual(self.fixture["contractVersion"], PROTECTED_CONTENT_CONTRACT_VERSION)
        self.assertEqual(self.fixture["rangeEncoding"], RANGE_ENCODING_VERSION)
        self.assertEqual(self.fixture["identity"]["algorithm"], "sha256-utf8")
        self.assertEqual(
            self.fixture["identity"]["preimageFields"],
            ["rangeEncoding", "sourceSha256", "wireStart", "wireEnd", "text"],
        )
        self.assertEqual(self.fixture["identity"]["preimageSeparator"], "\u001f")

    def test_identity_vectors(self) -> None:
        self.assertEqual(
            compute_source_sha256(""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )
        self.assertEqual(
            compute_source_sha256("abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        )
        for vector in self.fixture["identityVectors"]:
            with self.subTest(vector["id"]):
                self.assertEqual(
                    compute_source_sha256(vector["text"]), vector["sourceSha256"]
                )
                start = utf16_to_index(vector["text"], vector["range"]["start"])
                end = utf16_to_index(vector["text"], vector["range"]["end"])
                self.assertEqual(
                    compute_protected_span_sha256(
                        self.fixture["rangeEncoding"],
                        vector["sourceSha256"],
                        vector["range"]["start"],
                        vector["range"]["end"],
                        vector["text"][start:end],
                    ),
                    vector["rangeSha256"],
                )

    def test_shared_fixture_corpus(self) -> None:
        for case in self.fixture["cases"]:
            with self.subTest(case["id"]):
                kwargs = {
                    "route": case["route"],
                    "anchor_policy": case["anchorPolicy"],
                    "protected": [dict(span) for span in case["protectedSpans"]],
                }
                if "selection" in case:
                    sel = case["selection"]
                    kwargs["selection"] = (
                        utf16_to_index(case["sourceText"], sel["start"]),
                        utf16_to_index(case["sourceText"], sel["end"]),
                    )
                if "candidateRange" in case:
                    rng = case["candidateRange"]
                    kwargs["candidate_range"] = (
                        utf16_to_index(case["candidateText"], rng["start"]),
                        utf16_to_index(case["candidateText"], rng["end"]),
                    )
                result = evaluate_protected_content(
                    case["sourceText"], case["candidateText"], **kwargs
                )
                expect = case["expect"]
                self.assertEqual(result.safe, expect["safe"], result.failure_class)
                self.assertEqual(result.contract_version, PROTECTED_CONTENT_CONTRACT_VERSION)
                if not expect["safe"]:
                    self.assertEqual(result.failure_class, expect["failureClass"])
                if "spanIds" in expect:
                    self.assertEqual(reported_span_ids(result), sorted(expect["spanIds"]))


class ExtractionTests(unittest.TestCase):
    SAMPLES = (
        'Dr. Maya Chen wrote, "Keep the 42.5% result unchanged" in 2024. Email '
        "maya@example.com or visit https://example.com/report. The device may "
        "not change $1,200.",
        'Intro line.\n```json\n{"a": 1}\n```\nOutro line.',
        "Call `build_plan()` before review.",
        "Renew on 2026-08-10 and meet at 3:30.",
        "Pay $4,200 by 99.9% today.",
        "The total is $20.",
    )

    def test_every_extracted_span_reproduces_source_text(self) -> None:
        for sample in self.SAMPLES:
            for span in extract_protected_spans(sample):
                self.assertEqual(sample[span.start : span.end], span.text, span.kind)
                self.assertGreaterEqual(
                    len(exact_occurrences(sample, span.text)), 1, span.text
                )

    def test_no_overlapping_code_spans(self) -> None:
        fenced = [
            span
            for span in extract_protected_spans('Text\n```json\n{"a":1}\n```\nmore')
            if span.kind == "code"
        ]
        self.assertEqual(len(fenced), 1)
        self.assertEqual(fenced[0].text, '```json\n{"a":1}\n```')

        doubled = [
            span for span in extract_protected_spans("a ``x`` b") if span.kind == "code"
        ]
        self.assertEqual(len(doubled), 1)
        self.assertEqual(doubled[0].text, "``x``")

    def test_nested_numbers_suppressed(self) -> None:
        spans = extract_protected_spans(
            "The total is $1,200 on 2026-08-10 at 3:30 for 99.9%."
        )
        self.assertEqual([span.text for span in spans if span.kind == "number"], [])
        self.assertIn("$1,200", [s.text for s in spans if s.kind == "currency"])
        self.assertIn("2026-08-10", [s.text for s in spans if s.kind == "date"])
        self.assertIn("3:30", [s.text for s in spans if s.kind == "time"])
        self.assertIn("99.9%", [s.text for s in spans if s.kind == "percentage"])


class IdentityTests(unittest.TestCase):
    def _span(self, source: str, text: str, kind: str = "number") -> dict:
        start = source.index(text)
        digest = compute_source_sha256(source)
        return {
            "id": "span",
            "kind": kind,
            "scope": "required",
            "text": text,
            "start": start,
            "end": start + len(text),
            "rangeEncoding": RANGE_ENCODING_VERSION,
            "sourceSha256": digest,
            "protectedSpanSha256": compute_protected_span_sha256(
                RANGE_ENCODING_VERSION, digest, start, start + len(text), text
            ),
        }

    def test_valid_span_identity_passes(self) -> None:
        source = "Keep 2026 exactly in place."
        span = self._span(source, "2026")
        result = evaluate_protected_content(
            source, "Keep 2026 exactly.", protected=[span]
        )
        self.assertTrue(result.safe)

    def test_span_from_wire_rejects_text_mismatch(self) -> None:
        source = "Keep 2026 exactly in place."
        start = source.index("2026")
        payload = {
            "id": "span",
            "text": "2027",
            "start": start,
            "end": start + 4,
            "rangeEncoding": RANGE_ENCODING_VERSION,
        }
        with self.assertRaises(ProtectedContentError) as ctx:
            span_from_wire(source, payload)
        self.assertEqual(ctx.exception.code, "span_text_mismatch")

    def test_span_from_wire_rejects_stale_digest(self) -> None:
        source = "Keep 2026 exactly in place."
        start = source.index("2026")
        payload = {
            "text": "2026",
            "start": start,
            "end": start + 4,
            "rangeEncoding": RANGE_ENCODING_VERSION,
            "protectedSpanSha256": "0" * 64,
        }
        with self.assertRaises(ProtectedContentError) as ctx:
            span_from_wire(source, payload)
        self.assertEqual(ctx.exception.code, "stale_span_identity")

    def test_span_from_wire_rejects_surrogate_split(self) -> None:
        source = "\U0001F600 99.9%"
        # Offset 1 addresses the low surrogate of the emoji, which is not a
        # legal UTF-16 boundary.
        payload = {"text": "99.9%", "start": 1, "end": 6}
        with self.assertRaises(ProtectedContentError) as ctx:
            span_from_wire(source, payload)
        self.assertEqual(ctx.exception.code, "invalid_span_range")

    def test_span_from_wire_accepts_non_bmp_prefix(self) -> None:
        source = "\U0001F600 99.9%"
        start = utf16_length(source[: source.index("99.9%")])
        span = span_from_wire(
            source, {"text": "99.9%", "start": start, "end": start + 5}
        )
        self.assertEqual(source[span.start : span.end], "99.9%")

    def test_span_from_wire_rejects_unsupported_encoding(self) -> None:
        source = "abc"
        payload = {"text": "abc", "start": 0, "end": 3, "rangeEncoding": "utf32-v9"}
        with self.assertRaises(ProtectedContentError) as ctx:
            span_from_wire(source, payload)
        self.assertEqual(ctx.exception.code, "unsupported_range_encoding")

    def test_selection_identity_binds_position_and_text(self) -> None:
        source = "Alpha 2026 beta."
        selection = (source.index("2026"), source.index("2026") + 4)
        digest = compute_selection_sha256(
            RANGE_ENCODING_VERSION,
            compute_source_sha256(source),
            selection[0],
            selection[1],
            source[selection[0] : selection[1]],
        )
        good = evaluate_protected_content(
            source,
            "Alpha 2026 beta.",
            protected=extract_protected_spans(source),
            route="local",
            selection=selection,
            selection_sha256=digest,
        )
        self.assertTrue(good.safe)
        stale = evaluate_protected_content(
            source,
            "Alpha 2026 beta.",
            protected=extract_protected_spans(source),
            route="local",
            selection=selection,
            selection_sha256="f" * 64,
        )
        self.assertEqual(stale.failure_class, "identity_mismatch")


class ScopeTests(unittest.TestCase):
    def test_context_only_value_not_required_inside_selection(self) -> None:
        source = "The budget is $20. Replace this word with a clearer phrase now."
        start = source.index("$20")
        span = {
            "id": "budget",
            "kind": "currency",
            "scope": "context-only",
            "text": "$20",
            "start": start,
            "end": start + 3,
        }
        candidate = "The budget is $20. Replace this word with a sharper phrase now."
        sel_start = source.index("Replace this word")
        result = evaluate_protected_content(
            source,
            candidate,
            protected=[span],
            route="local",
            selection=(sel_start, len(source)),
            candidate_range=(sel_start, len(candidate)),
        )
        self.assertTrue(result.safe)

    def test_context_only_value_injected_into_selection_is_introduced(self) -> None:
        source = "The budget is $20. Replace this word with a clearer phrase now."
        start = source.index("$20")
        span = {
            "id": "budget",
            "kind": "currency",
            "scope": "context-only",
            "text": "$20",
            "start": start,
            "end": start + 3,
        }
        candidate = "Replace this word with a clearer phrase for $20 now."
        sel_start = source.index("Replace this word")
        result = evaluate_protected_content(
            source,
            candidate,
            protected=[span],
            route="local",
            selection=(sel_start, len(source)),
            candidate_range=(0, len(candidate)),
        )
        self.assertFalse(result.safe)
        self.assertEqual(result.failure_class, "protected_introduced")
        self.assertIn("budget", result.introduced_span_ids)


class NormalizationTests(unittest.TestCase):
    def test_normalize_accepts_strings_dicts_and_dataclasses(self) -> None:
        spans = normalize_protected_spans(
            [
                "$20",
                {"text": "99.9%", "kind": "percentage", "scope": "required", "id": "pct"},
                extract_protected_spans("Call `build_plan()` now.")[0],
            ]
        )
        self.assertEqual(len(spans), 3)
        self.assertEqual(spans[0].text, "$20")
        self.assertEqual(spans[1].kind, "percentage")
        self.assertEqual(spans[2].kind, "code")
        self.assertTrue(all(span.id for span in spans))

    def test_protected_spans_for_evaluation_shape(self) -> None:
        source = "Pay $20 by 99.9% today."
        payload = protected_spans_for_evaluation(source, "Pay $20 by 99.9% today.")
        self.assertTrue(payload)
        for entry in payload:
            for key in ("id", "kind", "scope", "text", "start", "end"):
                self.assertIn(key, entry)


class DetectionRegressionTests(unittest.TestCase):
    def test_issue_51_examples_rejected(self) -> None:
        cases = [
            ("Pay $50 now.", "Pay $500 now.", "protected_altered"),
            ("Year 2026 here.", "Year 120260 here.", "protected_altered"),
            ("Open report.txt now.", "Open report.txt.bak now.", "protected_altered"),
            ("Keep the SLA at 99.9%.", "Keep the SLA at 99.91%.", "protected_altered"),
            ("Open https://x.dev/a?q=1.", "Open https://x.dev/a?q=2.", "protected_altered"),
            ("You may go.", "You must go.", "protected_altered"),
            ("You may not go.", "You may go.", "protected_missing"),
            ("You may not go.", "You may not not go.", "protected_introduced"),
        ]
        for source, candidate, expected in cases:
            with self.subTest(source=source, candidate=candidate):
                spans = extract_protected_spans(source)
                result = evaluate_protected_content(
                    source, candidate, protected=spans, anchor_policy="exact"
                )
                self.assertFalse(result.safe)
                self.assertEqual(result.failure_class, expected)

    def test_exact_occurrences_rejects_extended_tokens(self) -> None:
        self.assertEqual(exact_occurrences("Pay $500 now.", "$50"), ())
        self.assertEqual(exact_occurrences("Year 120260 here.", "2026"), ())
        self.assertEqual(exact_occurrences("Samuel spoke.", "Sam"), ())
        self.assertEqual(exact_occurrences("Open report.txt.bak now.", "report.txt"), ())
        self.assertEqual(exact_occurrences("Open report.txt now.", "report.txt"), (5,))
        self.assertEqual(exact_occurrences("value: xabc", "abc"), ())
        self.assertEqual(exact_occurrences("value: abcx", "abc"), ())


if __name__ == "__main__":
    unittest.main(verbosity=2)
