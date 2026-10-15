#!/usr/bin/env python3
"""Shared protected-content contract for issue #51.

One versioned implementation of the protected-content rules that the Mac app,
the benchmark parser, and the Python Studio service all test against. The
language-neutral fixture corpus lives at
``app/tests/fixtures/protected-content-contract-v1.json``.

Design rules that must not drift:

- protected payloads are compared code-point-for-code-point, never as bare
  substrings, so ``$50`` does not survive as ``$500`` and ``report.txt`` does
  not survive as ``report.txt.bak``;
- wire coordinates are UTF-16 code units (``utf16-v1``, issue #50) and are
  converted to Python string indices before any slicing;
- span identity binds the exact source revision, position, and payload through
  a five-field SHA-256 preimage, and mismatches fail closed;
- repeated identical payloads are tracked per span, never per text value;
- negation and modality are semantic anchors: they must survive, and the
  ``exact`` anchor policy also rejects an added or swapped anchor;
- introduced protected-looking content is reported separately from changed or
  missing protected content.

This module deliberately does not import ``word_studio_output_parser`` so the
benchmark parser can consume it without an import cycle.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import re
from typing import Any, Iterable, Mapping, Sequence

from .range_encoding import (
    RANGE_ENCODING_VERSION,
    utf16_offset_to_index,
)


PROTECTED_CONTENT_CONTRACT_VERSION = 1
IDENTITY_PREIMAGE_SEPARATOR = "\u001f"

PROTECTED_SPAN_KINDS: tuple[str, ...] = (
    "url",
    "email",
    "quote",
    "citation",
    "date",
    "time",
    "number",
    "percentage",
    "currency",
    "name",
    "negation",
    "modality",
    "list-marker",
    "code",
)
PROTECTED_SPAN_SCOPES: tuple[str, ...] = ("required", "context-only")
PROTECTED_ROUTES: tuple[str, ...] = ("whole", "local")
ANCHOR_POLICIES: tuple[str, ...] = ("minimum", "exact")

ANCHOR_KINDS = frozenset({"negation", "modality"})
NUMERIC_KINDS = frozenset({"number", "percentage", "currency", "date", "time"})
SAME_KIND_ALTERED_KINDS = frozenset(
    {"url", "email", "quote", "citation", "name", "code"}
)
CONTAINER_KINDS = frozenset({"quote", "code", "date", "time", "currency", "percentage"})

FAILURE_PRECEDENCE: tuple[str, ...] = (
    "identity_mismatch",
    "protected_altered",
    "protected_repeated_mismatch",
    "protected_missing",
    "protected_position_drift",
    "protected_introduced",
)

IDENTITY_ERROR_CODES: tuple[str, ...] = (
    "stale_document_identity",
    "stale_selection_identity",
    "stale_span_identity",
    "unsupported_range_encoding",
    "invalid_span_range",
    "span_text_mismatch",
)


class ProtectedContentError(ValueError):
    """Fail-closed protected-content identity or range error."""

    def __init__(self, code: str, detail: str = "") -> None:
        if code not in IDENTITY_ERROR_CODES:
            raise ValueError(f"unknown protected-content error code: {code}")
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class ProtectedContentSpan:
    """One protected span in code-point index space.

    ``start``/``end`` are Python string indices (code points). Wire payloads use
    UTF-16 code units; use :func:`span_from_wire` to convert and validate.
    """

    id: str
    kind: str
    scope: str
    text: str
    start: int | None = None
    end: int | None = None
    range_encoding: str = RANGE_ENCODING_VERSION
    source_sha256: str | None = None
    protected_span_sha256: str | None = None
    candidate_start: int | None = None
    candidate_end: int | None = None

    @property
    def has_range(self) -> bool:
        return self.start is not None and self.end is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "scope": self.scope,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "rangeEncoding": self.range_encoding,
            "sourceSha256": self.source_sha256,
            "protectedSpanSha256": self.protected_span_sha256,
        }


@dataclass(frozen=True)
class ProtectedEvaluation:
    contract_version: int
    safe: bool
    failure_class: str | None
    failure_span_ids: tuple[str, ...]
    missing_span_ids: tuple[str, ...]
    altered_span_ids: tuple[str, ...]
    repeated_mismatch_span_ids: tuple[str, ...]
    position_drift_span_ids: tuple[str, ...]
    introduced_span_ids: tuple[str, ...]
    introduced: tuple[str, ...]

    @property
    def corrupted(self) -> bool:
        return not self.safe

    def to_dict(self) -> dict[str, Any]:
        return {
            "contractVersion": self.contract_version,
            "rangeEncoding": RANGE_ENCODING_VERSION,
            "safe": self.safe,
            "corrupted": self.corrupted,
            "failureClass": self.failure_class,
            "failureSpanIds": list(self.failure_span_ids),
            "missingSpanIds": list(self.missing_span_ids),
            "alteredSpanIds": list(self.altered_span_ids),
            "repeatedMismatchSpanIds": list(self.repeated_mismatch_span_ids),
            "positionDriftSpanIds": list(self.position_drift_span_ids),
            "introducedSpanIds": list(self.introduced_span_ids),
            "introduced": list(self.introduced),
        }


# ---------------------------------------------------------------------------
# Identity helpers (issue #50 preimage, kept byte-identical to the TypeScript)
# ---------------------------------------------------------------------------


def compute_source_sha256(text: str) -> str:
    """Lowercase SHA-256 hex of the exact UTF-8 bytes; no normalization."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_range_sha256(
    range_encoding: str,
    source_sha256: str,
    wire_start: int,
    wire_end: int,
    text: str,
) -> str:
    preimage = IDENTITY_PREIMAGE_SEPARATOR.join(
        [range_encoding, source_sha256, str(wire_start), str(wire_end), text]
    )
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


def compute_selection_sha256(
    range_encoding: str,
    source_sha256: str,
    wire_start: int,
    wire_end: int,
    selected_text: str,
) -> str:
    return compute_range_sha256(
        range_encoding, source_sha256, wire_start, wire_end, selected_text
    )


def compute_protected_span_sha256(
    range_encoding: str,
    source_sha256: str,
    wire_start: int,
    wire_end: int,
    text: str,
) -> str:
    return compute_range_sha256(range_encoding, source_sha256, wire_start, wire_end, text)


def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _wire_range_to_index(text: str, start: Any, end: Any, *, field: str) -> tuple[int, int]:
    if isinstance(start, bool) or isinstance(end, bool):
        raise ProtectedContentError("invalid_span_range", field)
    if not isinstance(start, int) or not isinstance(end, int):
        raise ProtectedContentError("invalid_span_range", field)
    if start < 0 or end <= start:
        raise ProtectedContentError("invalid_span_range", field)
    try:
        index_start = utf16_offset_to_index(text, start, field=f"{field}.start")
        index_end = utf16_offset_to_index(text, end, field=f"{field}.end")
    except Exception as exc:  # ServiceRequestError for surrogate/out-of-range
        raise ProtectedContentError("invalid_span_range", field) from exc
    if index_end <= index_start:
        raise ProtectedContentError("invalid_span_range", field)
    return index_start, index_end


def span_from_wire(
    source_text: str,
    payload: Mapping[str, Any],
    *,
    source_sha256: str | None = None,
    index: int = 0,
) -> ProtectedContentSpan:
    """Validate a wire protected-span payload against the exact source text.

    Coordinate-bearing spans must reproduce their declared payload byte-for-byte
    at the declared UTF-16 range; there is deliberately no nearby search.
    """

    range_encoding = str(payload.get("rangeEncoding") or RANGE_ENCODING_VERSION)
    if range_encoding != RANGE_ENCODING_VERSION:
        raise ProtectedContentError("unsupported_range_encoding", range_encoding)
    text = payload.get("text")
    if not isinstance(text, str) or not text:
        raise ProtectedContentError("span_text_mismatch", "empty protected text")
    raw_start = payload.get("start")
    raw_end = payload.get("end")
    if raw_start is None or raw_end is None:
        span_id = str(payload.get("id") or _coordinate_free_span_id(text, index))
        return ProtectedContentSpan(
            id=span_id,
            kind=_coerce_kind(payload.get("kind")),
            scope=_coerce_scope(payload.get("scope")),
            text=text,
            start=None,
            end=None,
            range_encoding=range_encoding,
            source_sha256=source_sha256 or payload.get("sourceSha256"),
            protected_span_sha256=payload.get("protectedSpanSha256"),
            candidate_start=payload.get("candidateStart"),
            candidate_end=payload.get("candidateEnd"),
        )

    index_start, index_end = _wire_range_to_index(
        source_text, raw_start, raw_end, field="protectedSpan"
    )
    if source_text[index_start:index_end] != text:
        raise ProtectedContentError("span_text_mismatch", text)
    expected_source = source_sha256 or payload.get("sourceSha256")
    if expected_source is not None and expected_source != compute_source_sha256(source_text):
        raise ProtectedContentError("stale_document_identity", str(expected_source))
    declared = payload.get("protectedSpanSha256")
    if declared is not None:
        if not isinstance(declared, str):
            raise ProtectedContentError("stale_span_identity", "non-string digest")
        if expected_source is None:
            expected_source = compute_source_sha256(source_text)
        expected = compute_protected_span_sha256(
            range_encoding, expected_source, raw_start, raw_end, text
        )
        if declared != expected:
            raise ProtectedContentError("stale_span_identity", text)
    span_id = str(payload.get("id") or f"span-{index}-{raw_start}-{raw_end}")
    return ProtectedContentSpan(
        id=span_id,
        kind=_coerce_kind(payload.get("kind")),
        scope=_coerce_scope(payload.get("scope")),
        text=text,
        start=index_start,
        end=index_end,
        range_encoding=range_encoding,
        source_sha256=expected_source,
        protected_span_sha256=declared,
        candidate_start=payload.get("candidateStart"),
        candidate_end=payload.get("candidateEnd"),
    )


def _coerce_kind(value: Any) -> str:
    if isinstance(value, str) and value in PROTECTED_SPAN_KINDS:
        return value
    return "code"


def _coerce_scope(value: Any) -> str:
    if isinstance(value, str) and value in PROTECTED_SPAN_SCOPES:
        return value
    return "required"


def _coordinate_free_span_id(text: str, index: int) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"text-{index}-{digest}"


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def normalize_protected_spans(
    value: Any,
    *,
    source_text: str | None = None,
    source_sha256: str | None = None,
    range_encoding: str = RANGE_ENCODING_VERSION,
    strict: bool = False,
) -> tuple[ProtectedContentSpan, ...]:
    """Normalize caller spans into the canonical protected-content shape.

    Accepts :class:`ProtectedContentSpan` instances, mappings with ``text`` and
    optional ``kind``/``scope``/``id``/``start``/``end``, plain strings, and any
    iterable of those. With ``source_text`` the ranges are validated against the
    exact source; with ``strict=True`` any mismatch raises
    :class:`ProtectedContentError` instead of falling back to text-only
    matching.
    """

    items: list[Any]
    if value is None:
        items = []
    elif isinstance(value, (str, Mapping, ProtectedContentSpan)):
        items = [value]
    elif isinstance(value, Iterable):
        items = list(value)
    else:
        items = [value]

    out: list[ProtectedContentSpan] = []
    for index, item in enumerate(items):
        if isinstance(item, ProtectedContentSpan):
            span = item
            if source_text is not None:
                checked = _revalidate_span(span, source_text, source_sha256, strict)
                out.append(checked)
            else:
                out.append(span)
            continue
        if isinstance(item, str):
            payload: Mapping[str, Any] = {"text": item}
        elif isinstance(item, Mapping):
            payload = item
        else:
            payload = {"text": str(item)}
        if source_text is not None:
            out.append(span_from_wire(source_text, payload, source_sha256=source_sha256, index=index))
        else:
            text = str(payload.get("text") or "")
            out.append(
                ProtectedContentSpan(
                    id=str(payload.get("id") or _coordinate_free_span_id(text, index)),
                    kind=_coerce_kind(payload.get("kind")),
                    scope=_coerce_scope(payload.get("scope")),
                    text=text,
                    start=payload.get("start"),
                    end=payload.get("end"),
                    range_encoding=str(payload.get("rangeEncoding") or range_encoding),
                    source_sha256=payload.get("sourceSha256"),
                    protected_span_sha256=payload.get("protectedSpanSha256"),
                    candidate_start=payload.get("candidateStart"),
                    candidate_end=payload.get("candidateEnd"),
                )
            )
    return tuple(out)


def _revalidate_span(
    span: ProtectedContentSpan,
    source_text: str,
    source_sha256: str | None,
    strict: bool,
) -> ProtectedContentSpan:
    if span.range_encoding != RANGE_ENCODING_VERSION:
        if strict:
            raise ProtectedContentError("unsupported_range_encoding", span.range_encoding)
        return span
    if not span.has_range:
        return span
    try:
        wire_start = utf16_length(source_text[: span.start or 0])
        wire_end = wire_start + utf16_length(span.text)
        index_start, index_end = _wire_range_to_index(
            source_text, wire_start, wire_end, field="protectedSpan"
        )
    except ProtectedContentError:
        if strict:
            raise
        return span
    if source_text[index_start:index_end] != span.text:
        if strict:
            raise ProtectedContentError("span_text_mismatch", span.text)
        return span
    digest_source = source_sha256 or compute_source_sha256(source_text)
    if span.protected_span_sha256 is not None:
        expected = compute_protected_span_sha256(
            span.range_encoding, digest_source, wire_start, wire_end, span.text
        )
        if span.protected_span_sha256 != expected:
            if strict:
                raise ProtectedContentError("stale_span_identity", span.text)
            return span
    if span.source_sha256 is not None and span.source_sha256 != digest_source:
        if strict:
            raise ProtectedContentError("stale_document_identity", span.text)
        return span
    return replace(
        span,
        start=index_start,
        end=index_end,
        source_sha256=span.source_sha256 or digest_source,
    )


# ---------------------------------------------------------------------------
# Detection (mirrors the TypeScript extractor closely enough for the corpus)
# ---------------------------------------------------------------------------

_PATTERNS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("url", re.compile(r"\bhttps?://[^\s<>)\]]+", re.I), 100),
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I), 100),
    ("quote", re.compile(r"[\u201c\u201e\"][^\u201d\"\n]+[\u201d\"]"), 90),
    ("citation", re.compile(r"\[[^\]\n]{1,100}\]"), 85),
    ("citation", re.compile(r"\([A-Z][^()\n]{0,70}\b\d{4}\b[^()\n]*\)"), 85),
    (
        "currency",
        re.compile(
            r"(?:[\u0024\u20ac\u00a3\u00a5]\s*\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s*(?:USD|EUR|GBP|JPY)\b)",
            re.I,
        ),
        80,
    ),
    ("percentage", re.compile(r"\b\d+(?:\.\d+)?\s?%(?!\w)"), 80),
    (
        "date",
        re.compile(
            r"\b(?:\d{1,4}[-/]\d{1,2}[-/]\d{1,4}|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:,\s*\d{4})?)\b",
            re.I,
        ),
        78,
    ),
    ("time", re.compile(r"\b\d{1,2}:\d{2}(?:\s?[AP]M)?\b", re.I), 78),
    (
        "number",
        re.compile(
            r"\b\d[\d,]*(?:\.\d+)?(?:\s?(?:kg|g|lb|lbs|km|mi|MB|GB|ms|s|hours?|minutes?|years?))?\b",
            re.I,
        ),
        72,
    ),
    ("list-marker", re.compile(r"^[ \t]*(?:[-*\u2022]|\d+[.)])(?=\s)", re.M), 70),
    (
        "negation",
        re.compile(
            r"\b(?:not|never|no|without|cannot|can't|don't|doesn't|didn't|won't|wouldn't|shouldn't)\b",
            re.I,
        ),
        65,
    ),
    (
        "modality",
        re.compile(r"\b(?:may|might|could|can|must|should|will|would|shall)\b", re.I),
        64,
    ),
    (
        "code",
        re.compile(
            r"(?:[A-Za-z0-9_@~-]+[\\/])*[A-Za-z0-9_@~-]+\.(?:pdf|docx?|xlsx?|pptx?|txt|csv|json|md|ya?ml|toml|ini|log|py|ts|tsx|js|jsx|mjs|cjs|rs|go|java|kt|swift|c|h|cc|cpp|hpp|sh)(?![\w.-])",
            re.I,
        ),
        92,
    ),
)

_NAME_RE = re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})+\b")
_HONORIFIC_NAME_RE = re.compile(
    r"\b(?:Dr|Mr|Ms|Mrs|Prof|Professor)\.?\s+([A-Z][a-z]{2,})\b"
)
_FENCE_OPEN_RE = re.compile(r"^(`{3,}|~{3,})")


def _trim_trailing_punctuation(kind: str, text: str) -> str:
    if kind in {"quote", "citation", "code"}:
        return text
    return re.sub(r"[.,;:!?]+$", "", text)


def _scan_fenced_code(text: str) -> list[tuple[str, int, int, int]]:
    spans: list[tuple[str, int, int, int]] = []
    offset = 0
    open_marker: tuple[str, int, int] | None = None  # (char, length, start)
    for line in text.split("\n"):
        stripped = line.lstrip()
        match = _FENCE_OPEN_RE.match(stripped)
        if match:
            marker = match.group(1)
            marker_start = offset + line.index(marker)
            if open_marker is None:
                open_marker = (marker[0], len(marker), marker_start)
            elif marker[0] == open_marker[0] and len(marker) >= open_marker[1] and stripped == marker:
                end = marker_start + len(marker)
                spans.append(("code", open_marker[2], end, 92))
                open_marker = None
        offset += len(line) + 1
    if open_marker is not None:
        spans.append(("code", open_marker[2], len(text), 92))
    return spans


def _scan_inline_code(
    text: str, fenced: Sequence[tuple[str, int, int, int]]
) -> list[tuple[str, int, int, int]]:
    def in_fence(index: int) -> bool:
        return any(start <= index < end for _, start, end, _ in fenced)

    spans: list[tuple[str, int, int, int]] = []
    index = 0
    while index < len(text):
        if text[index] != "`" or in_fence(index):
            index += 1
            continue
        run = 1
        while index + run < len(text) and text[index + run] == "`":
            run += 1
        cursor = index + run
        closing = -1
        while cursor < len(text):
            if text[cursor] == "`" and not in_fence(cursor):
                length = 1
                while cursor + length < len(text) and text[cursor + length] == "`":
                    length += 1
                if length == run:
                    closing = cursor
                    break
                cursor += length
                continue
            cursor += 1
        if closing < 0:
            index += run
            continue
        end = closing + run
        spans.append(("code", index, end, 92))
        index = end
    return spans


def extract_protected_spans(text: str) -> tuple[ProtectedContentSpan, ...]:
    """Detect the canonical protected classes with stable ids and identity."""

    source_sha256 = compute_source_sha256(text)
    candidates: list[tuple[str, str, int, int, int]] = []
    for kind, pattern, priority in _PATTERNS:
        for match in pattern.finditer(text):
            value = _trim_trailing_punctuation(kind, match.group(0))
            if not value:
                continue
            candidates.append((kind, value, match.start(), match.start() + len(value), priority))

    fenced = _scan_fenced_code(text)
    inline = _scan_inline_code(text, fenced)
    for kind, start, end, priority in [*fenced, *inline]:
        candidates.append((kind, text[start:end], start, end, priority))

    for match in _NAME_RE.finditer(text):
        candidates.append(("name", match.group(0), match.start(), match.end(), 75))
    for match in _HONORIFIC_NAME_RE.finditer(text):
        name = match.group(1)
        start = match.start() + match.group(0).rfind(name)
        end = start + len(name)
        if re.match(r"\s+[A-Z][a-z]{2,}\b", text[end:]):
            continue
        candidates.append(("name", name, start, end, 74))

    ordered = sorted(candidates, key=lambda item: (item[2], -item[4], -item[3]))
    selected: list[tuple[str, str, int, int, int]] = []
    for candidate in ordered:
        kind, _, start, end, _ = candidate
        rejected = False
        for existing in selected:
            existing_kind, _, existing_start, existing_end, _ = existing
            if existing_kind == kind and existing_start == start and existing_end == end:
                rejected = True
                break
            if (
                existing_kind == "code"
                and kind == "code"
                and existing_start < end
                and start < existing_end
            ):
                rejected = True
                break
            if (
                kind == "number"
                and existing_kind != "number"
                and existing_kind in CONTAINER_KINDS
                and existing_start <= start
                and existing_end >= end
                and (existing_start, existing_end) != (start, end)
            ):
                rejected = True
                break
        if rejected:
            continue
        selected.append(candidate)

    selected.sort(key=lambda item: item[2])
    spans: list[ProtectedContentSpan] = []
    for index, (kind, value, start, end, _) in enumerate(selected):
        wire_start = utf16_length(text[:start])
        wire_end = wire_start + utf16_length(value)
        spans.append(
            ProtectedContentSpan(
                id=f"protected-{index}-{start}",
                kind=kind,
                scope="required",
                text=value,
                start=start,
                end=end,
                range_encoding=RANGE_ENCODING_VERSION,
                source_sha256=source_sha256,
                protected_span_sha256=compute_protected_span_sha256(
                    RANGE_ENCODING_VERSION, source_sha256, wire_start, wire_end, value
                ),
            )
        )
    return tuple(spans)


# ---------------------------------------------------------------------------
# Exact occurrence matching
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[\w]", re.UNICODE)
_DIGIT_RE = re.compile(r"\d")
_LEADING_SYMBOL_RE = re.compile(r"[\u0024\u20ac\u00a3\u00a5%@]")
_NUMERIC_TOKEN_RE = re.compile(r"[\u0024\u20ac\u00a3\u00a5]?\d[\d,]*(?:\.\d+)?%?")


def _is_word_char(char: str) -> bool:
    return bool(char) and bool(_WORD_RE.match(char))


def exact_occurrences(text: str, needle: str) -> tuple[int, ...]:
    """Class-aware exact-token occurrences of ``needle`` inside ``text``.

    Mirrors ``exactOccurrences`` in ``src/lib/safety/protectedContent.ts``: a
    protected payload only counts when it appears as a complete anchored unit,
    so extended or embedded tokens cannot satisfy it.
    """

    if not needle:
        return ()
    positions: list[int] = []
    cursor = 0
    while cursor <= len(text) - len(needle):
        index = text.find(needle, cursor)
        if index < 0:
            break
        if _boundary_allows(text, index, needle):
            positions.append(index)
        cursor = index + 1
    return tuple(positions)


def _boundary_allows(text: str, index: int, needle: str) -> bool:
    first = needle[0]
    last = needle[-1]
    before = text[index - 1] if index > 0 else ""
    after_index = index + len(needle)
    after = text[after_index] if after_index < len(text) else ""
    after_next = text[after_index + 1] if after_index + 1 < len(text) else ""

    starts_wordish = bool(_WORD_RE.match(first)) or bool(_LEADING_SYMBOL_RE.match(first))
    if starts_wordish and before:
        if _is_word_char(before):
            return False
        if _LEADING_SYMBOL_RE.match(first) and _DIGIT_RE.match(before):
            return False

    ends_wordish = bool(_WORD_RE.match(last))
    identifierish = ends_wordish and any(sep in needle for sep in "./:@-")
    numeric_tail = bool(_DIGIT_RE.match(last)) or last == "%"

    if ends_wordish:
        if after and _is_word_char(after):
            return False
        if identifierish and after and after in "/:@-":
            return False
        if identifierish and after == "." and after_next and not after_next.isspace():
            return False
        if after == "-" and after_next and _is_word_char(after_next):
            return False

    if numeric_tail:
        if after and _is_word_char(after):
            return False
        if after and after in ".,:/-" and _DIGIT_RE.match(after_next):
            return False

    return True


def _numeric_token_shapes(text: str) -> set[str]:
    return {
        re.sub(r"\d+", "#", token)
        for token in _NUMERIC_TOKEN_RE.findall(text)
        if token
    }


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def protected_spans_for_evaluation(
    source: str,
    candidate: str,
    *,
    protected: Any = None,
    route: str = "whole",
) -> tuple[dict[str, Any], ...]:
    """Canonical span dictionaries the deterministic gate should evaluate."""

    if route not in PROTECTED_ROUTES:
        raise ValueError(f"unknown protected route: {route}")
    spans = normalize_protected_spans(
        protected if protected is not None else extract_protected_spans(source),
        source_text=source,
    )
    return tuple(
        span.to_dict()
        for span in spans
    )


def _anchor_key(span: ProtectedContentSpan) -> str:
    return f"{span.kind}:{span.text.lower()}"


def _group_key(span: ProtectedContentSpan) -> str:
    value = span.text.lower() if span.kind in ANCHOR_KINDS else span.text
    return f"{span.kind}\x00{value}"


def _is_heading_like(text: str, index: int) -> bool:
    line_start = text.rfind("\n", 0, index) + 1
    prefix = text[line_start:index]
    return bool(re.match(r"^\s*(?:[-*#>]+|\d+[.)])\s*$", prefix))


def _unprotected_introductions(original: str, region: str) -> list[str]:
    original_names = {
        span.text.lower()
        for span in extract_protected_spans(original)
        if span.kind == "name"
    }
    out: list[str] = []
    for span in extract_protected_spans(region):
        if span.kind != "name":
            continue
        if span.text.lower() in original_names:
            continue
        if _is_heading_like(region, span.start or 0):
            continue
        out.append(span.text)
    return out


def _classify_absent(
    span: ProtectedContentSpan,
    region_text: str,
    region_spans: Sequence[ProtectedContentSpan],
    repeated: bool,
) -> str:
    if span.kind in NUMERIC_KINDS:
        shapes = _numeric_token_shapes(span.text)
        if shapes & _numeric_token_shapes(region_text):
            return "protected_altered"
    if span.kind in ANCHOR_KINDS or span.kind in SAME_KIND_ALTERED_KINDS:
        if any(other.kind == span.kind for other in region_spans):
            return "protected_altered"
    if span.kind in SAME_KIND_ALTERED_KINDS and span.text in region_text:
        return "protected_altered"
    if repeated:
        return "protected_repeated_mismatch"
    return "protected_missing"


def _overlapping(
    spans: Sequence[ProtectedContentSpan], start: int, end: int
) -> list[ProtectedContentSpan]:
    return [
        span
        for span in spans
        if span.has_range and span.start is not None and span.end is not None
        and span.start < end
        and span.end > start
    ]


def _failures() -> dict[str, list[str]]:
    return {}


def _record(failures: dict[str, list[str]], failure_class: str, span_id: str) -> None:
    bucket = failures.setdefault(failure_class, [])
    if span_id not in bucket:
        bucket.append(span_id)


def _resolve_failure(failures: Mapping[str, Sequence[str]]) -> tuple[str | None, tuple[str, ...]]:
    for failure_class in FAILURE_PRECEDENCE:
        ids = failures.get(failure_class)
        if ids:
            seen: list[str] = []
            for value in ids:
                if value not in seen:
                    seen.append(value)
            return failure_class, tuple(seen)
    return None, ()


def _finish(
    failures: Mapping[str, Sequence[str]],
    introduced: Sequence[str],
) -> ProtectedEvaluation:
    failure_class, failure_span_ids = _resolve_failure(failures)
    unique_introduced: list[str] = []
    for value in introduced:
        if value not in unique_introduced:
            unique_introduced.append(value)
    return ProtectedEvaluation(
        contract_version=PROTECTED_CONTENT_CONTRACT_VERSION,
        safe=failure_class is None,
        failure_class=failure_class,
        failure_span_ids=failure_span_ids,
        missing_span_ids=tuple(failures.get("protected_missing", ())),
        altered_span_ids=tuple(failures.get("protected_altered", ())),
        repeated_mismatch_span_ids=tuple(
            failures.get("protected_repeated_mismatch", ())
        ),
        position_drift_span_ids=tuple(failures.get("protected_position_drift", ())),
        introduced_span_ids=tuple(failures.get("protected_introduced", ())),
        introduced=tuple(unique_introduced),
    )


def _identity_failure(
    source: str,
    spans: Sequence[ProtectedContentSpan],
    *,
    source_sha256: str | None,
    selection: tuple[int, int] | None,
    selection_sha256: str | None,
) -> ProtectedContentSpan | None:
    digest = compute_source_sha256(source)
    if source_sha256 is not None and source_sha256 != digest:
        return spans[0] if spans else None
    for span in spans:
        if not span.has_range:
            continue
        assert span.start is not None and span.end is not None
        if source[span.start : span.end] != span.text:
            return span
        if span.range_encoding != RANGE_ENCODING_VERSION:
            return span
        if span.source_sha256 is not None and span.source_sha256 != digest:
            return span
        if span.protected_span_sha256 is not None:
            wire_start = utf16_length(source[: span.start])
            wire_end = wire_start + utf16_length(span.text)
            expected = compute_protected_span_sha256(
                span.range_encoding, digest, wire_start, wire_end, span.text
            )
            if span.protected_span_sha256 != expected:
                return span
    if selection is not None and selection_sha256 is not None:
        selected = source[selection[0] : selection[1]]
        expected = compute_selection_sha256(
            RANGE_ENCODING_VERSION, digest, selection[0], selection[1], selected
        )
        if expected != selection_sha256:
            return spans[0] if spans else None
    return None


def _evaluate_whole(
    source: str,
    candidate: str,
    spans: Sequence[ProtectedContentSpan],
    anchor_policy: str,
) -> ProtectedEvaluation:
    failures = _failures()
    introduced: list[str] = []
    candidate_spans = extract_protected_spans(candidate)

    groups: dict[str, list[ProtectedContentSpan]] = {}
    for span in spans:
        groups.setdefault(_group_key(span), []).append(span)

    for group in groups.values():
        first = group[0]
        expected = len(group)
        actual = len(exact_occurrences(candidate, first.text))
        if actual < expected:
            if actual > 0:
                failure_class = "protected_repeated_mismatch"
            else:
                failure_class = _classify_absent(
                    first, candidate, candidate_spans, expected > 1
                )
            for span in group:
                _record(failures, failure_class, span.id)
            continue
        if actual > expected:
            for span in group:
                _record(failures, "protected_introduced", span.id)
            introduced.append(first.text)

    if anchor_policy == "exact":
        source_anchors = {
            _anchor_key(span) for span in spans if span.kind in ANCHOR_KINDS
        }
        source_by_kind: dict[str, list[ProtectedContentSpan]] = {}
        for span in spans:
            if span.kind in ANCHOR_KINDS:
                source_by_kind.setdefault(span.kind, []).append(span)
        for span in candidate_spans:
            if span.kind not in ANCHOR_KINDS:
                continue
            if _anchor_key(span) in source_anchors:
                continue
            same_kind = source_by_kind.get(span.kind)
            span_id = (
                same_kind[0].id
                if same_kind
                else f"introduced-{span.kind}:{span.text.lower()}"
            )
            _record(failures, "protected_introduced", span_id)
            introduced.append(span.text)

    for name in _unprotected_introductions(source, candidate):
        _record(failures, "protected_introduced", f"introduced-name:{name}")
        introduced.append(name)

    return _finish(failures, introduced)


def _evaluate_local(
    source: str,
    candidate: str,
    spans: Sequence[ProtectedContentSpan],
    *,
    anchor_policy: str,
    selection: tuple[int, int] | None,
    candidate_range: tuple[int, int] | None,
    candidate_document: str | None,
) -> ProtectedEvaluation:
    if selection is None:
        return ProtectedEvaluation(
            contract_version=PROTECTED_CONTENT_CONTRACT_VERSION,
            safe=False,
            failure_class="identity_mismatch",
            failure_span_ids=tuple(span.id for span in spans),
            missing_span_ids=(),
            altered_span_ids=(),
            repeated_mismatch_span_ids=(),
            position_drift_span_ids=(),
            introduced_span_ids=(),
            introduced=(),
        )

    document = candidate_document if candidate_document is not None else candidate
    if candidate_range is None:
        candidate_range = (0, len(document))
    start, end = candidate_range
    if start < 0 or end <= start or end > len(document):
        return ProtectedEvaluation(
            contract_version=PROTECTED_CONTENT_CONTRACT_VERSION,
            safe=False,
            failure_class="identity_mismatch",
            failure_span_ids=tuple(span.id for span in spans),
            missing_span_ids=(),
            altered_span_ids=(),
            repeated_mismatch_span_ids=(),
            position_drift_span_ids=(),
            introduced_span_ids=(),
            introduced=(),
        )

    region_text = document[start:end]
    region_spans = extract_protected_spans(region_text)
    failures = _failures()
    introduced: list[str] = []

    inside = _overlapping(spans, selection[0], selection[1])
    inside_ids = {span.id for span in inside}
    outside = [span for span in spans if span.id not in inside_ids]

    consumed: set[int] = set()
    previous_source_end = -1
    previous_region_index = -1

    for span in inside:
        positions = exact_occurrences(region_text, span.text)
        ordered = [position for position in positions if position >= previous_region_index]
        next_index = ordered[0] if ordered else (positions[0] if positions else -1)
        if not positions:
            if exact_occurrences(document, span.text):
                _record(failures, "protected_position_drift", span.id)
            else:
                repeated = bool(span.end is not None and span.end <= previous_source_end)
                _record(
                    failures,
                    _classify_absent(span, region_text, region_spans, repeated),
                    span.id,
                )
            continue
        if span.candidate_start is not None and span.candidate_end is not None:
            bound_start = span.candidate_start - start
            bound_end = span.candidate_end - start
            if (
                bound_start < 0
                or bound_end > len(region_text)
                or region_text[bound_start:bound_end] != span.text
            ):
                _record(failures, "protected_position_drift", span.id)
                continue
        if not ordered and len(positions) == 1 and previous_region_index >= 0:
            _record(failures, "protected_position_drift", span.id)
            continue
        previous_source_end = max(previous_source_end, span.end or 0)
        previous_region_index = next_index + len(span.text)
        consumed.add(next_index)

    for span in outside:
        if exact_occurrences(region_text, span.text):
            _record(failures, "protected_introduced", span.id)
            introduced.append(span.text)

    source_anchors = {_anchor_key(span) for span in spans if span.kind in ANCHOR_KINDS}
    source_names = {
        span.text.lower() for span in spans if span.kind == "name"
    }
    for span in region_spans:
        offset = span.start or 0
        if offset in consumed:
            continue
        if span.kind in ANCHOR_KINDS:
            if anchor_policy != "exact" or _anchor_key(span) in source_anchors:
                continue
            _record(failures, "protected_introduced", span.id)
            introduced.append(span.text)
            continue
        if span.kind == "name" and span.text.lower() not in source_names:
            if _is_heading_like(region_text, offset):
                continue
            _record(failures, "protected_introduced", span.id)
            introduced.append(span.text)

    return _finish(failures, introduced)


def evaluate_protected_content(
    source: str,
    candidate: str,
    *,
    protected: Any = None,
    route: str = "whole",
    anchor_policy: str | None = None,
    selection: tuple[int, int] | None = None,
    selection_sha256: str | None = None,
    candidate_range: tuple[int, int] | None = None,
    candidate_document: str | None = None,
    source_sha256: str | None = None,
    strict_identity: bool = False,
) -> ProtectedEvaluation:
    """Evaluate ``candidate`` against the shared protected-content contract."""

    if route not in PROTECTED_ROUTES:
        raise ValueError(f"unknown protected route: {route}")
    policy = anchor_policy or ("exact" if route == "local" else "minimum")
    if policy not in ANCHOR_POLICIES:
        raise ValueError(f"unknown anchor policy: {policy}")

    spans = normalize_protected_spans(
        protected if protected is not None else extract_protected_spans(source),
        source_text=source,
        source_sha256=source_sha256,
        strict=strict_identity,
    )

    identity = _identity_failure(
        source,
        spans,
        source_sha256=source_sha256,
        selection=selection,
        selection_sha256=selection_sha256,
    )
    if identity is not None:
        return ProtectedEvaluation(
            contract_version=PROTECTED_CONTENT_CONTRACT_VERSION,
            safe=False,
            failure_class="identity_mismatch",
            failure_span_ids=(identity.id,),
            missing_span_ids=(),
            altered_span_ids=(),
            repeated_mismatch_span_ids=(),
            position_drift_span_ids=(),
            introduced_span_ids=(),
            introduced=(),
        )

    if route == "local":
        return _evaluate_local(
            source,
            candidate,
            spans,
            anchor_policy=policy,
            selection=selection,
            candidate_range=candidate_range,
            candidate_document=candidate_document,
        )
    return _evaluate_whole(source, candidate, spans, policy)


__all__ = [
    "ANCHOR_POLICIES",
    "ANCHOR_KINDS",
    "CONTAINER_KINDS",
    "FAILURE_PRECEDENCE",
    "IDENTITY_ERROR_CODES",
    "IDENTITY_PREIMAGE_SEPARATOR",
    "NUMERIC_KINDS",
    "PROTECTED_CONTENT_CONTRACT_VERSION",
    "PROTECTED_ROUTES",
    "PROTECTED_SPAN_KINDS",
    "PROTECTED_SPAN_SCOPES",
    "ProtectedContentError",
    "ProtectedContentSpan",
    "ProtectedEvaluation",
    "compute_protected_span_sha256",
    "compute_range_sha256",
    "compute_selection_sha256",
    "compute_source_sha256",
    "evaluate_protected_content",
    "exact_occurrences",
    "extract_protected_spans",
    "normalize_protected_spans",
    "protected_spans_for_evaluation",
    "span_from_wire",
    "utf16_length",
]
