#!/usr/bin/env python3
"""Unicode-safe wire ranges and source identity for the Pari Studio contract.

Issue #50 fixes one wire coordinate unit: UTF-16 code units, matching AppKit
``NSRange``. Conversions are deterministic and lossless: offsets that land in
the middle of a surrogate pair, past the end of the text, or inside an invalid
UTF-16 sequence are rejected instead of rounded. Source text is never
normalized, so an exact substring cross-check still compares the original
code points.

Wire contract (``pari-studio-request-v2``) binds each transform to an
immutable source state so a late or reordered response can be discarded:

.. code-block:: json

    {
      "contractVersion": "pari-studio-request-v2",
      "rangeEncoding": "utf16-v1",
      "documentText": "<exact source bytes as text>",
      "sourceIdentity": {
        "documentSha256": "<sha256(documentText.encode('utf-8'))>",
        "documentRevision": "<opaque client revision, optional>"
      },
      "selection": {"start": 6, "end": 12},          // UTF-16 code units
      "selectedText": "<exact documentText[selection]>",
      "selectionSha256": "<selection_identity_sha256(...)>",
      "protectedSpans": [
        {"text": "Ada", "start": 0, "end": 3,        // UTF-16 code units
         "protectedSpanSha256": "<protected_span_identity_sha256(...)>"}
      ]
    }

All identity digests are lowercase SHA-256 hex over UTF-8 bytes. Source text is
hashed and compared exactly; Unicode normalization (NFC/NFD/NFKC/NFKD), case
folding, trimming, and "search nearby" relocation are never applied. A range
that cannot reproduce the client-declared ``selectedText`` (or a protected span
text) byte-for-byte fails closed.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

from .errors import ServiceRequestError


RANGE_ENCODING_VERSION = "utf16-v1"
REQUEST_CONTRACT_VERSION = "pari-studio-request-v2"
SUPPORTED_RANGE_ENCODINGS = frozenset({RANGE_ENCODING_VERSION})

# U+001F (ASCII UNIT SEPARATOR) frames the identity preimage so no field value
# can be confused with a boundary. Both Python and the macOS/TypeScript client
# must join with this exact code point and hash the resulting UTF-8 bytes.
_IDENTITY_SEPARATOR = "\u001f"
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def utf16_length(text: str, *, field: str = "documentText") -> int:
    """Return the UTF-16 code-unit length of ``text``.

    Rejects strings containing unpaired surrogates (which have no UTF-16
    representation) with ``ServiceRequestError`` instead of leaking a codec
    error.
    """
    try:
        return len(text.encode("utf-16-le")) // 2
    except UnicodeEncodeError as exc:
        raise ServiceRequestError(field) from exc


def _allowed_offsets(text: str, *, field: str = "documentText") -> dict[int, int]:
    """Map each legal UTF-16 boundary offset to a Python string index.

    A "legal" offset is one that does not land inside a surrogate pair and is
    within ``[0, utf16_length(text)]``. Any offset that would address the low
    surrogate of a non-BMP code point is deliberately absent from the map, so
    callers reject it rather than round it to a neighboring boundary.
    """
    offsets: dict[int, int] = {0: 0}
    unit = 0
    for index, char in enumerate(text):
        code_point = ord(char)
        if 0xD800 <= code_point <= 0xDFFF:
            # Python can hold unpaired surrogates via \uD800-style JSON escapes,
            # but they are not representable as UTF-16 and must be rejected.
            raise ServiceRequestError(field)
        width = 2 if ord(char) > 0xFFFF else 1
        if width == 2:
            # unit + 1 addresses the low surrogate and is not a legal boundary.
            unit += 2
        else:
            unit += 1
        offsets[unit] = index + 1
    return offsets


def utf16_offset_to_index(text: str, offset: int, *, field: str) -> int:
    """Convert a UTF-16 code-unit offset to a Python string index.

    Raises ``ServiceRequestError`` when ``offset`` is negative, not an exact
    ``int`` (bools, floats, and numeric strings are rejected, never coerced),
    inside a surrogate pair, or past the end of ``text``.
    """
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise ServiceRequestError(field)
    if offset < 0:
        raise ServiceRequestError(field)
    offsets = _allowed_offsets(text, field=field)
    try:
        return offsets[offset]
    except KeyError as exc:
        raise ServiceRequestError(field) from exc


def utf16_range_to_slice(text: str, start: int, end: int, *, field: str) -> tuple[int, int]:
    """Convert a half-open UTF-16 ``[start, end)`` range to Python indices.

    Builds the boundary map once so validating a range costs a single pass over
    the document, and reports the offending endpoint in the error field.
    """
    wire_start = require_wire_offset(start, field=f"{field}.start")
    wire_end = require_wire_offset(end, field=f"{field}.end")
    if wire_end <= wire_start:
        raise ServiceRequestError(field)
    offsets = _allowed_offsets(text, field=field)
    try:
        codepoint_start = offsets[wire_start]
    except KeyError as exc:
        raise ServiceRequestError(f"{field}.start") from exc
    try:
        codepoint_end = offsets[wire_end]
    except KeyError as exc:
        raise ServiceRequestError(f"{field}.end") from exc
    return codepoint_start, codepoint_end


def code_point_to_utf16(text: str, index: int, *, field: str = "documentText") -> int:
    """Convert a Python string index (code-point offset) to a UTF-16 offset.

    This is the inverse of :func:`utf16_offset_to_index` and is used by the
    server-side encoder that serializes an internal request back to the wire.
    ``index`` must be in ``[0, len(text)]``.
    """
    if isinstance(index, bool) or not isinstance(index, int):
        raise ServiceRequestError(field)
    if index < 0 or index > len(text):
        raise ServiceRequestError(field)
    return utf16_length(text[:index], field=field)


def require_supported_range_encoding(value: Any, *, field: str = "rangeEncoding") -> str:
    """Validate that ``value`` is a supported range-encoding version string."""
    if not isinstance(value, str) or value not in SUPPORTED_RANGE_ENCODINGS:
        raise ServiceRequestError(field)
    return value


def require_wire_offset(value: Any, *, field: str) -> int:
    """Validate that ``value`` is a non-negative, exact-integer wire offset."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ServiceRequestError(field)
    if value < 0:
        raise ServiceRequestError(field)
    return value


def require_sha256_hex(value: Any, *, field: str) -> str:
    """Validate that ``value`` is a lowercase 64-char SHA-256 hex digest."""
    if not isinstance(value, str) or not _SHA256_HEX.fullmatch(value):
        raise ServiceRequestError(field)
    return value


def source_identity_sha256(value: str, *, field: str = "sourceText") -> str:
    """SHA-256 of the exact UTF-8 bytes of ``value`` (no normalization).

    This is the canonical digest for ``sourceIdentity.documentSha256``. The
    text is hashed exactly as received: no NFC/NFD/NFKC/NFKD normalization, no
    case folding, no trimming, and lone surrogates are rejected because they
    have no UTF-8 (or UTF-16) representation.
    """
    if not isinstance(value, str):
        raise ServiceRequestError(field)
    try:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    except UnicodeEncodeError as exc:
        raise ServiceRequestError(field) from exc


# Compatibility alias: earlier call sites imported ``sha256_text`` for the same
# exact-UTF-8 digest. Keep one implementation so the two names cannot drift.
sha256_text = source_identity_sha256


def _identity_preimage(
    *,
    source_sha256: str,
    range_encoding: str,
    wire_start: int,
    wire_end: int,
    text: str,
    field: str,
) -> bytes:
    preimage = _IDENTITY_SEPARATOR.join(
        [
            range_encoding,
            source_sha256,
            str(wire_start),
            str(wire_end),
            text,
        ]
    )
    try:
        return preimage.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ServiceRequestError(field) from exc


def selection_identity_sha256(
    *,
    source_sha256: str,
    range_encoding: str,
    wire_start: int,
    wire_end: int,
    selected_text: str,
) -> str:
    """Canonical digest binding document state, position, and exact selection.

    Binds the selection to *both* the immutable source bytes (via
    ``source_sha256``) and its exact position (via the UTF-16 offsets) so two
    identical substrings at different positions produce different identities.
    The ``documentRevision`` string is intentionally *not* part of this digest:
    it is an opaque client token compared separately, and excluding it keeps
    the digest computable by clients that only track bytes.
    """
    require_sha256_hex(source_sha256, field="sourceIdentity.documentSha256")
    require_supported_range_encoding(range_encoding, field="rangeEncoding")
    start = require_wire_offset(wire_start, field="selection.start")
    end = require_wire_offset(wire_end, field="selection.end")
    return hashlib.sha256(
        _identity_preimage(
            source_sha256=source_sha256,
            range_encoding=range_encoding,
            wire_start=start,
            wire_end=end,
            text=selected_text,
            field="selectedText",
        )
    ).hexdigest()


def protected_span_identity_sha256(
    *,
    source_sha256: str,
    range_encoding: str,
    wire_start: int,
    wire_end: int,
    span_text: str,
) -> str:
    """Canonical digest binding document state, position, and exact span text."""
    require_sha256_hex(source_sha256, field="sourceIdentity.documentSha256")
    require_supported_range_encoding(range_encoding, field="rangeEncoding")
    start = require_wire_offset(wire_start, field="protectedSpans.start")
    end = require_wire_offset(wire_end, field="protectedSpans.end")
    return hashlib.sha256(
        _identity_preimage(
            source_sha256=source_sha256,
            range_encoding=range_encoding,
            wire_start=start,
            wire_end=end,
            text=span_text,
            field="protectedSpans.text",
        )
    ).hexdigest()


def exact_slice_from_utf16(text: str, start: int, end: int, *, field: str) -> str:
    """Return the exact substring for a validated UTF-16 ``[start, end)`` range."""
    cp_start, cp_end = utf16_range_to_slice(text, start, end, field=field)
    return text[cp_start:cp_end]


def parse_source_identity(
    body: Mapping[str, Any],
    *,
    field: str = "sourceIdentity",
) -> tuple[str, str | None]:
    """Validate the nested ``sourceIdentity`` object and return
    ``(document_sha256, document_revision)``.

    The object must contain ``documentSha256`` (64-hex) and may contain an
    opaque ``documentRevision`` string. Unknown/legacy flat spellings
    (``sourceHash``/``documentHash``) are intentionally *not* accepted here;
    the caller owns the decision to reject or migrate them at the request
    boundary.
    """
    value = body.get(field)
    if not isinstance(value, Mapping):
        raise ServiceRequestError(field)
    document_sha256 = require_sha256_hex(
        value.get("documentSha256"), field=f"{field}.documentSha256"
    )
    revision_value = value.get("documentRevision")
    document_revision: str | None = None
    if revision_value is not None:
        if not isinstance(revision_value, str):
            raise ServiceRequestError(f"{field}.documentRevision")
        document_revision = revision_value
    return document_sha256, document_revision


__all__ = [
    "RANGE_ENCODING_VERSION",
    "REQUEST_CONTRACT_VERSION",
    "SUPPORTED_RANGE_ENCODINGS",
    "code_point_to_utf16",
    "exact_slice_from_utf16",
    "parse_source_identity",
    "protected_span_identity_sha256",
    "require_sha256_hex",
    "require_supported_range_encoding",
    "require_wire_offset",
    "selection_identity_sha256",
    "source_identity_sha256",
    "sha256_text",
    "utf16_length",
    "utf16_offset_to_index",
    "utf16_range_to_slice",
]
