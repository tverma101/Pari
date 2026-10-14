#!/usr/bin/env python3
"""Versioned inert-data framing for Pari Word Studio prompts.

The framed value is one canonical JSON object behind a fixed prefix. Every
document-derived value is a JSON string, so source text may repeat the prefix,
Studio headers, role labels, Markdown, or JSON without terminating or
impersonating the frame.

This module deliberately knows nothing about HTTP, model runtimes, or service
orchestration. Benchmark callers can use :func:`encode_inert_data` and
:func:`decode_inert_data` without importing the production service.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any


FRAMING_CONTRACT_VERSION = "pari-studio-prompt-v1"
FRAMING_PREFIX = "PARI_WORD_STUDIO_DATA_V1\n"
CONTROL_SHA256_FIELD = "controlSha256"
CONTEXT_PROTECTED_FIELD = "contextProtectedValues"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTROL_FIELDS = ("operation", "lane", "targetWords", "outputContract")


class FramingError(ValueError):
    """Raised when an inert-data frame or payload is malformed."""


@dataclass(frozen=True)
class EncodedInertData:
    contract_version: str
    text: str
    payload_sha256: str
    control_sha256: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "contractVersion": self.contract_version,
            "framing": "canonical-json-prefixed-v1",
            "payloadSha256": self.payload_sha256,
            "controlSha256": self.control_sha256,
        }


@dataclass(frozen=True)
class DecodedInertData:
    payload: dict[str, Any]
    payload_sha256: str
    control_sha256: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "contractVersion": FRAMING_CONTRACT_VERSION,
            "payloadSha256": self.payload_sha256,
            "controlSha256": self.control_sha256,
        }


def canonical_json(value: Any) -> str:
    """Return the one canonical UTF-8 JSON representation used by the frame."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise FramingError(f"prompt payload is not canonical JSON data: {error}") from error


def sha256_text(value: str) -> str:
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise FramingError("prompt payload contains invalid Unicode") from error
    return hashlib.sha256(encoded).hexdigest()


def compute_control_sha256(payload: dict[str, Any]) -> str:
    """Hash only authoritative control fields, never document-derived data."""
    control = {field: payload.get(field) for field in _CONTROL_FIELDS}
    return sha256_text(canonical_json(control))


def _exact_keys(value: Any, expected: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise FramingError(f"{path} must be an object")
    actual = set(value)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        raise FramingError(f"{path} keys mismatch: missing={missing}, extra={extra}")
    return value


def _string(value: Any, path: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str):
        raise FramingError(f"{path} must be a string")
    if nonempty and not value:
        raise FramingError(f"{path} must not be empty")
    return value


def _integer(value: Any, path: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FramingError(f"{path} must be an integer")
    if minimum is not None and value < minimum:
        raise FramingError(f"{path} must be >= {minimum}")
    return value


def _sha256(value: Any, path: str) -> str:
    text = _string(value, path)
    if not _SHA256_RE.fullmatch(text):
        raise FramingError(f"{path} must be a lowercase SHA-256 hex digest")
    return text


def _validate_operation(value: Any) -> None:
    operation = _exact_keys(
        value,
        {"id", "instruction", "semanticMode", "semanticRule", "strength", "controlNote"},
        "operation",
    )
    _string(operation["id"], "operation.id")
    _string(operation["instruction"], "operation.instruction")
    _string(operation["semanticMode"], "operation.semanticMode")
    _string(operation["semanticRule"], "operation.semanticRule")
    strength = _integer(operation["strength"], "operation.strength", minimum=0)
    if strength > 100:
        raise FramingError("operation.strength must be <= 100")
    _string(operation["controlNote"], "operation.controlNote")


def _validate_source(value: Any) -> None:
    source = _exact_keys(
        value,
        {
            "documentText",
            "documentContext",
            "selectedText",
            "selection",
            "contextRange",
            "sourceSha256",
            "selectionSha256",
        },
        "source",
    )
    document = _string(source["documentText"], "source.documentText", nonempty=False)
    context = _string(source["documentContext"], "source.documentContext", nonempty=False)
    selected = _string(source["selectedText"], "source.selectedText")
    if not selected:
        raise FramingError("source.selectedText must not be empty")

    selection = _exact_keys(source["selection"], {"start", "end"}, "source.selection")
    start = _integer(selection["start"], "source.selection.start", minimum=0)
    end = _integer(selection["end"], "source.selection.end", minimum=1)
    if end <= start or end > len(document):
        raise FramingError("source.selection is outside source.documentText")
    if document[start:end] != selected:
        raise FramingError("source.selectedText does not match source.selection")

    context_range = _exact_keys(source["contextRange"], {"start", "end"}, "source.contextRange")
    context_start = _integer(context_range["start"], "source.contextRange.start", minimum=0)
    context_end = _integer(context_range["end"], "source.contextRange.end", minimum=0)
    if context_start > context_end or context_end > len(document):
        raise FramingError("source.contextRange is outside source.documentText")
    if document[context_start:context_end] != context:
        raise FramingError("source.documentContext does not match source.contextRange")

    if _sha256(source["sourceSha256"], "source.sourceSha256") != sha256_text(document):
        raise FramingError("source.sourceSha256 does not match source.documentText")
    if _sha256(source["selectionSha256"], "source.selectionSha256") != sha256_text(selected):
        raise FramingError("source.selectionSha256 does not match source.selectedText")


def _validate_protected(value: Any, document: str, field: str = "protectedSpans") -> None:
    """Validate one closed array of protected spans against the document.

    ``protectedSpans`` and ``contextProtectedValues`` deliberately share this
    shape and validator: the second array is the same kind of source data and
    differs only in whether the span overlaps the selection. One validator means
    a context-only span can never be accepted under looser rules than a
    selection-overlapping one.
    """
    if not isinstance(value, list):
        raise FramingError(f"{field} must be an array")
    seen: set[tuple[int | None, int | None, str]] = set()
    for index, item in enumerate(value):
        path = f"{field}[{index}]"
        span = _exact_keys(item, {"text", "start", "end"}, path)
        text = _string(span["text"], f"{path}.text")
        start = span["start"]
        end = span["end"]
        if (start is None) != (end is None):
            raise FramingError(f"{path} start/end must both be null or both be integers")
        if start is not None and end is not None:
            start_value = _integer(start, f"{path}.start", minimum=0)
            end_value = _integer(end, f"{path}.end", minimum=1)
            if end_value <= start_value or end_value > len(document):
                raise FramingError(f"{path} range is outside source.documentText")
            if document[start_value:end_value] != text:
                raise FramingError(f"{path}.text does not match its source range")
        key = (start, end, text)
        if key in seen:
            raise FramingError(f"duplicate protected span at {path}")
        seen.add(key)


def _validate_lane(value: Any) -> int:
    lane = _exact_keys(
        value,
        {"id", "requestedFamilies", "candidateBudget", "maxNewTokens", "temperature", "topP"},
        "lane",
    )
    _string(lane["id"], "lane.id")
    families = lane["requestedFamilies"]
    if not isinstance(families, list) or not families:
        raise FramingError("lane.requestedFamilies must be a non-empty array")
    if any(not isinstance(item, str) or not item for item in families):
        raise FramingError("lane.requestedFamilies entries must be non-empty strings")
    if len(families) != len(set(families)):
        raise FramingError("lane.requestedFamilies must not contain duplicates")
    budget = _integer(lane["candidateBudget"], "lane.candidateBudget", minimum=1)
    if budget > 40:
        raise FramingError("lane.candidateBudget must be <= 40")
    _integer(lane["maxNewTokens"], "lane.maxNewTokens", minimum=1)
    temperature = _integer_or_number(lane["temperature"], "lane.temperature")
    if not 0 <= temperature <= 2:
        raise FramingError("lane.temperature must be in [0,2]")
    top_p = _integer_or_number(lane["topP"], "lane.topP")
    if not 0 < top_p <= 1:
        raise FramingError("lane.topP must be in (0,1]")
    return budget


def _integer_or_number(value: Any, path: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FramingError(f"{path} must be a finite number")
    if isinstance(value, float) and not (0 <= value <= 1000):
        raise FramingError(f"{path} must be finite")
    return value


def _validate_target_words(value: Any) -> None:
    target = _exact_keys(value, {"minWords", "maxWords"}, "targetWords")
    minimum = target["minWords"]
    maximum = target["maxWords"]
    if minimum is not None:
        minimum = _integer(minimum, "targetWords.minWords", minimum=1)
    if maximum is not None:
        maximum = _integer(maximum, "targetWords.maxWords", minimum=1)
    if minimum is not None and maximum is not None and minimum > maximum:
        raise FramingError("targetWords.minWords must be <= targetWords.maxWords")


def _validate_output_contract(value: Any, candidate_budget: int) -> None:
    output = _exact_keys(
        value,
        {"format", "field", "count", "schema", "instruction"},
        "outputContract",
    )
    if output["format"] != "json_object":
        raise FramingError("outputContract.format must be json_object")
    field = _string(output["field"], "outputContract.field")
    count = _integer(output["count"], "outputContract.count", minimum=1)
    if count != candidate_budget:
        raise FramingError("outputContract.count must equal lane.candidateBudget")
    if not isinstance(output["schema"], dict) or not output["schema"]:
        raise FramingError("outputContract.schema must be a non-empty object")
    instruction = _string(output["instruction"], "outputContract.instruction")
    if field not in instruction or str(count) not in instruction:
        raise FramingError("outputContract.instruction must name its field and count")


def validate_inert_data_payload(payload: Any, *, require_control_hash: bool = True) -> dict[str, Any]:
    """Validate one unsealed or sealed prompt payload and return it unchanged."""
    expected_top = {
        "contract",
        "operation",
        "source",
        "protectedSpans",
        CONTEXT_PROTECTED_FIELD,
        "lane",
        "targetWords",
        "outputContract",
    }
    if require_control_hash:
        expected_top.add(CONTROL_SHA256_FIELD)
    value = _exact_keys(payload, expected_top, "prompt")
    if value["contract"] != FRAMING_CONTRACT_VERSION:
        raise FramingError("unsupported inert-data contract version")
    _validate_operation(value["operation"])
    _validate_source(value["source"])
    _validate_protected(value["protectedSpans"], value["source"]["documentText"])
    _validate_protected(value[CONTEXT_PROTECTED_FIELD], value["source"]["documentText"], CONTEXT_PROTECTED_FIELD)
    candidate_budget = _validate_lane(value["lane"])
    _validate_target_words(value["targetWords"])
    _validate_output_contract(value["outputContract"], candidate_budget)
    if require_control_hash:
        recorded = _sha256(value[CONTROL_SHA256_FIELD], f"{CONTROL_SHA256_FIELD}")
        if recorded != compute_control_sha256(value):
            raise FramingError("controlSha256 does not match authoritative control fields")
    return value


def seal_inert_data_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a validated payload with a digest over only control fields."""
    if isinstance(payload, dict) and CONTROL_SHA256_FIELD in payload:
        return validate_inert_data_payload(payload)
    validate_inert_data_payload(payload, require_control_hash=False)
    sealed = dict(payload)
    sealed[CONTROL_SHA256_FIELD] = compute_control_sha256(sealed)
    return validate_inert_data_payload(sealed)


def encode_inert_data(payload: dict[str, Any]) -> EncodedInertData:
    """Seal and frame a payload without any lossy normalization."""
    sealed = seal_inert_data_payload(payload)
    serialized = canonical_json(sealed)
    return EncodedInertData(
        contract_version=FRAMING_CONTRACT_VERSION,
        text=FRAMING_PREFIX + serialized,
        payload_sha256=sha256_text(serialized),
        control_sha256=sealed[CONTROL_SHA256_FIELD],
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FramingError(f"duplicate JSON key in inert-data frame: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise FramingError(f"non-finite JSON constant in inert-data frame: {value}")


def decode_inert_data(framed: str) -> DecodedInertData:
    """Validate and recover the exact payload plus stable identity hashes."""
    if not isinstance(framed, str):
        raise FramingError("inert-data frame must be a string")
    if not framed.startswith(FRAMING_PREFIX):
        raise FramingError("missing inert-data contract prefix")
    serialized = framed[len(FRAMING_PREFIX) :]
    if not serialized:
        raise FramingError("empty inert-data payload")
    try:
        payload = json.loads(
            serialized,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except FramingError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise FramingError("malformed inert-data JSON") from error
    canonical = canonical_json(payload)
    if canonical != serialized:
        raise FramingError("inert-data payload is not canonical JSON")
    validated = validate_inert_data_payload(payload)
    return DecodedInertData(
        payload=validated,
        payload_sha256=sha256_text(serialized),
        control_sha256=validated[CONTROL_SHA256_FIELD],
    )


__all__ = [
    "CONTEXT_PROTECTED_FIELD",
    "CONTROL_SHA256_FIELD",
    "DecodedInertData",
    "EncodedInertData",
    "FRAMING_CONTRACT_VERSION",
    "FRAMING_PREFIX",
    "FramingError",
    "canonical_json",
    "compute_control_sha256",
    "decode_inert_data",
    "encode_inert_data",
    "seal_inert_data_payload",
    "sha256_text",
    "validate_inert_data_payload",
]
