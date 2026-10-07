#!/usr/bin/env python3
"""Deterministic pre-ranking safety gates for selected-span alternatives."""
from __future__ import annotations

from .contracts import ProtectedSpan, StudioRequest, detect_protected_spans


def protected_inside_selection(request: StudioRequest) -> tuple[ProtectedSpan, ...]:
    detected = (*detect_protected_spans(request.document_text), *request.protected_spans)
    unique: dict[tuple[int | None, int | None, str], ProtectedSpan] = {}
    for span in detected:
        if not span.text:
            continue
        # Explicit spans without coordinates are treated as protected only when
        # their exact value occurs inside the selected text.
        if span.start is None or span.end is None:
            if span.text in request.selected_text:
                unique[(span.start, span.end, span.text)] = span
            continue
        if span.start < request.selection.end and span.end > request.selection.start:
            unique[(span.start, span.end, span.text)] = span
    return tuple(unique.values())


def candidate_preserves_protected_content(request: StudioRequest, candidate: str) -> bool:
    return all(span.text in candidate for span in protected_inside_selection(request))


def filter_protected_candidates(request: StudioRequest, values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(value for value in values if value.strip() and candidate_preserves_protected_content(request, value))
