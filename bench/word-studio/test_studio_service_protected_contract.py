#!/usr/bin/env python3
"""Cross-surface checks for the frozen #51 protected-content contract.

The corpus is the same language-neutral fixture the Mac app and the shared
Python contract consume (``tests/fixtures/protected-content-contract-v1.json``).
These tests drive it through the two surfaces this backend owns:

- ``studio_backend.service_limits.studio_request_from_wire`` parses every corpus
  span (``id``/``kind``/``scope`` plus UTF-16 positions) into
  ``contracts.ProtectedSpan`` and re-encodes it byte-stably;
- ``studio_backend.safety.protected_diagnostics`` returns the #51 verdict for the
  cases whose route the Studio service can express, keeping the published
  diagnostics shape.

CPU-only; no model, no network, no cloud.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from studio_backend.contracts import (  # noqa: E402
    Operation,
    ProtectedSpan,
    StudioRequest,
    TextRange,
    to_wire_request,
)
from studio_backend.range_encoding import (  # noqa: E402
    RANGE_ENCODING_VERSION,
    REQUEST_CONTRACT_VERSION,
    protected_span_identity_sha256,
    selection_identity_sha256,
    source_identity_sha256,
)
from studio_backend.safety import protected_diagnostics  # noqa: E402
from studio_backend.service_limits import ServiceLimits, studio_request_from_wire  # noqa: E402
from word_studio_output_parser import protected_evaluation as benchmark_protected_evaluation  # noqa: E402


FIXTURE = HERE.parents[1] / "app" / "tests" / "fixtures" / "protected-content-contract-v1.json"


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


def wire_body_for_case(case: dict) -> dict:
    """Build a ``pari-studio-request-v2`` body whose spans are the corpus spans."""
    source = case["sourceText"]
    source_sha256 = source_identity_sha256(source)
    spans = []
    for span in case["protectedSpans"]:
        row = dict(span)
        row["rangeEncoding"] = RANGE_ENCODING_VERSION
        row["protectedSpanSha256"] = protected_span_identity_sha256(
            source_sha256=source_sha256,
            range_encoding=RANGE_ENCODING_VERSION,
            wire_start=row["start"],
            wire_end=row["end"],
            span_text=row["text"],
        )
        spans.append(row)
    selection = case["selection"]
    selected = source[
        utf16_to_index(source, selection["start"]) : utf16_to_index(source, selection["end"])
    ]
    return {
        "contractVersion": REQUEST_CONTRACT_VERSION,
        "rangeEncoding": RANGE_ENCODING_VERSION,
        "requestId": f"corpus-{case['id']}",
        "sourceIdentity": {
            "contractVersion": REQUEST_CONTRACT_VERSION,
            "rangeEncoding": RANGE_ENCODING_VERSION,
            "documentSha256": source_sha256,
            "documentRevision": None,
        },
        "documentText": source,
        "selection": {"start": selection["start"], "end": selection["end"]},
        "selectedText": selected,
        "selectionSha256": selection_identity_sha256(
            source_sha256=source_sha256,
            range_encoding=RANGE_ENCODING_VERSION,
            wire_start=selection["start"],
            wire_end=selection["end"],
            selected_text=selected,
        ),
        "operation": "replace",
        "requestedCandidates": 10,
        "protectedSpans": spans,
    }


class CorpusSpanParsingTests(unittest.TestCase):
    """Every corpus span must survive the backend wire boundary unchanged."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.limits = ServiceLimits()

    def test_fixture_is_present_and_versioned(self) -> None:
        self.assertEqual(self.fixture["rangeEncoding"], RANGE_ENCODING_VERSION)

    def test_every_corpus_span_parses_and_reencodes(self) -> None:
        for case in self.fixture["cases"]:
            if not case.get("selection"):
                continue
            with self.subTest(case["id"]):
                body = wire_body_for_case(case)
                parsed = studio_request_from_wire(body, self.limits)
                spans = parsed.request.protected_spans
                self.assertEqual(len(spans), len(case["protectedSpans"]))
                for span, expected in zip(spans, case["protectedSpans"]):
                    self.assertEqual(span.text, expected["text"])
                    self.assertEqual(span.kind, expected["kind"])
                    self.assertEqual(span.scope, expected["scope"])
                    start = utf16_to_index(case["sourceText"], expected["start"])
                    end = utf16_to_index(case["sourceText"], expected["end"])
                    self.assertEqual((span.start, span.end), (start, end))
                # Re-encoding the parsed request reproduces the corpus digest,
                # proving the UTF-16 wire identity survives the round trip.
                reencoded = to_wire_request(parsed.request)["protectedSpans"]
                sent = body["protectedSpans"]
                for row, expected_row, sent_row in zip(
                    reencoded, case["protectedSpans"], sent
                ):
                    self.assertEqual(
                        row["protectedSpanSha256"], sent_row["protectedSpanSha256"]
                    )
                    self.assertEqual(row["scope"], expected_row["scope"])
                    self.assertEqual(row["kind"], expected_row["kind"])

    def test_context_only_scope_is_preserved(self) -> None:
        case = next(
            item
            for item in self.fixture["cases"]
            if item["id"] == "context-only-value-not-required-in-selection"
        )
        parsed = studio_request_from_wire(wire_body_for_case(case), self.limits)
        span = parsed.request.protected_spans[0]
        self.assertEqual(span.scope, "context-only")
        self.assertFalse(span.is_required)


class CorpusGateTests(unittest.TestCase):
    """The safety gate must reproduce the #51 verdict for the local cases the
    Studio service can express (a selection replacement)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    @staticmethod
    def _request(case: dict) -> StudioRequest:
        source = case["sourceText"]
        start = utf16_to_index(source, case["selection"]["start"])
        end = utf16_to_index(source, case["selection"]["end"])
        spans = tuple(
            ProtectedSpan(
                span["text"],
                utf16_to_index(source, span["start"]),
                utf16_to_index(source, span["end"]),
                id=span["id"],
                kind=span["kind"],
                scope=span["scope"],
            )
            for span in case["protectedSpans"]
        )
        return StudioRequest(
            document_text=source,
            selection=TextRange(start, end),
            operation=Operation.REPLACE,
            protected_spans=spans,
        )

    @staticmethod
    def _region_kwargs(case: dict) -> dict:
        if "candidateRange" not in case:
            return {}
        rng = case["candidateRange"]
        return {
            "candidate_document": case["candidateText"],
            "candidate_range": (
                utf16_to_index(case["candidateText"], rng["start"]),
                utf16_to_index(case["candidateText"], rng["end"]),
            ),
        }

    def test_local_cases_reproduce_expected_verdict(self) -> None:
        for case in self.fixture["cases"]:
            if case["route"] != "local":
                continue
            with self.subTest(case["id"]):
                diagnostics = protected_diagnostics(
                    self._request(case),
                    case["candidateRegionText"],
                    **self._region_kwargs(case),
                )
                expect = case["expect"]
                self.assertEqual(
                    diagnostics["corrupted"], not expect["safe"], diagnostics["failureClass"]
                )
                if not expect["safe"]:
                    self.assertEqual(diagnostics["failureClass"], expect["failureClass"])

    def test_position_drift_reports_the_corpus_span_id(self) -> None:
        case = next(
            item
            for item in self.fixture["cases"]
            if item["id"] == "duplicate-identical-numbers-local-wrong-occurrence"
        )
        diagnostics = protected_diagnostics(
            self._request(case), case["candidateRegionText"], **self._region_kwargs(case)
        )
        self.assertTrue(diagnostics["corrupted"])
        self.assertEqual(diagnostics["failureClass"], "protected_position_drift")
        self.assertIn("selected-2026", diagnostics["positionDriftSpanIds"])

    def test_published_diagnostics_shape_is_preserved(self) -> None:
        case = next(
            item
            for item in self.fixture["cases"]
            if item["id"] == "filename-suffix-change"
        )
        request = StudioRequest(
            document_text=case["sourceText"],
            selection=TextRange(0, len(case["sourceText"])),
            operation=Operation.REPLACE,
        )
        diagnostics = protected_diagnostics(request, case["candidateText"])
        for key in (
            "protectedCount",
            "missing",
            "altered",
            "repeatedMismatch",
            "positionDrift",
            "corrupted",
        ):
            self.assertIn(key, diagnostics)
        self.assertIsInstance(diagnostics["corrupted"], bool)

    def test_benchmark_and_production_agree_on_corruption_classes(self) -> None:
        """#51: benchmark parser and Studio service publish one verdict.

        ``word_studio_output_parser.protected_evaluation`` is the benchmark
        surface and ``safety.protected_diagnostics`` is the production surface.
        Both project the shared #51 contract onto the same five corruption
        buckets (missing / altered / repeatedMismatch / positionDrift), so a
        case that corrupts protected content one way must not be reported as a
        different kind of corruption by the other. The Studio service can only
        express a ``local`` selection replacement, so this compares the two
        surfaces on the corpus cases whose route the service actually runs
        (route ``local``); the whole-document ``whole`` route is benchmark-only.
        The parser is another owner's file, so it is driven read-only and the
        assertion is agreement, not a restatement of its implementation.
        """
        local_cases = [c for c in self.fixture["cases"] if c["route"] == "local"]
        self.assertTrue(local_cases, "corpus has no local-route cases")
        for case in local_cases:
            with self.subTest(case["id"]):
                source = case["sourceText"]
                spans = [
                    dict(span, rangeEncoding=RANGE_ENCODING_VERSION)
                    for span in case["protectedSpans"]
                ]
                sel = case["selection"]
                rng = case["candidateRange"]
                benchmark = benchmark_protected_evaluation(
                    case["candidateText"],
                    source=source,
                    protected=spans,
                    protected_route="local",
                    selection=(
                        utf16_to_index(source, sel["start"]),
                        utf16_to_index(source, sel["end"]),
                    ),
                    candidate_range=(
                        utf16_to_index(case["candidateText"], rng["start"]),
                        utf16_to_index(case["candidateText"], rng["end"]),
                    ),
                )
                service = protected_diagnostics(
                    self._request(case),
                    case["candidateRegionText"],
                    **self._region_kwargs(case),
                )
                self.assertEqual(
                    benchmark["corrupted"],
                    service["corrupted"],
                    "benchmark vs service corrupted flag",
                )
                for field in ("missing", "altered", "repeatedMismatch", "positionDrift"):
                    self.assertEqual(
                        sorted(benchmark[field]),
                        sorted(service[field]),
                        f"benchmark vs service {field}",
                    )

    def test_benchmark_publishes_the_shared_contract_buckets_for_every_case(self) -> None:
        """#51: the benchmark surface must not invent its own corruption classes.

        For the whole corpus (both routes) the benchmark parser is handed the
        same shared verdict and must project exactly the contract's five
        buckets. This pins the benchmark-to-contract edge from this backend's
        own test file, independent of the parser's own suite.
        """
        bucket_by_failure = {
            "protected_missing": "missing",
            "protected_altered": "altered",
            "protected_repeated_mismatch": "repeatedMismatch",
            "protected_position_drift": "positionDrift",
        }
        for case in self.fixture["cases"]:
            with self.subTest(case["id"]):
                source = case["sourceText"]
                spans = [
                    dict(span, rangeEncoding=RANGE_ENCODING_VERSION)
                    for span in case["protectedSpans"]
                ]
                kwargs: dict = {"protected": spans, "protected_route": case["route"]}
                if "selection" in case:
                    sel = case["selection"]
                    kwargs["selection"] = (
                        utf16_to_index(source, sel["start"]),
                        utf16_to_index(source, sel["end"]),
                    )
                if "candidateRange" in case:
                    rng = case["candidateRange"]
                    kwargs["candidate_range"] = (
                        utf16_to_index(case["candidateText"], rng["start"]),
                        utf16_to_index(case["candidateText"], rng["end"]),
                    )
                benchmark = benchmark_protected_evaluation(
                    case["candidateText"], source=source, **kwargs
                )
                self.assertEqual(
                    set(benchmark),
                    {
                        "protectedCount",
                        "missing",
                        "altered",
                        "repeatedMismatch",
                        "positionDrift",
                        "corrupted",
                    },
                    "benchmark publishes exactly the five corruption buckets",
                )
                expect = case["expect"]
                self.assertEqual(benchmark["corrupted"], not expect["safe"])
                list_key = bucket_by_failure.get(expect.get("failureClass"))
                if list_key is not None and "spanIds" in expect:
                    text_by_id = {str(s["id"]): str(s["text"]) for s in case["protectedSpans"]}
                    expected_texts = sorted({text_by_id[str(i)] for i in expect["spanIds"]})
                    self.assertEqual(sorted(benchmark[list_key]), expected_texts)
                else:
                    for field in ("missing", "altered", "repeatedMismatch", "positionDrift"):
                        self.assertFalse(benchmark[field], field)

if __name__ == "__main__":
    unittest.main(verbosity=2)
