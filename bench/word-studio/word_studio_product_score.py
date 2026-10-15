"""Deterministic product metrics for one Word Studio model response.

The scorer is deliberately a thin, JSON-safe wrapper around the parser contract;
it never turns malformed output into a quality score and never invokes a model.
"""
from __future__ import annotations

from typing import Any, Iterable

from word_studio_output_parser import diagnose, partial_usable_unique_count


def score_product_output(
    raw: str,
    *,
    requested: int = 10,
    source: str | None = None,
    protected: Iterable[Any] | None = None,
    route: str = "alternatives",
) -> dict[str, Any]:
    """Return auditable Word Studio depth/duplicate/safety metrics.

    ``usableUniqueCount`` is the only candidate-depth metric used for product
    gates. Parser statuses and duplicate taxonomy remain visible so callers do
    not collapse malformed output or protected-content failures into a score.
    """
    diagnostics = diagnose(
        raw,
        source=source,
        requested=requested,
        protected=protected,
        route=route,
    )
    return {
        "version": 1,
        "requestedCount": diagnostics["requestedCount"],
        "parsedCount": diagnostics["parsedCount"],
        "usableUniqueCount": diagnostics["usableUniqueCount"],
        "depth": {
            "first1": min(1, diagnostics["usableUniqueCount"]),
            "first3": min(3, diagnostics["usableUniqueCount"]),
            "first10": min(10, diagnostics["usableUniqueCount"]),
        },
        "duplicateTaxonomy": diagnostics["duplicateTaxonomy"],
        "protectedContentCorruptionCount": diagnostics["protectedContentCorruptionCount"],
        "statuses": diagnostics["statuses"],
        "accepted": diagnostics["usableUniqueCount"] >= int(requested)
        and diagnostics["protectedContentCorruptionCount"] == 0,
        "parserVersion": diagnostics["parserVersion"],
    }


def score_stream_depth(raw: str, *, requested: int = 10) -> dict[str, int]:
    """Return the same usable-depth counters used during incremental streaming."""
    usable = partial_usable_unique_count(raw, final=False)
    return {"usableUniqueCount": usable, "first1": min(1, usable), "first3": min(3, usable), "first10": min(10, usable)}
