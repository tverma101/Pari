#!/usr/bin/env python3
"""Protected-content gate backed by the shared #51 protected-content contract."""
from __future__ import annotations

from typing import Any

from word_studio_output_parser import normalize_protected  # type: ignore[import-not-found]

from .contracts import ProtectedSpan, StudioRequest, detect_protected_spans
from .protected_content import ProtectedContentSpan, evaluate_protected_content, normalize_protected_spans


def protected_inside_selection(request: StudioRequest) -> tuple[ProtectedSpan, ...]:
    # Caller-declared spans win: they are the authoritative client contract and
    # may carry a scope the deterministic detector cannot infer.
    detected = (*request.protected_spans, *detect_protected_spans(request.document_text))
    unique: dict[tuple[int | None, int | None, str], ProtectedSpan] = {}
    for span in detected:
        if not span.text:
            continue
        if span.start is None or span.end is None:
            if span.text in request.selected_text:
                unique[(span.start, span.end, span.text)] = span
            continue
        if span.start < request.selection.end and span.end > request.selection.start:
            unique[(span.start, span.end, span.text)] = span
    return tuple(unique.values())


def _contract_spans(request: StudioRequest) -> tuple[ProtectedContentSpan, ...]:
    """Every protected span for this request, in the #51 contract shape."""
    detected = (*detect_protected_spans(request.document_text), *request.protected_spans)
    unique: dict[tuple[int | None, int | None, str], ProtectedSpan] = {}
    for span in detected:
        if not span.text:
            continue
        # Keyed by position and exact text so a detected span and the same span
        # declared by the caller collapse into one span instead of being
        # evaluated as a repeated pair.
        unique.setdefault((span.start, span.end, span.text), span)
    return normalize_protected_spans(
        [
            {
                "id": span.id,
                "kind": span.kind,
                "scope": span.scope,
                "text": span.text,
                "start": span.start,
                "end": span.end,
            }
            for span in unique.values()
        ],
        source_text=request.document_text,
    )


def protected_diagnostics(
    request: StudioRequest,
    candidate: str,
    *,
    candidate_document: str | None = None,
    candidate_range: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Evaluate a candidate through the shared #51 local-route contract.

    The Studio service always rewrites the selected range, so the evaluation
    route is ``local`` with the request selection and, by default, the candidate
    as the whole replacement region. Callers that hold the full rewritten
    document can pass it explicitly with the replacement's region inside it.

    The returned shape stays the one the service has always published
    (``protectedCount`` plus ``missing``/``altered``/``repeatedMismatch``/
    ``positionDrift`` lists of protected texts and ``corrupted``), so existing
    consumers keep working while the verdict itself now comes from #51.
    """
    spans = _contract_spans(request)
    evaluation = evaluate_protected_content(
        request.document_text,
        candidate,
        protected=spans,
        route="local",
        selection=(request.selection.start, request.selection.end),
        candidate_document=candidate_document,
        candidate_range=candidate_range,
    )
    texts_by_id: dict[str, str] = {}
    for span in spans:
        texts_by_id.setdefault(span.id, span.text)

    def _texts(ids: tuple[str, ...]) -> list[str]:
        out: list[str] = []
        for span_id in ids:
            value = texts_by_id.get(span_id, span_id)
            if value not in out:
                out.append(value)
        return out

    return {
        "protectedCount": len(texts_by_id),
        "missing": _texts(evaluation.missing_span_ids),
        "altered": _texts(evaluation.altered_span_ids),
        "repeatedMismatch": _texts(evaluation.repeated_mismatch_span_ids),
        "positionDrift": _texts(evaluation.position_drift_span_ids),
        "corrupted": evaluation.corrupted,
        # Additive fields from the shared contract. The keys above stay exactly
        # as before so no consumer has to change shape to adopt the #51 verdict.
        "contractVersion": evaluation.contract_version,
        "failureClass": evaluation.failure_class,
        "introduced": list(evaluation.introduced),
        "missingSpanIds": list(evaluation.missing_span_ids),
        "alteredSpanIds": list(evaluation.altered_span_ids),
        "repeatedMismatchSpanIds": list(evaluation.repeated_mismatch_span_ids),
        "positionDriftSpanIds": list(evaluation.position_drift_span_ids),
        "introducedSpanIds": list(evaluation.introduced_span_ids),
    }


def candidate_preserves_protected_content(request: StudioRequest, candidate: str) -> bool:
    return not bool(protected_diagnostics(request, candidate).get("corrupted"))


def filter_protected_candidates(
    request: StudioRequest,
    values: list[str] | tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(value for value in values if value.strip() and candidate_preserves_protected_content(request, value))


__all__ = [
    "candidate_preserves_protected_content",
    "filter_protected_candidates",
    "normalize_protected",
    "protected_diagnostics",
    "protected_inside_selection",
]
