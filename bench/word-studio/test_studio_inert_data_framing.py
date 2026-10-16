#!/usr/bin/env python3
"""CPU-only contract tests for the versioned inert-data prompt frame.

These assert the *framing module's* contract only: canonical form, closed key
set, validation, sealing and round-trip. They deliberately build payloads
locally instead of importing ``studio_backend.prompting``, so the module can be
verified on its own terms. The service-side wiring (which fields the production
payload sets, and how control text describes them) is asserted by
``test_studio_prompting_boundary.py``, which owns that surface.

Every case lives on a ``unittest.TestCase`` so ``python3 -m unittest``, pytest,
and a bare ``python3`` invocation all execute the same bodies. A module of bare
``test_*`` functions is invisible to unittest discovery, which would report a
green zero-test run instead of the real result.
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from studio_backend.inert_data_framing import (  # noqa: E402
    FRAMING_CONTRACT_VERSION,
    FRAMING_PREFIX,
    FramingError,
    compute_control_sha256,
    decode_inert_data,
    encode_inert_data,
)


FIXTURE_PATH = HERE / "studio_backend" / "fixtures" / "inert_data_framing_cases.json"
SCHEMA_PATH = HERE / "studio_backend" / "inert_data_framing.schema.json"
FIXTURES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _payload(
    *,
    document: str,
    selected: str,
    start: int | None = None,
    context: tuple[int, int] | None = None,
    protected: list[dict] | None = None,
    context_protected: list[dict] | None = None,
    strength: int = 37,
    candidate_budget: int = 10,
) -> dict:
    """Build one valid, unsealed v1 payload for the framing contract."""
    if start is None:
        start = document.index(selected)
    context_start, context_end = context or (0, len(document))
    return {
        "contract": FRAMING_CONTRACT_VERSION,
        "operation": {
            "id": "replace",
            "instruction": "Replace only the selected text with context-valid equivalents.",
            "semanticMode": "full_preservation",
            "semanticRule": "Preserve actor roles, polarity, negation and modality.",
            "strength": strength,
            "controlNote": "Strength controls distance, not intensity.",
        },
        "source": {
            "documentText": document,
            "documentContext": document[context_start:context_end],
            "selectedText": selected,
            "selection": {"start": start, "end": start + len(selected)},
            "contextRange": {"start": context_start, "end": context_end},
            "sourceSha256": hashlib.sha256(document.encode("utf-8")).hexdigest(),
            "selectionSha256": hashlib.sha256(selected.encode("utf-8")).hexdigest(),
        },
        "protectedSpans": list(protected or []),
        "contextProtectedValues": list(context_protected or []),
        "lane": {
            "id": "fast",
            "requestedFamilies": ["contextual_equivalent"],
            "candidateBudget": candidate_budget,
            "maxNewTokens": 420,
            "temperature": 0.35,
            "topP": 0.9,
        },
        "targetWords": {"minWords": None, "maxWords": None},
        "outputContract": {
            "format": "json_object",
            "field": "options",
            "count": candidate_budget,
            "schema": {"options": ["distinct alternative"]},
            "instruction": (
                f"Return exactly {candidate_budget} distinct alternatives as JSON only. "
                'Use {"options":["...", "..."]}.'
            ),
        },
    }


def _spans(document: str, texts: list[str]) -> list[dict]:
    """Turn fixture protected texts into wire spans bound to the document."""
    spans = []
    for text in texts:
        offset = document.find(text)
        spans.append(
            {"text": text, "start": None if offset < 0 else offset, "end": None if offset < 0 else offset + len(text)}
        )
    return spans


class InertDataFramingContractTests(unittest.TestCase):
    """Framing-module contract: canonical form, closed keys, sealing, round-trip."""

    def test_schema_and_fixture_pin_the_same_contract(self) -> None:
        self.assertEqual(FIXTURES["contract"], FRAMING_CONTRACT_VERSION)
        self.assertEqual(SCHEMA["properties"]["contract"]["const"], FRAMING_CONTRACT_VERSION)
        self.assertEqual(
            set(SCHEMA["required"]),
            {
                "contract",
                "operation",
                "source",
                "protectedSpans",
                "contextProtectedValues",
                "lane",
                "targetWords",
                "outputContract",
                "controlSha256",
            },
        )

    def test_schema_object_shapes_match_the_validator(self) -> None:
        """The published JSON Schema must describe the shape the code enforces.

        The framing module is the enforcement point, but the schema is the
        artifact other implementations read. If a nested object stops being
        closed, or a numeric bound drifts, the contract would silently diverge
        between validators, so pin every closed-object and bound here.
        """
        self.assertIs(SCHEMA["additionalProperties"], False)
        for name in ("operation", "source", "lane", "targetWords", "outputContract"):
            self.assertIs(SCHEMA["properties"][name]["additionalProperties"], False, name)
        # Both protected arrays are the same closed span shape, not one loose form.
        for name in ("protectedSpans", "contextProtectedValues"):
            item = SCHEMA["properties"][name]["items"]
            self.assertIs(item["additionalProperties"], False, name)
            self.assertEqual(set(item["required"]), {"text", "start", "end"}, name)
        # Control-field bounds the validator also enforces.
        self.assertEqual(
            SCHEMA["properties"]["operation"]["properties"]["strength"],
            {"type": "integer", "minimum": 0, "maximum": 100},
        )
        self.assertEqual(
            SCHEMA["properties"]["lane"]["properties"]["candidateBudget"],
            {"type": "integer", "minimum": 1, "maximum": 40},
        )
        self.assertEqual(
            SCHEMA["properties"]["lane"]["properties"]["temperature"],
            {"type": "number", "minimum": 0, "maximum": 2},
        )
        self.assertEqual(
            SCHEMA["properties"]["lane"]["properties"]["topP"],
            {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
        )
        self.assertEqual(
            SCHEMA["properties"]["outputContract"]["properties"]["format"],
            {"const": "json_object"},
        )
        # The validator's closed range/selection key sets and lower bounds.
        source_props = SCHEMA["properties"]["source"]["properties"]
        self.assertEqual(set(source_props["selection"]["required"]), {"start", "end"})
        self.assertEqual(set(source_props["contextRange"]["required"]), {"start", "end"})
        self.assertEqual(source_props["selection"]["properties"]["end"]["minimum"], 1)
        self.assertEqual(source_props["contextRange"]["properties"]["end"]["minimum"], 0)
        self.assertEqual(SCHEMA["$defs"]["sha256"]["pattern"], "^[0-9a-f]{64}$")

    def test_adversarial_fixtures_round_trip_exact_unicode_and_protected_data(self) -> None:
        for case in FIXTURES["cases"]:
            with self.subTest(case["id"]):
                payload = _payload(
                    document=case["documentText"],
                    selected=case["selectedText"],
                    protected=_spans(case["documentText"], case.get("protectedTexts", [])),
                )
                encoded = encode_inert_data(payload)
                decoded = decode_inert_data(encoded.text)

                self.assertEqual(decoded.payload["source"]["documentText"], case["documentText"])
                self.assertEqual(decoded.payload["source"]["selectedText"], case["selectedText"])
                selection = decoded.payload["source"]["selection"]
                self.assertEqual(
                    case["documentText"][selection["start"] : selection["end"]],
                    case["selectedText"],
                )
                recovered = {span["text"] for span in decoded.payload["protectedSpans"]}
                self.assertLessEqual(set(case.get("protectedTexts", [])), recovered)
                self.assertTrue(encoded.text.startswith(FRAMING_PREFIX))
                self.assertEqual(encoded.text.count(FRAMING_PREFIX), 1)
                self.assertEqual(encoded.payload_sha256, decoded.payload_sha256)

    def test_control_fields_are_authoritative_and_sealed(self) -> None:
        case = FIXTURES["cases"][0]
        payload = _payload(
            document=case["documentText"],
            selected=case["selectedText"],
            protected=_spans(case["documentText"], case.get("protectedTexts", [])),
        )
        original_control_sha = encode_inert_data(payload).control_sha256
        self.assertEqual(original_control_sha, compute_control_sha256(payload))

        changed_source = deepcopy(payload)
        # Insert before the selection instead of inside it, so every range invariant
        # still holds: the same selected/context substrings stay bound to their
        # ranges, only the document bytes and their offsets move.
        changed_source["source"]["documentText"] = " " + changed_source["source"]["documentText"]
        changed_source["source"]["selection"]["start"] += 1
        changed_source["source"]["selection"]["end"] += 1
        changed_source["source"]["contextRange"]["start"] += 1
        changed_source["source"]["contextRange"]["end"] += 1
        for span in changed_source["protectedSpans"]:
            if span["start"] is not None:
                span["start"] += 1
            if span["end"] is not None:
                span["end"] += 1
        changed_source["source"]["sourceSha256"] = hashlib.sha256(
            changed_source["source"]["documentText"].encode("utf-8")
        ).hexdigest()
        changed = encode_inert_data(changed_source)
        self.assertEqual(changed.control_sha256, original_control_sha)
        self.assertNotEqual(changed.payload_sha256, encode_inert_data(payload).payload_sha256)

        # The control seal is recomputed on encode, so forging a control field in the
        # frame is caught on decode rather than being trusted.
        forged = decode_inert_data(encode_inert_data(payload).text)
        tampered = json.loads(encode_inert_data(payload).text[len(FRAMING_PREFIX) :])
        tampered["operation"]["strength"] = 99
        self.assertRaises(
            FramingError,
            decode_inert_data,
            FRAMING_PREFIX + json.dumps(tampered, sort_keys=True, separators=(",", ":")),
        )
        self.assertEqual(forged.payload["operation"]["strength"], payload["operation"]["strength"])

    def test_malformed_frames_fail_before_inference(self) -> None:
        case = FIXTURES["cases"][0]
        payload = _payload(
            document=case["documentText"],
            selected=case["selectedText"],
            protected=_spans(case["documentText"], case.get("protectedTexts", [])),
        )
        encoded_text = encode_inert_data(payload).text
        for bad in (
            "not-a-frame",
            FRAMING_PREFIX + "{",
            FRAMING_PREFIX + "[]",
            FRAMING_PREFIX + '{"contract":"other"}',
            encoded_text + "\ntrailing",
        ):
            with self.subTest(bad=bad[:40]):
                self.assertRaises(FramingError, decode_inert_data, bad)

    def test_selection_and_protected_identity_are_checked_locally(self) -> None:
        case = FIXTURES["cases"][2]
        document = case["documentText"]
        payload = _payload(
            document=document,
            selected=case["selectedText"],
            protected=_spans(document, case.get("protectedTexts", [])),
        )
        framed = encode_inert_data(payload).text
        decoded = decode_inert_data(framed)
        self.assertEqual(
            decoded.payload["source"]["sourceSha256"],
            hashlib.sha256(document.encode("utf-8")).hexdigest(),
        )
        self.assertEqual(
            decoded.payload["source"]["selectionSha256"],
            hashlib.sha256(case["selectedText"].encode("utf-8")).hexdigest(),
        )
        self.assertEqual(decoded.payload["source"]["documentText"], document)

    def test_context_protected_values_are_required_data_and_sealed_out_of_control(self) -> None:
        case = FIXTURES["cases"][1]
        document = case["documentText"]
        payload = _payload(document=document, selected=case["selectedText"])
        # Required-always-present: the key exists even when the value is empty.
        self.assertEqual(payload["contextProtectedValues"], [])
        encoded = encode_inert_data(payload)
        self.assertEqual(encoded.control_sha256, compute_control_sha256(payload))
        decoded = decode_inert_data(encoded.text)
        self.assertEqual(decoded.payload["contextProtectedValues"], [])

        # A context-only span is validated exactly like a protected span and, like
        # all source data, cannot change the control digest.
        span = {"text": document[0:3], "start": 0, "end": 3}
        before = encoded.control_sha256
        changed = deepcopy(payload)
        changed["contextProtectedValues"] = [span]
        resealed = encode_inert_data(changed)
        self.assertEqual(resealed.control_sha256, before)
        self.assertNotEqual(resealed.payload_sha256, encoded.payload_sha256)

        # Invalid context-only spans fail closed rather than being ignored.
        for bad in (
            "not-an-array",
            [{"text": "missing range fields"}],
            [{"text": "x", "start": 0}],
            [{"text": "no", "start": 0, "end": 9999}],
            [{"text": "mismatch", "start": 0, "end": 1}],
            [span, dict(span)],
        ):
            with self.subTest(bad=bad):
                broken = deepcopy(payload)
                broken["contextProtectedValues"] = bad
                self.assertRaises(FramingError, encode_inert_data, broken)


def main() -> int:
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(InertDataFramingContractTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
