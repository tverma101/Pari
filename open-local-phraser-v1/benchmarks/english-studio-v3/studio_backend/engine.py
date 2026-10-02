#!/usr/bin/env python3
"""Runtime-neutral concurrent execution engine for Pari Word Studio."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator, Protocol

from .contracts import Candidate, CandidateBatch, CandidateLane, LanePlan, StudioRequest
from .progressive import CandidateAccumulator
from .prompting import CompiledPrompt, compile_prompt
from .router import build_execution_plan
from .safety import filter_protected_candidates


class LaneAdapter(Protocol):
    """A model/runtime adapter bound to one logical generation lane."""

    async def generate(self, prompt: CompiledPrompt, *, request_id: str) -> list[str]: ...

    async def cancel(self, request_id: str) -> None: ...


@dataclass(frozen=True)
class LaneResult:
    lane: CandidateLane
    plan: LanePlan
    values: tuple[str, ...]


class StudioEngine:
    def __init__(self, fast: LaneAdapter, diversity: LaneAdapter | None = None) -> None:
        self._fast = fast
        self._diversity = diversity or fast
        self._cancelled: set[str] = set()

    async def cancel(self, request_id: str) -> None:
        self._cancelled.add(request_id)
        await asyncio.gather(
            self._fast.cancel(request_id),
            self._diversity.cancel(request_id),
            return_exceptions=True,
        )

    async def _run_lane(self, request: StudioRequest, lane_plan: LanePlan, adapter: LaneAdapter, semantic_mode) -> LaneResult:
        prompt = compile_prompt(request, lane_plan, semantic_mode)
        values = await adapter.generate(prompt, request_id=request.request_id)
        safe = filter_protected_candidates(request, values)
        return LaneResult(lane=lane_plan.lane, plan=lane_plan, values=safe)

    @staticmethod
    def _to_candidates(result: LaneResult, *, model_id: str | None = None) -> tuple[Candidate, ...]:
        families = result.plan.families or ("unspecified",)
        return tuple(
            Candidate(
                text=value,
                lane=result.lane,
                family=families[index % len(families)],
                generation_index=index,
                model_id=model_id,
            )
            for index, value in enumerate(result.values)
        )

    async def stream(self, request: StudioRequest) -> AsyncIterator[CandidateBatch]:
        request.validate()
        plan = build_execution_plan(request)
        accumulator = CandidateAccumulator(plan)
        self._cancelled.discard(request.request_id)

        tasks: dict[asyncio.Task[LaneResult], CandidateLane] = {}
        fast_task = asyncio.create_task(self._run_lane(request, plan.fast, self._fast, plan.semantic_mode))
        tasks[fast_task] = CandidateLane.FAST
        if plan.diversity is not None:
            diversity_task = asyncio.create_task(
                self._run_lane(request, plan.diversity, self._diversity, plan.semantic_mode)
            )
            tasks[diversity_task] = CandidateLane.DIVERSITY

        try:
            while tasks:
                if request.request_id in self._cancelled:
                    for task in tasks:
                        task.cancel()
                    yield accumulator.cancel()
                    return

                done, _pending = await asyncio.wait(tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    tasks.pop(task, None)
                    if task.cancelled():
                        continue
                    result = task.result()
                    all_finished = not tasks
                    batches = accumulator.add(self._to_candidates(result), all_finished=all_finished)
                    for batch in batches:
                        yield batch
                        if batch.final:
                            return

            # Defensive fallback: both adapters may return no usable candidates.
            if not accumulator.cancelled:
                for batch in accumulator.add((), all_finished=True):
                    yield batch
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            self._cancelled.discard(request.request_id)
