#!/usr/bin/env python3
"""Progressive 3→10→final candidate delivery for Pari Studio.

Candidate admission is delegated to the canonical Word Studio
``CandidateLedger`` so duplicates, protected corruption, unchanged source,
commentary, and near-duplicates cannot drift from the benchmark contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from word_studio_output_parser import (  # type: ignore[import-not-found]
    ROUTE_INTENTIONAL_COMPRESSION,
    CandidateLedger,
)

from .contracts import Candidate, CandidateBatch, ExecutionPlan, SemanticMode


@dataclass
class CandidateAccumulator:
    plan: ExecutionPlan
    source_text: str | None = None
    protected: Iterable[Any] | None = None
    _ledger: CandidateLedger = field(init=False)
    _unique: list[Candidate] = field(default_factory=list, init=False)
    _emitted_thresholds: set[int] = field(default_factory=set, init=False)
    _sequence: int = field(default=0, init=False)
    _cancelled: bool = field(default=False, init=False)
    _cancel_reason: str | None = field(default=None, init=False)
    _delivery_thresholds: tuple[int, ...] = field(init=False)

    def __post_init__(self) -> None:
        route = (
            ROUTE_INTENTIONAL_COMPRESSION
            if self.plan.semantic_mode == SemanticMode.INTENTIONAL_COMPRESSION
            else "alternatives"
        )
        self._ledger = CandidateLedger(
            source=self.source_text,
            requested=self.plan.progressive_thresholds[-1]
            if self.plan.progressive_thresholds
            else 1,
            route=route,
            protected=self.protected,
        )
        # The router plan freezes the product depth thresholds (3/10/requested).
        # #36 additionally requires the benchmark's first-1 milestone to be
        # observable on its own, so the wire also delivers a one-option
        # snapshot as soon as the first usable candidate is admitted.
        self._delivery_thresholds = tuple(
            dict.fromkeys((1,) + tuple(self.plan.progressive_thresholds))
        )

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def unique_count(self) -> int:
        return len(self._unique)

    @property
    def cancel_reason(self) -> str | None:
        return self._cancel_reason

    def cancel(self, reason: str = "cancelled") -> CandidateBatch:
        self._cancelled = True
        self._cancel_reason = reason
        self._sequence += 1
        return CandidateBatch(
            request_id=self.plan.request_id,
            sequence=self._sequence,
            candidates=(),
            cumulative_unique_count=len(self._unique),
            final=True,
            cancelled=True,
            cancel_reason=reason,
            diagnostics=self.diagnostics(),
        )

    def diagnostics(self) -> dict[str, Any]:
        return {
            "uniqueUsableCandidateCount": self._ledger.usable_unique_count,
            "rejectedCandidateReasons": dict(sorted(self._ledger.rejected_reasons.items())),
            "protectedCorruptionCount": self._ledger.protected_corruption_count,
            "commentaryCandidateCount": self._ledger.commentary_count,
            "unchangedSourceCount": self._ledger.unchanged_source_count,
            "nearDuplicateCount": self._ledger.near_duplicate_count,
            "normalizedDuplicateCount": self._ledger.normalized_duplicate_count,
            "duplicateRejectedCount": (
                self._ledger.normalized_duplicate_count + self._ledger.near_duplicate_count
            ),
        }

    def status_batch(
        self,
        *,
        diagnostics: tuple[dict[str, Any], ...] = (),
        errors: tuple[dict[str, Any], ...] = (),
        final: bool = False,
    ) -> CandidateBatch:
        self._sequence += 1
        return CandidateBatch(
            request_id=self.plan.request_id,
            sequence=self._sequence,
            candidates=(),
            cumulative_unique_count=len(self._unique),
            final=final,
            diagnostics=diagnostics + (self.diagnostics(),) if diagnostics else (self.diagnostics(),),
            errors=errors,
        )

    def add(
        self,
        candidates: list[Candidate] | tuple[Candidate, ...],
        *,
        lane_finished: bool = False,
        all_finished: bool = False,
        diagnostics: tuple[dict[str, Any], ...] = (),
        errors: tuple[dict[str, Any], ...] = (),
    ) -> tuple[CandidateBatch, ...]:
        del lane_finished  # retained for call-site compatibility
        if self._cancelled:
            return ()
        for candidate in candidates:
            verdict = self._ledger.add(candidate.text)
            if not verdict.usable:
                continue
            self._unique.append(candidate)
            if self._delivery_thresholds and len(self._unique) >= self._delivery_thresholds[-1]:
                break

        batches: list[CandidateBatch] = []
        for threshold in self._delivery_thresholds:
            if threshold in self._emitted_thresholds or len(self._unique) < threshold:
                continue
            self._emitted_thresholds.add(threshold)
            self._sequence += 1
            snapshot = tuple(self._unique[:threshold])
            batches.append(
                CandidateBatch(
                    request_id=self.plan.request_id,
                    sequence=self._sequence,
                    # Cumulative snapshot semantics: ``candidates`` is exactly
                    # the ranked prefix at this threshold, and
                    # ``cumulative_unique_count`` matches the delivered length
                    # so the client can reconcile by replace-through-rank.
                    candidates=snapshot,
                    cumulative_unique_count=len(snapshot),
                    final=all_finished and threshold == self._delivery_thresholds[-1],
                    diagnostics=diagnostics + (self.diagnostics(),) if diagnostics else (self.diagnostics(),),
                    errors=errors,
                )
            )

        if all_finished and (not batches or not batches[-1].final):
            self._sequence += 1
            final_snapshot = tuple(self._unique)
            batches.append(
                CandidateBatch(
                    request_id=self.plan.request_id,
                    sequence=self._sequence,
                    candidates=final_snapshot,
                    cumulative_unique_count=len(final_snapshot),
                    final=True,
                    diagnostics=diagnostics + (self.diagnostics(),) if diagnostics else (self.diagnostics(),),
                    errors=errors,
                )
            )
        return tuple(batches)


def normalize_candidate(text: str) -> str:
    """Compatibility helper backed by the canonical comparison key."""
    from word_studio_output_parser import comparison_key

    return comparison_key(text)


__all__ = ["CandidateAccumulator", "normalize_candidate"]
