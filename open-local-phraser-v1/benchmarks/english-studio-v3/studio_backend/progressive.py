#!/usr/bin/env python3
"""Progressive 3→10→final candidate delivery for Pari Studio."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .contracts import Candidate, CandidateBatch, ExecutionPlan


def normalize_candidate(text: str) -> str:
    text = text.strip().strip('"“”')
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text.casefold()


@dataclass
class CandidateAccumulator:
    plan: ExecutionPlan
    _unique: list[Candidate] = field(default_factory=list)
    _seen: set[str] = field(default_factory=set)
    _emitted_thresholds: set[int] = field(default_factory=set)
    _sequence: int = 0
    _cancelled: bool = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def unique_count(self) -> int:
        return len(self._unique)

    def cancel(self) -> CandidateBatch:
        self._cancelled = True
        self._sequence += 1
        return CandidateBatch(
            request_id=self.plan.request_id,
            sequence=self._sequence,
            candidates=(),
            cumulative_unique_count=len(self._unique),
            final=True,
            cancelled=True,
        )

    def add(self, candidates: list[Candidate] | tuple[Candidate, ...], *, lane_finished: bool = False, all_finished: bool = False) -> tuple[CandidateBatch, ...]:
        if self._cancelled:
            return ()
        for candidate in candidates:
            normalized = normalize_candidate(candidate.text)
            if not normalized or normalized in self._seen:
                continue
            self._seen.add(normalized)
            self._unique.append(candidate)
            if len(self._unique) >= self.plan.progressive_thresholds[-1]:
                break

        batches: list[CandidateBatch] = []
        for threshold in self.plan.progressive_thresholds:
            if threshold in self._emitted_thresholds or len(self._unique) < threshold:
                continue
            self._emitted_thresholds.add(threshold)
            self._sequence += 1
            batches.append(
                CandidateBatch(
                    request_id=self.plan.request_id,
                    sequence=self._sequence,
                    candidates=tuple(self._unique[:threshold]),
                    cumulative_unique_count=len(self._unique),
                    final=all_finished and threshold == self.plan.progressive_thresholds[-1],
                )
            )

        # If generation ends with fewer unique options than requested, still emit a
        # final snapshot so the UI never waits forever for an unreachable threshold.
        if all_finished and (not batches or not batches[-1].final):
            self._sequence += 1
            batches.append(
                CandidateBatch(
                    request_id=self.plan.request_id,
                    sequence=self._sequence,
                    candidates=tuple(self._unique),
                    cumulative_unique_count=len(self._unique),
                    final=True,
                )
            )
        return tuple(batches)
