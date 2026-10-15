#!/usr/bin/env python3
"""Focused CPU contract tests for the #50 Unicode range/identity helpers.

These tests exercise ``studio_backend.range_encoding`` only: UTF-16 code-unit
conversion, exact (non-normalized) substring reproduction, and the canonical
source/selection/protected-span identity digests. They do not load the model
runtime, the FastAPI app, or any network/Kaggle resource.

The expected digests and coordinates come from the language-neutral fixture
``tests/fixtures/studio-unicode-ranges-v1.json`` so the macOS/TypeScript
client can assert the same vectors.
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
FIXTURE = REPO_ROOT / "app" / "tests" / "fixtures" / "studio-unicode-ranges-v1.json"
sys.path.insert(0, str(HERE.parent))

from studio_backend.errors import ServiceRequestError  # noqa: E402
from studio_backend.range_encoding import (  # noqa: E402
    RANGE_ENCODING_VERSION,
    REQUEST_CONTRACT_VERSION,
    code_point_to_utf16,
    exact_slice_from_utf16,
    parse_source_identity,
    protected_span_identity_sha256,
    require_sha256_hex,
    require_supported_range_encoding,
    require_wire_offset,
    selection_identity_sha256,
    source_identity_sha256,
    sha256_text,
    utf16_length,
    utf16_offset_to_index,
    utf16_range_to_slice,
)


def load_fixture() -> dict:
    with FIXTURE.open("r", encoding="utf-8") as handle:
        return json.load(handle)


FIXTURE_DATA = load_fixture()


def independent_source_sha256(text: str) -> str:
    """Recompute a source digest with raw hashlib, bypassing the module."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def independent_selection_sha256(
    source_sha256: str, wire_start: int, wire_end: int, selected_text: str
) -> str:
    preimage = "\u001f".join(
        ["utf16-v1", source_sha256, str(wire_start), str(wire_end), selected_text]
    )
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


def fixture_document(case: dict) -> str:
    """Return the exact source text a fixture case describes.

    A case whose ``documentText`` is null carries an unpaired UTF-16 surrogate,
    which cannot be written as a JSON string literal that strict readers accept
    (Swift's ``JSONSerialization`` refuses the whole document). Those cases
    spell the surrogate out in ``documentTextUnpairedSurrogate`` instead, so
    every language can reconstruct the same string and assert the same
    rejection.
    """
    document = case.get("documentText")
    if document is not None:
        return document
    escape_notation = case["documentTextUnpairedSurrogate"]
    decoded: list[str] = []
    index = 0
    while index < len(escape_notation):
        character = escape_notation[index]
        if character == "\\" and escape_notation[index : index + 2] == "\\u":
            decoded.append(chr(int(escape_notation[index + 2 : index + 6], 16)))
            index += 6
            continue
        decoded.append(character)
        index += 1
    return "".join(decoded)


class TestRangeEncodingConstants(unittest.TestCase):
    def test_contract_and_encoding_are_versioned(self):
        self.assertEqual(REQUEST_CONTRACT_VERSION, "pari-studio-request-v2")
        self.assertEqual(RANGE_ENCODING_VERSION, "utf16-v1")
        self.assertEqual(FIXTURE_DATA["contractVersion"], REQUEST_CONTRACT_VERSION)
        self.assertEqual(FIXTURE_DATA["rangeEncoding"], RANGE_ENCODING_VERSION)

    def test_unsupported_range_encoding_is_rejected(self):
        with self.assertRaises(ServiceRequestError):
            require_supported_range_encoding("python-codepoint-v1")
        with self.assertRaises(ServiceRequestError):
            require_supported_range_encoding(None)


class TestUnicodeFixtureRoundTrips(unittest.TestCase):
    def test_fixture_covers_the_required_unicode_matrix(self):
        ids = {case["id"] for case in FIXTURE_DATA["cases"]}
        required = {
            "ascii",
            "curly_quotes",
            "precomposed_accent",
            "combining_accent",
            "non_bmp_emoji",
            "emoji_skin_tone",
            "zwj_family",
            "regional_indicators",
            "variation_selector",
            "cjk",
            "crlf",
            "repeated_values",
        }
        self.assertTrue(required.issubset(ids), sorted(required - ids))

    def test_every_valid_case_round_trips_exactly(self):
        for case in FIXTURE_DATA["cases"]:
            with self.subTest(case=case["id"]):
                doc = case["documentText"]
                start = case["selection"]["start"]
                end = case["selection"]["end"]
                cp_start, cp_end = utf16_range_to_slice(doc, start, end, field="selection")
                # The exact declared text is reproduced byte-for-byte.
                self.assertEqual(doc[cp_start:cp_end], case["selectedText"])
                self.assertEqual(
                    exact_slice_from_utf16(doc, start, end, field="selection"),
                    case["selectedText"],
                )
                # Code-point and UTF-16 offsets are inverses of each other.
                self.assertEqual(code_point_to_utf16(doc, cp_start), start)
                self.assertEqual(code_point_to_utf16(doc, cp_end), end)
                # Source identity hashes the exact UTF-8 bytes.
                self.assertEqual(source_identity_sha256(doc), case["documentSha256"])
                self.assertEqual(sha256_text(doc), case["documentSha256"])
                # Cross-check against a raw hashlib recomputation so a fixture
                # regenerated from the module cannot silently redefine truth.
                self.assertEqual(independent_source_sha256(doc), case["documentSha256"])
                # Selection identity binds document + encoding + offsets + text.
                self.assertEqual(
                    selection_identity_sha256(
                        source_sha256=case["documentSha256"],
                        range_encoding=RANGE_ENCODING_VERSION,
                        wire_start=start,
                        wire_end=end,
                        selected_text=case["selectedText"],
                    ),
                    case["selectionSha256"],
                )
                self.assertEqual(
                    independent_selection_sha256(
                        case["documentSha256"], start, end, case["selectedText"]
                    ),
                    case["selectionSha256"],
                )
                # Protected spans share the same encoding and identity scheme.
                for span in case.get("protectedSpans", []):
                    span_cp_start, span_cp_end = utf16_range_to_slice(
                        doc, span["start"], span["end"], field="protectedSpans.range"
                    )
                    self.assertEqual(doc[span_cp_start:span_cp_end], span["text"])
                    self.assertEqual(
                        protected_span_identity_sha256(
                            source_sha256=case["documentSha256"],
                            range_encoding=RANGE_ENCODING_VERSION,
                            wire_start=span["start"],
                            wire_end=span["end"],
                            span_text=span["text"],
                        ),
                        span["protectedSpanSha256"],
                    )

    def test_code_point_and_utf16_offsets_diverge_but_contract_selects_intended_text(self):
        case = next(c for c in FIXTURE_DATA["cases"] if c["id"] == "non_bmp_emoji")
        doc = case["documentText"]
        divergence = case["codePointDivergence"]
        utf16_start = case["selection"]["start"]
        cp_start = divergence["codePointStart"]

        # Premise: the two units disagree before the selection.
        self.assertNotEqual(cp_start, utf16_start)
        # Treating the UTF-16 offset as a code-point offset picks the wrong text.
        self.assertNotEqual(
            doc[utf16_start : utf16_start + len(case["selectedText"])],
            case["selectedText"],
        )
        # The correct UTF-16 offset selects the intended substring.
        cp_a, cp_b = utf16_range_to_slice(
            doc, case["selection"]["start"], case["selection"]["end"], field="selection"
        )
        self.assertEqual(doc[cp_a:cp_b], case["selectedText"])
        # The stale code-point range cannot reproduce the declared text, so it
        # must not silently validate.
        stale_cp_a, stale_cp_b = utf16_range_to_slice(
            doc, divergence["codePointStart"], divergence["codePointEnd"], field="selection"
        )
        self.assertNotEqual(doc[stale_cp_a:stale_cp_b], case["selectedText"])

    def test_no_unicode_normalization_is_applied(self):
        precomposed = next(c for c in FIXTURE_DATA["cases"] if c["id"] == "precomposed_accent")
        combining = next(c for c in FIXTURE_DATA["cases"] if c["id"] == "combining_accent")
        # NFC vs NFD spellings of the same visible text hash differently.
        self.assertNotEqual(precomposed["documentSha256"], combining["documentSha256"])
        self.assertNotEqual(precomposed["selectionSha256"], combining["selectionSha256"])

    def test_repeated_identical_spans_differ_by_position(self):
        case = next(c for c in FIXTURE_DATA["cases"] if c["id"] == "repeated_values")
        by_text: dict[str, set[str]] = {}
        for span in case["protectedSpans"]:
            by_text.setdefault(span["text"], set()).add(span["protectedSpanSha256"])
        # "Ada" appears twice at different offsets -> two distinct digests.
        self.assertEqual(len(by_text["Ada"]), 2)


class TestInvalidFixtureCasesFailClosed(unittest.TestCase):
    def _selection_case_raises(self, case):
        doc = fixture_document(case)
        with self.assertRaises(ServiceRequestError):
            utf16_range_to_slice(
                doc, case["selection"]["start"], case["selection"]["end"], field="selection"
            )

    def test_surrogate_interior_offsets_are_rejected(self):
        for case in FIXTURE_DATA["invalidCases"]:
            if case["reason"] != "surrogateInterior":
                continue
            with self.subTest(case=case["id"]):
                self._selection_case_raises(case)

    def test_out_of_bounds_negative_empty_reversed_are_rejected(self):
        reasons = {"outOfBounds", "negative", "emptyRange", "reversedRange"}
        for case in FIXTURE_DATA["invalidCases"]:
            if case["reason"] not in reasons:
                continue
            with self.subTest(case=case["id"]):
                self._selection_case_raises(case)

    def test_non_integer_offsets_are_rejected_not_coerced(self):
        for case in FIXTURE_DATA["invalidCases"]:
            if case["reason"] != "notAnInteger":
                continue
            with self.subTest(case=case["id"]):
                self._selection_case_raises(case)

    def test_mixed_type_offsets_fail_closed_without_type_error(self):
        doc = "Ship \U0001F600 the release."
        for start, end in (("8", 9), (8, "19"), (None, 9), ([8], 9), (8, {})):
            with self.subTest(start=start, end=end):
                with self.assertRaises(ServiceRequestError):
                    utf16_range_to_slice(doc, start, end, field="selection")

    def test_lone_surrogate_document_is_rejected_before_range_work(self):
        case = next(
            c for c in FIXTURE_DATA["invalidCases"] if c["reason"] == "loneSurrogateDocument"
        )
        # The fixture spells the unpaired surrogate out in escape notation so a
        # strict JSON reader on another language can still load the document;
        # the reconstructed string must be the one the contract rejects.
        self.assertIsNone(case["documentText"])
        document = fixture_document(case)
        self.assertEqual(len(document), 3)
        self.assertEqual(ord(document[1]), 0xD83D)
        with self.assertRaises(ServiceRequestError):
            source_identity_sha256(document)
        with self.assertRaises(ServiceRequestError):
            utf16_length(document)

    def test_codepoint_offset_misuse_cannot_reproduce_declared_text(self):
        case = next(
            c for c in FIXTURE_DATA["invalidCases"] if c["reason"] == "selectedTextMismatch"
        )
        doc = fixture_document(case)
        # The stale range is structurally valid UTF-16 but points at the wrong
        # substring; the exact selected-text cross-check is what rejects it.
        cp_a, cp_b = utf16_range_to_slice(
            doc, case["selection"]["start"], case["selection"]["end"], field="selection"
        )
        self.assertNotEqual(doc[cp_a:cp_b], case["selectedText"])

    def test_protected_span_position_mismatch_is_detectable(self):
        case = next(
            c
            for c in FIXTURE_DATA["invalidCases"]
            if c["reason"] == "protectedSpanTextMismatch"
        )
        doc = fixture_document(case)
        span = case["protectedSpans"][0]
        cp_a, cp_b = utf16_range_to_slice(
            doc, span["start"], span["end"], field="protectedSpans.range"
        )
        self.assertNotEqual(doc[cp_a:cp_b], span["text"])


class TestIdentityValidators(unittest.TestCase):
    def test_require_sha256_hex_accepts_only_lowercase_digest(self):
        self.assertEqual(require_sha256_hex("a" * 64, field="sourceIdentity.documentSha256"), "a" * 64)
        with self.assertRaises(ServiceRequestError):
            require_sha256_hex("A" * 64, field="sourceIdentity.documentSha256")
        with self.assertRaises(ServiceRequestError):
            require_sha256_hex("a" * 63, field="sourceIdentity.documentSha256")
        with self.assertRaises(ServiceRequestError):
            require_sha256_hex(None, field="sourceIdentity.documentSha256")

    def test_require_wire_offset_rejects_bools_and_non_ints(self):
        self.assertEqual(require_wire_offset(0, field="selection.start"), 0)
        for bad in (True, 1.0, "1", -1, None):
            with self.assertRaises(ServiceRequestError):
                require_wire_offset(bad, field="selection.start")

    def test_parse_source_identity_reads_nested_digest_and_revision(self):
        body = {
            "sourceIdentity": {
                "documentSha256": "b" * 64,
                "documentRevision": "doc-1",
            }
        }
        digest, revision = parse_source_identity(body)
        self.assertEqual(digest, "b" * 64)
        self.assertEqual(revision, "doc-1")

    def test_parse_source_identity_rejects_missing_or_malformed(self):
        with self.assertRaises(ServiceRequestError):
            parse_source_identity({})
        with self.assertRaises(ServiceRequestError):
            parse_source_identity({"sourceIdentity": {"documentSha256": "short"}})
        with self.assertRaises(ServiceRequestError):
            parse_source_identity({"sourceIdentity": "not-a-mapping"})


if __name__ == "__main__":
    unittest.main()
