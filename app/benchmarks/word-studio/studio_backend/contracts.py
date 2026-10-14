#!/usr/bin/env python3
"""Stable request/response contracts for the future Pari Word Studio backend."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping
import re
import uuid

from .range_encoding import (
    RANGE_ENCODING_VERSION,
    REQUEST_CONTRACT_VERSION,
    code_point_to_utf16,
    protected_span_identity_sha256,
    selection_identity_sha256,
    source_identity_sha256,
)
from .errors import ServiceRequestError
from .protected_content import (
    PROTECTED_SPAN_KINDS,
    PROTECTED_SPAN_SCOPES,
    ProtectedContentError,
    span_from_wire,
)


class Operation(str, Enum):
    REWRITE = "rewrite"
    REPLACE = "replace"
    SHORTEN = "shorten"
    EXPAND = "expand"
    COMPRESS_GIST = "compress_gist"
    SPLIT = "split"
    JOIN = "join"
    SIMPLIFY = "simplify"
    DIFFERENT_STRUCTURE = "different_structure"
    PRESERVE_REGISTER = "preserve_register"


class SemanticMode(str, Enum):
    FULL_PRESERVATION = "full_preservation"
    INTENTIONAL_COMPRESSION = "intentional_compression"
    CONTROLLED_EXPANSION = "controlled_expansion"


class CandidateLane(str, Enum):
    FAST = "fast"
    DIVERSITY = "diversity"


@dataclass(frozen=True)
class TextRange:
    start: int
    end: int

    def validate(self, text: str) -> None:
        if self.start < 0 or self.end <= self.start or self.end > len(text):
            raise ValueError(f"invalid selection range {self.start}:{self.end} for text length {len(text)}")


@dataclass(frozen=True)
class ProtectedSpan:
    """One protected span in code-point index space.

    Issue #51 froze the versioned protected-content contract, so a span carries
    the contract's ``id``/``kind``/``scope`` alongside its exact text and its
    code-point ``start``/``end``. ``kind`` defaults to the contract's own
    coercion default (``"code"``) and ``scope`` to ``"required"`` so a span
    constructed without them encodes and decodes identically.
    """

    text: str
    start: int | None = None
    end: int | None = None
    id: str | None = None
    kind: str = "code"
    scope: str = "required"

    @property
    def wire_id(self) -> str:
        """Stable id for this span, derived when the caller supplied none."""
        return self.id or protected_span_id(self.text, self.start, self.end)

    @property
    def is_required(self) -> bool:
        return self.scope == "required"

    def to_wire(self) -> dict[str, Any]:
        """The identity-carrying part of the span, without wire offsets."""
        return {
            "id": self.wire_id,
            "kind": self.kind,
            "scope": self.scope,
            "text": self.text,
        }


def protected_span_id(text: str, start: int | None, end: int | None) -> str:
    """Deterministic span id used when a caller does not supply one.

    Coordinate-bearing spans are named by position, and text-only spans by a
    digest of their exact text, so two spans with the same text at different
    positions stay distinct and one round trip is byte-stable.
    """
    if start is not None and end is not None:
        return f"span-{start}-{end}"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"text-{digest}"


_PROTECTED_FIELD_BY_CODE = {
    "invalid_span_range": "range",
    "span_text_mismatch": "text",
    "stale_span_identity": "protectedSpanSha256",
    "stale_document_identity": "sourceSha256",
    "stale_selection_identity": "selectionSha256",
    "unsupported_range_encoding": "rangeEncoding",
}


def protected_span_from_wire(
    document_text: str,
    payload: Mapping[str, Any],
    *,
    source_sha256: str,
    range_encoding: str = RANGE_ENCODING_VERSION,
    index: int = 0,
    field_prefix: str = "protectedSpans",
) -> ProtectedSpan:
    """Validate one wire protected-span payload through the #51 contract.

    The #51 module owns span identity, range conversion, and ``id``/``kind``/
    ``scope`` coercion; this adapter only re-raises its fail-closed codes as the
    service's field-addressable :class:`ServiceRequestError` so a client can see
    exactly which span field was rejected.
    """
    declared_encoding = payload.get("rangeEncoding")
    if declared_encoding is not None and declared_encoding != range_encoding:
        raise ServiceRequestError(f"{field_prefix}[{index}].rangeEncoding")
    wire: dict[str, Any] = {
        "text": payload.get("text"),
        "start": payload.get("start"),
        "end": payload.get("end"),
        "rangeEncoding": range_encoding,
        "sourceSha256": source_sha256,
    }
    for key in ("id", "kind", "scope", "protectedSpanSha256"):
        value = payload.get(key)
        if value is not None:
            wire[key] = value
    try:
        span = span_from_wire(document_text, wire, source_sha256=source_sha256, index=index)
    except ProtectedContentError as exc:
        suffix = _PROTECTED_FIELD_BY_CODE.get(exc.code, "protectedSpanSha256")
        raise ServiceRequestError(f"{field_prefix}[{index}].{suffix}") from exc
    return ProtectedSpan(
        text=span.text,
        start=span.start,
        end=span.end,
        id=span.id,
        kind=span.kind,
        scope=span.scope,
    )


@dataclass(frozen=True)
class StudioRequest:
    document_text: str
    selection: TextRange
    operation: Operation
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    strength: int = 60
    requested_candidates: int = 40
    target_min_words: int | None = None
    target_max_words: int | None = None
    protected_spans: tuple[ProtectedSpan, ...] = ()
    context_before_chars: int = 900
    context_after_chars: int = 900
    document_revision: str | None = None

    @property
    def selected_text(self) -> str:
        return self.document_text[self.selection.start : self.selection.end]

    def validate(self) -> None:
        if not self.document_text.strip():
            raise ValueError("document_text must not be empty")
        self.selection.validate(self.document_text)
        if not self.selected_text.strip():
            raise ValueError("selected text must not be whitespace")
        if not 0 <= self.strength <= 100:
            raise ValueError("strength must be in [0,100]")
        if not 1 <= self.requested_candidates <= 40:
            raise ValueError("requested_candidates must be in [1,40]")
        if self.target_min_words is not None and self.target_min_words < 1:
            raise ValueError("target_min_words must be >=1")
        if self.target_max_words is not None and self.target_max_words < 1:
            raise ValueError("target_max_words must be >=1")
        if self.target_min_words is not None and self.target_max_words is not None and self.target_min_words > self.target_max_words:
            raise ValueError("target_min_words cannot exceed target_max_words")
        if self.context_before_chars < 0 or self.context_after_chars < 0:
            raise ValueError("context windows must be non-negative")


@dataclass(frozen=True)
class Candidate:
    text: str
    lane: CandidateLane
    family: str
    generation_index: int
    model_id: str | None = None
    raw_score: float | None = None
    runtime_id: str | None = None


@dataclass(frozen=True)
class CandidateBatch:
    request_id: str
    sequence: int
    candidates: tuple[Candidate, ...]
    cumulative_unique_count: int
    final: bool
    cancelled: bool = False
    cancel_reason: str | None = None
    diagnostics: tuple[dict[str, Any], ...] = ()
    errors: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class LanePlan:
    lane: CandidateLane
    candidate_budget: int
    max_new_tokens: int
    families: tuple[str, ...]
    temperature: float
    top_p: float


@dataclass(frozen=True)
class ExecutionPlan:
    request_id: str
    semantic_mode: SemanticMode
    fast: LanePlan
    diversity: LanePlan | None
    progressive_thresholds: tuple[int, ...]


_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_MONEY_RE = re.compile(r"(?<!\w)\$\d+(?:,\d{3})*(?:\.\d{2})?")
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\s?(?:AM|PM|a\.m\.|p\.m\.)?\b", re.I)
_FILENAME_RE = re.compile(r"\b[\w.-]+\.(?:pdf|docx?|xlsx?|pptx?|txt|csv|json|md)\b", re.I)
_QUOTE_RE = re.compile(r"[“\"]([^”\"]+)[”\"]")
_DETECTED_SPAN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", _EMAIL_RE),
    ("currency", _MONEY_RE),
    ("time", _TIME_RE),
    ("code", _FILENAME_RE),
    ("quote", _QUOTE_RE),
)


def detect_protected_spans(text: str) -> tuple[ProtectedSpan, ...]:
    """Cheap deterministic baseline; product safety can add richer extractors later."""
    matches: list[ProtectedSpan] = []
    for kind, pattern in _DETECTED_SPAN_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(0)
            matches.append(
                ProtectedSpan(
                    value,
                    match.start(),
                    match.end(),
                    id=f"span-{match.start()}-{match.end()}",
                    kind=kind,
                )
            )
    seen: set[tuple[int | None, int | None, str]] = set()
    out: list[ProtectedSpan] = []
    for item in sorted(matches, key=lambda x: (x.start if x.start is not None else -1, -len(x.text))):
        key = (item.start, item.end, item.text)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return tuple(out)


def _codepoint_to_utf16(text: str, index: int) -> int:
    return code_point_to_utf16(text, index, field="documentText")


def to_wire_request(request: StudioRequest) -> dict[str, Any]:
    """Encode ``request`` into the ``pari-studio-request-v2`` wire shape.

    Every emitted range is a UTF-16 code-unit offset and every identity digest
    comes from :mod:`studio_backend.range_encoding`, so the encoder and the
    client derive identical values from identical source bytes. The legacy flat
    ``sourceHash``/``documentHash``/``selectionHash`` spellings are not emitted:
    the source digest is nested under ``sourceIdentity`` and the selection and
    protected-span digests bind the source bytes, the encoding, the offsets,
    and the exact text together.
    """
    request.validate()
    document_text = request.document_text
    selected_text = request.selected_text
    document_sha256 = source_identity_sha256(document_text, field="documentText")
    selection_start = _codepoint_to_utf16(document_text, request.selection.start)
    selection_end = _codepoint_to_utf16(document_text, request.selection.end)
    protected = []
    for span in request.protected_spans:
        identity = span.to_wire()
        if span.start is None or span.end is None:
            # A text-only span declares no position, so there is no offset pair
            # for an identity digest to bind. Emit a deterministic null rather
            # than a digest that would imply a location the client never sent.
            protected.append(
                {
                    **identity,
                    "start": None,
                    "end": None,
                    "protectedSpanSha256": None,
                }
            )
            continue
        span_start = _codepoint_to_utf16(document_text, span.start)
        span_end = _codepoint_to_utf16(document_text, span.end)
        protected.append(
            {
                **identity,
                "start": span_start,
                "end": span_end,
                "protectedSpanSha256": protected_span_identity_sha256(
                    source_sha256=document_sha256,
                    range_encoding=RANGE_ENCODING_VERSION,
                    wire_start=span_start,
                    wire_end=span_end,
                    span_text=span.text,
                ),
            }
        )
    return {
        "contractVersion": REQUEST_CONTRACT_VERSION,
        "rangeEncoding": RANGE_ENCODING_VERSION,
        "requestId": request.request_id,
        "sourceIdentity": {
            "contractVersion": REQUEST_CONTRACT_VERSION,
            "rangeEncoding": RANGE_ENCODING_VERSION,
            "documentSha256": document_sha256,
            "documentRevision": request.document_revision,
        },
        "documentText": document_text,
        "selection": {
            "start": selection_start,
            "end": selection_end,
        },
        "selectedText": selected_text,
        "selectionSha256": selection_identity_sha256(
            source_sha256=document_sha256,
            range_encoding=RANGE_ENCODING_VERSION,
            wire_start=selection_start,
            wire_end=selection_end,
            selected_text=selected_text,
        ),
        "operation": request.operation.value,
        "strength": request.strength,
        "requestedCandidates": request.requested_candidates,
        "targetMinWords": request.target_min_words,
        "targetMaxWords": request.target_max_words,
        "protectedSpans": protected,
    }
