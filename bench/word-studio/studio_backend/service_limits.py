#!/usr/bin/env python3
"""Wire, identity, and request-size limits for the outer Studio service."""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from .contracts import (
    Operation,
    PROTECTED_SPAN_KINDS,
    PROTECTED_SPAN_SCOPES,
    ProtectedSpan,
    StudioRequest,
    TextRange,
    protected_span_from_wire,
)
from .errors import ServiceLimitError, ServiceRequestError
from .range_encoding import (
    REQUEST_CONTRACT_VERSION,
    parse_source_identity,
    require_sha256_hex,
    require_supported_range_encoding,
    require_wire_offset,
    selection_identity_sha256,
    source_identity_sha256,
    utf16_range_to_slice,
)


_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_LEGACY_IDENTITY_FIELDS = (
    "sourceHash",
    "documentHash",
    "selectionHash",
)


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be in [{minimum},{maximum}]")
    return value


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be in [{minimum},{maximum}]")
    return value


@dataclass(frozen=True)
class ServiceLimits:
    max_body_bytes: int = 2 * 1024 * 1024
    max_document_chars: int = 500_000
    max_document_bytes: int = 1024 * 1024
    max_request_id_chars: int = 128
    max_revision_chars: int = 128
    max_protected_spans: int = 512
    max_protected_span_text_chars: int = 2_000
    max_protected_metadata_bytes: int = 256 * 1024
    max_target_words: int = 100_000
    max_requested_candidates: int = 40
    max_context_window_chars: int = 50_000
    max_queued_requests: int = 8
    max_sse_event_bytes: int = 256 * 1024
    max_sse_events: int = 128
    max_sse_queue: int = 8
    max_concurrent_requests: int = 2
    max_sse_connections: int = 2
    queue_wait_seconds: float = 10.0
    cancel_timeout_seconds: float = 5.0
    heartbeat_seconds: float = 10.0
    request_timeout_seconds: float = 180.0
    telemetry_entries: int = 256
    telemetry_ttl_seconds: float = 900.0
    observation_entries: int = 256
    observation_ttl_seconds: float = 900.0

    @classmethod
    def from_env(cls) -> "ServiceLimits":
        return cls(
            max_body_bytes=_env_int(
                "PARI_STUDIO_MAX_BODY_BYTES", cls.max_body_bytes, minimum=16_384, maximum=16 * 1024 * 1024
            ),
            max_document_chars=_env_int(
                "PARI_STUDIO_MAX_DOCUMENT_CHARS",
                cls.max_document_chars,
                minimum=1_000,
                maximum=5_000_000,
            ),
            max_document_bytes=_env_int(
                "PARI_STUDIO_MAX_DOCUMENT_BYTES",
                cls.max_document_bytes,
                minimum=4_096,
                maximum=16 * 1024 * 1024,
            ),
            max_revision_chars=_env_int(
                "PARI_STUDIO_MAX_REVISION_CHARS",
                cls.max_revision_chars,
                minimum=1,
                maximum=1_024,
            ),
            max_protected_spans=_env_int(
                "PARI_STUDIO_MAX_PROTECTED_SPANS", cls.max_protected_spans, minimum=1, maximum=100_000
            ),
            max_protected_span_text_chars=_env_int(
                "PARI_STUDIO_MAX_PROTECTED_SPAN_TEXT_CHARS",
                cls.max_protected_span_text_chars,
                minimum=16,
                maximum=100_000,
            ),
            max_protected_metadata_bytes=_env_int(
                "PARI_STUDIO_MAX_PROTECTED_METADATA_BYTES",
                cls.max_protected_metadata_bytes,
                minimum=1_024,
                maximum=8 * 1024 * 1024,
            ),
            max_target_words=_env_int(
                "PARI_STUDIO_MAX_TARGET_WORDS", cls.max_target_words, minimum=1, maximum=1_000_000
            ),
            max_context_window_chars=_env_int(
                "PARI_STUDIO_MAX_CONTEXT_WINDOW_CHARS",
                cls.max_context_window_chars,
                minimum=0,
                maximum=1_000_000,
            ),
            max_queued_requests=_env_int(
                "PARI_STUDIO_MAX_QUEUED_REQUESTS",
                cls.max_queued_requests,
                minimum=1,
                maximum=256,
            ),
            max_sse_event_bytes=_env_int(
                "PARI_STUDIO_MAX_SSE_EVENT_BYTES",
                cls.max_sse_event_bytes,
                minimum=16_384,
                maximum=4 * 1024 * 1024,
            ),
            max_sse_events=_env_int(
                "PARI_STUDIO_MAX_SSE_EVENTS", cls.max_sse_events, minimum=8, maximum=1_024
            ),
            max_sse_queue=_env_int(
                "PARI_STUDIO_MAX_SSE_QUEUE", cls.max_sse_queue, minimum=1, maximum=128
            ),
            max_concurrent_requests=_env_int(
                "PARI_STUDIO_MAX_CONCURRENT_REQUESTS",
                cls.max_concurrent_requests,
                minimum=1,
                maximum=64,
            ),
            max_sse_connections=_env_int(
                "PARI_STUDIO_MAX_SSE_CONNECTIONS",
                cls.max_sse_connections,
                minimum=1,
                maximum=64,
            ),
            queue_wait_seconds=_env_float(
                "PARI_STUDIO_QUEUE_WAIT_SECONDS", cls.queue_wait_seconds, minimum=0.05, maximum=300.0
            ),
            cancel_timeout_seconds=_env_float(
                "PARI_STUDIO_CANCEL_TIMEOUT_SECONDS",
                cls.cancel_timeout_seconds,
                minimum=0.05,
                maximum=120.0,
            ),
            heartbeat_seconds=_env_float(
                "PARI_STUDIO_HEARTBEAT_SECONDS", cls.heartbeat_seconds, minimum=0.1, maximum=300.0
            ),
            request_timeout_seconds=_env_float(
                "PARI_STUDIO_REQUEST_TIMEOUT_SECONDS",
                cls.request_timeout_seconds,
                minimum=1.0,
                maximum=3_600.0,
            ),
            telemetry_entries=_env_int(
                "PARI_STUDIO_TELEMETRY_ENTRIES", cls.telemetry_entries, minimum=8, maximum=100_000
            ),
            telemetry_ttl_seconds=_env_float(
                "PARI_STUDIO_TELEMETRY_TTL_SECONDS",
                cls.telemetry_ttl_seconds,
                minimum=1.0,
                maximum=86_400.0,
            ),
            observation_entries=_env_int(
                "PARI_STUDIO_OBSERVATION_ENTRIES",
                cls.observation_entries,
                minimum=8,
                maximum=100_000,
            ),
            observation_ttl_seconds=_env_float(
                "PARI_STUDIO_OBSERVATION_TTL_SECONDS",
                cls.observation_ttl_seconds,
                minimum=1.0,
                maximum=86_400.0,
            ),
        )


@dataclass(frozen=True)
class RequestIdentity:
    request_id: str
    document_revision: str | None
    source_sha256: str
    selection_sha256: str
    selection_start: int
    selection_end: int
    selected_text: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "requestId": self.request_id,
            "documentRevision": self.document_revision,
            "sourceSha256": self.source_sha256,
            "selectionSha256": self.selection_sha256,
            "selection": {"start": self.selection_start, "end": self.selection_end},
        }


@dataclass(frozen=True)
class ParsedStudioRequest:
    request: StudioRequest
    identity: RequestIdentity


_VALIDATION_FIELD_BY_MESSAGE_PREFIX = (
    ("document_text", "documentText"),
    ("selected text", "selection"),
    ("selection range", "selection"),
    ("strength", "strength"),
    ("requested_candidates", "requestedCandidates"),
    ("target_min_words", "targetMinWords"),
    ("target_max_words", "targetMaxWords"),
    ("context windows", "contextWindow"),
)


def _validation_field(exc: ValueError) -> str:
    """Map a contracts validation message to the wire field that caused it."""
    message = str(exc)
    for prefix, field in _VALIDATION_FIELD_BY_MESSAGE_PREFIX:
        if message.startswith(prefix) or f" {prefix}" in message:
            return field
    return "request"


def _require_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ServiceRequestError(field)
    return value


def _optional_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, field)


def _optional_limited_int(value: Any, field: str, *, maximum: int) -> int | None:
    parsed = _optional_int(value, field)
    if parsed is None:
        return None
    if parsed < 1 or parsed > maximum:
        raise ServiceLimitError(field, maximum)
    return parsed


def sha256_text(value: str) -> str:
    """Compatibility wrapper around the #50 exact-UTF-8 source digest."""
    return source_identity_sha256(value)


def studio_request_from_wire(
    body: Mapping[str, Any],
    limits: ServiceLimits,
) -> ParsedStudioRequest:
    if not isinstance(body, Mapping):
        raise ServiceRequestError("body")

    contract_version = body.get("contractVersion")
    if contract_version is None:
        raise ServiceRequestError("contractVersion")
    if contract_version != REQUEST_CONTRACT_VERSION:
        raise ServiceRequestError("contractVersion")

    range_encoding = require_supported_range_encoding(body.get("rangeEncoding"))
    source_identity = body.get("sourceIdentity")
    if not isinstance(source_identity, Mapping):
        raise ServiceRequestError("sourceIdentity")
    if source_identity.get("contractVersion") != REQUEST_CONTRACT_VERSION:
        raise ServiceRequestError("sourceIdentity.contractVersion")
    if require_supported_range_encoding(
        source_identity.get("rangeEncoding"), field="sourceIdentity.rangeEncoding"
    ) != range_encoding:
        raise ServiceRequestError("sourceIdentity.rangeEncoding")
    for legacy_field in _LEGACY_IDENTITY_FIELDS:
        if legacy_field in body:
            raise ServiceRequestError(legacy_field)

    request_id_value = body.get("requestId")
    if request_id_value is None or request_id_value == "":
        request_id = uuid.uuid4().hex
    else:
        if not isinstance(request_id_value, str):
            raise ServiceRequestError("requestId")
        request_id = request_id_value.strip()
        if len(request_id) > limits.max_request_id_chars:
            raise ServiceLimitError("requestId", limits.max_request_id_chars)
        if not _SAFE_ID.fullmatch(request_id):
            raise ServiceRequestError("requestId")

    declared_source_sha256, revision_value = parse_source_identity(body)
    document_revision: str | None = None
    if revision_value is not None:
        document_revision = revision_value.strip() or None
        if document_revision:
            if len(document_revision) > limits.max_revision_chars:
                raise ServiceLimitError(
                    "sourceIdentity.documentRevision", limits.max_revision_chars
                )
            if not _SAFE_ID.fullmatch(document_revision):
                raise ServiceRequestError("sourceIdentity.documentRevision")

    document_value = body.get("documentText")
    if not isinstance(document_value, str):
        raise ServiceRequestError("documentText")
    if len(document_value) > limits.max_document_chars:
        raise ServiceLimitError("documentText", limits.max_document_chars)
    document_bytes = len(document_value.encode("utf-8"))
    if document_bytes > limits.max_document_bytes:
        raise ServiceLimitError("documentText", limits.max_document_bytes)
    source_sha256 = source_identity_sha256(
        document_value, field="sourceIdentity.documentSha256"
    )
    if declared_source_sha256 != source_sha256:
        raise ServiceRequestError("sourceIdentity.documentSha256")

    selection_value = body.get("selection")
    if not isinstance(selection_value, Mapping):
        raise ServiceRequestError("selection")
    start = require_wire_offset(selection_value.get("start"), field="selection.start")
    end = require_wire_offset(selection_value.get("end"), field="selection.end")
    # Wire offsets are UTF-16 code units (AppKit NSRange). Convert them to
    # Python string indices without normalizing the source, then cross-check the
    # exact declared selectedText below.
    codepoint_start, codepoint_end = utf16_range_to_slice(
        document_value, start, end, field="selection"
    )
    selection = TextRange(codepoint_start, codepoint_end)

    operation_value = body.get("operation") or "replace"
    try:
        operation = Operation(str(operation_value))
    except ValueError as exc:
        raise ServiceRequestError("operation") from exc

    strength = _require_int(body.get("strength", 60), "strength")
    requested_candidates = _require_int(
        body.get("requestedCandidates", limits.max_requested_candidates),
        "requestedCandidates",
    )
    if requested_candidates > limits.max_requested_candidates:
        raise ServiceLimitError(
            "requestedCandidates", limits.max_requested_candidates
        )

    target_min_words = _optional_limited_int(
        body.get("targetMinWords"),
        "targetMinWords",
        maximum=limits.max_target_words,
    )
    target_max_words = _optional_limited_int(
        body.get("targetMaxWords"),
        "targetMaxWords",
        maximum=limits.max_target_words,
    )

    context_before_chars = _require_int(body.get("contextBeforeChars", 900), "contextBeforeChars")
    context_after_chars = _require_int(body.get("contextAfterChars", 900), "contextAfterChars")
    if (
        context_before_chars < 0
        or context_after_chars < 0
        or context_before_chars > limits.max_context_window_chars
        or context_after_chars > limits.max_context_window_chars
    ):
        if (
            context_before_chars > limits.max_context_window_chars
            or context_after_chars > limits.max_context_window_chars
        ):
            raise ServiceLimitError("contextWindow", limits.max_context_window_chars)
        raise ServiceRequestError("contextWindow")

    protected_value = body.get("protectedSpans") or []
    if not isinstance(protected_value, list):
        raise ServiceRequestError("protectedSpans")
    if len(protected_value) > limits.max_protected_spans:
        raise ServiceLimitError("protectedSpans", limits.max_protected_spans)

    protected_metadata_bytes = 0
    protected: list[ProtectedSpan] = []
    for index, row in enumerate(protected_value):
        if not isinstance(row, Mapping):
            raise ServiceRequestError(f"protectedSpans[{index}]")
        text_value = row.get("text")
        if not isinstance(text_value, str) or not text_value:
            raise ServiceRequestError(f"protectedSpans[{index}].text")
        if len(text_value) > limits.max_protected_span_text_chars:
            raise ServiceLimitError(
                f"protectedSpans[{index}].text",
                limits.max_protected_span_text_chars,
            )
        declared_span_sha256 = row.get("protectedSpanSha256")
        start_value = row.get("start")
        end_value = row.get("end")
        coordinate_free = start_value is None and end_value is None
        if coordinate_free and declared_span_sha256 is not None:
            # A text-only span has no coordinate identity to bind, so the
            # encoder emits a deterministic null rather than a digest over
            # placeholder offsets.
            raise ServiceRequestError(f"protectedSpans[{index}].protectedSpanSha256")
        kind_value = row.get("kind")
        if kind_value is not None and kind_value not in PROTECTED_SPAN_KINDS:
            raise ServiceRequestError(f"protectedSpans[{index}].kind")
        scope_value = row.get("scope")
        if scope_value is not None and scope_value not in PROTECTED_SPAN_SCOPES:
            raise ServiceRequestError(f"protectedSpans[{index}].scope")
        span = protected_span_from_wire(
            document_value,
            row,
            source_sha256=source_sha256,
            range_encoding=range_encoding,
            index=index,
        )
        protected.append(span)
        protected_metadata_bytes += len(text_value.encode("utf-8"))
        if protected_metadata_bytes > limits.max_protected_metadata_bytes:
            raise ServiceLimitError(
                "protectedSpans",
                limits.max_protected_metadata_bytes,
            )

    request = StudioRequest(
        document_text=document_value,
        selection=selection,
        operation=operation,
        request_id=request_id,
        strength=strength,
        requested_candidates=requested_candidates,
        target_min_words=target_min_words,
        target_max_words=target_max_words,
        protected_spans=tuple(protected),
        context_before_chars=context_before_chars,
        context_after_chars=context_after_chars,
        document_revision=document_revision,
    )
    try:
        request.validate()
    except ValueError as exc:
        raise ServiceRequestError(_validation_field(exc)) from exc

    selected_text = request.selected_text
    declared_selected = body.get("selectedText")
    if declared_selected is None:
        raise ServiceRequestError("selectedText")
    if not isinstance(declared_selected, str):
        raise ServiceRequestError("selectedText")
    if declared_selected != selected_text:
        raise ServiceRequestError("selectedText")
    selection_sha256 = selection_identity_sha256(
        source_sha256=source_sha256,
        range_encoding=range_encoding,
        wire_start=start,
        wire_end=end,
        selected_text=selected_text,
    )
    declared_selection_sha256 = body.get("selectionSha256")
    if declared_selection_sha256 is None:
        raise ServiceRequestError("selectionSha256")
    if (
        require_sha256_hex(declared_selection_sha256, field="selectionSha256")
        != selection_sha256
    ):
        raise ServiceRequestError("selectionSha256")

    identity = RequestIdentity(
        request_id=request_id,
        document_revision=document_revision,
        source_sha256=source_sha256,
        selection_sha256=selection_sha256,
        selection_start=selection.start,
        selection_end=selection.end,
        selected_text=selected_text,
    )
    return ParsedStudioRequest(request=request, identity=identity)


async def read_limited_json_body(request: Any, limits: ServiceLimits) -> dict[str, Any]:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError as exc:
            raise ServiceRequestError("contentLength") from exc
        if declared < 0:
            raise ServiceRequestError("contentLength")
        if declared > limits.max_body_bytes:
            raise ServiceLimitError("bodyBytes", limits.max_body_bytes)

    body = bytearray()
    async for chunk in request.stream():
        if not chunk:
            continue
        body.extend(chunk)
        if len(body) > limits.max_body_bytes:
            raise ServiceLimitError("bodyBytes", limits.max_body_bytes)
    try:
        decoded = json.loads(bytes(body).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ServiceRequestError("json") from exc
    if not isinstance(decoded, dict):
        raise ServiceRequestError("body")
    return decoded


__all__ = [
    "ParsedStudioRequest",
    "RequestIdentity",
    "ServiceLimits",
    "read_limited_json_body",
    "sha256_text",
    "studio_request_from_wire",
]
