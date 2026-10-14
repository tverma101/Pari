#!/usr/bin/env python3
"""Runtime-neutral concurrent execution engine for Pari Word Studio."""
from __future__ import annotations

import asyncio
import uuid
from collections import OrderedDict
from dataclasses import dataclass, replace
from typing import Any, AsyncIterator, Protocol

from .contracts import Candidate, CandidateBatch, CandidateLane, LanePlan, SemanticMode, StudioRequest
from .errors import ClientErrorCode, error_code_for_exception
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
    diagnostics: dict[str, Any]
    error: dict[str, Any] | None = None
    model_id: str | None = None
    runtime_id: str | None = None


# The generator is asked for a plain JSON ``options`` array with no
# candidate -> family mapping, so there is no observed evidence linking any
# option to any requested family. Candidate-level family stays explicitly
# unknown; the requested search families live on ``LanePlan.families``.
UNKNOWN_CANDIDATE_FAMILY = "unknown"


# A caller can cancel any request id at any time, including ids that never
# reach this engine, so the pre-stream tombstones below must be bounded.
MAX_CANCEL_TOMBSTONES = 128


class _BoundedCancels:
    """Size-bounded, least-recently-written map of cancel reasons."""

    def __init__(self, limit: int = MAX_CANCEL_TOMBSTONES) -> None:
        self._limit = limit
        self._entries: OrderedDict[str, str] = OrderedDict()

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: str) -> str | None:
        return self._entries.get(key)

    def record(self, key: str, reason: str) -> None:
        self._entries[key] = reason
        self._entries.move_to_end(key)
        while len(self._entries) > self._limit:
            self._entries.popitem(last=False)

    def take(self, key: str) -> str | None:
        """Remove and return the tombstone for ``key``, if one is present."""
        return self._entries.pop(key, None)

    def discard(self, key: str) -> None:
        self._entries.pop(key, None)


class _CanonicalAccumulator(CandidateAccumulator):
    """Accumulator whose candidate rank does not depend on lane arrival order.

    ``CandidateAccumulator`` appends admitted candidates in the order the lanes
    finish, so swapping the fast and diversity delays would change which
    candidate holds rank 1 even for identical fixtures. Re-ranking the admitted
    list by ``(lane, generation_index)`` keeps every cumulative snapshot - the
    final one especially - a pure function of each lane's own candidate order.

    Only the already-admitted list is re-ordered here; admission, safety and
    snapshot construction stay in ``CandidateAccumulator``.
    """

    _LANE_RANK: dict[CandidateLane, int] = {
        CandidateLane.FAST: 0,
        CandidateLane.DIVERSITY: 1,
    }

    @classmethod
    def _rank(cls, candidate: Candidate) -> tuple[int, int, str]:
        return (
            cls._LANE_RANK.get(candidate.lane, len(cls._LANE_RANK)),
            candidate.generation_index,
            candidate.text,
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
        batches = super().add(
            candidates,
            lane_finished=lane_finished,
            all_finished=all_finished,
            diagnostics=diagnostics,
            errors=errors,
        )
        if not batches:
            return batches
        ranked = sorted(self._unique, key=self._rank)
        if [item.text for item in ranked] == [item.text for item in self._unique]:
            return batches
        self._unique[:] = ranked
        return tuple(
            replace(
                batch,
                candidates=tuple(self._unique[: len(batch.candidates)]),
                cumulative_unique_count=len(batch.candidates),
            )
            for batch in batches
        )


class StudioEngine:
    def __init__(self, fast: LaneAdapter, diversity: LaneAdapter | None = None) -> None:
        self._fast = fast
        self._diversity = diversity or fast
        # Server-issued generation IDs own lifecycle state. The external
        # requestId is only a lookup key, so a stale cancel can never revive or
        # terminate a newer generation that reuses the same client requestId.
        self._cancelled: dict[str, tuple[str, str]] = {}
        self._active: dict[str, set[asyncio.Task[LaneResult]]] = {}
        self._active_generation: dict[str, str] = {}
        self._cancelled_generation = _BoundedCancels()
        self._cancelled_request = _BoundedCancels()

    async def cancel(
        self,
        request_id: str,
        reason: str = "cancelled",
        *,
        generation_id: str | None = None,
    ) -> None:
        """Cancel one owned generation, or mark a pre-stream cancel.

        A cancel that names ``generation_id`` only ever affects that exact
        generation. If that generation is not the live one - because it has not
        entered ``stream()`` yet, or because it already finished - the reason is
        tombstoned under the exact generation id, which no other generation can
        match. A stale cancel for generation N therefore cannot terminate the
        generation that reused the same external request id afterwards. A cancel
        without ``generation_id`` targets whichever generation is active now, or
        tombstones the external request id for one that has not started.

        Both tombstone maps are bounded, so an id that is cancelled repeatedly
        and never streams cannot grow them without limit.
        """
        active_generation = self._active_generation.get(request_id)
        if generation_id is not None and generation_id != active_generation:
            # Not the live generation: either it has not entered stream() yet or
            # it already finished. Keep it keyed by the exact generation id.
            self._cancelled_generation.record(generation_id, reason)
            return
        if active_generation is not None:
            self._cancelled[request_id] = (active_generation, reason)
            tasks = tuple(self._active.get(request_id, set()))
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                self._fast.cancel(request_id),
                self._diversity.cancel(request_id),
                return_exceptions=True,
            )
            return
        self._cancelled_request.record(request_id, reason)

    @staticmethod
    def _adapter_identity(adapter: LaneAdapter) -> tuple[str | None, str | None]:
        return (
            getattr(adapter, "model", None),
            getattr(adapter, "runtime_id", None),
        )

    async def _run_lane(
        self,
        request: StudioRequest,
        lane_plan: LanePlan,
        adapter: LaneAdapter,
        semantic_mode: SemanticMode,
    ) -> LaneResult:
        model_id, runtime_id = self._adapter_identity(adapter)
        prompt = compile_prompt(request, lane_plan, semantic_mode)
        loop = asyncio.get_running_loop()
        started = loop.time()
        try:
            values = await adapter.generate(prompt, request_id=request.request_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = {
                "code": error_code_for_exception(exc).value,
                "failureClass": type(exc).__name__,
                "lane": lane_plan.lane.value,
                "modelId": model_id,
                "runtimeId": runtime_id,
            }
            return LaneResult(
                lane=lane_plan.lane,
                plan=lane_plan,
                values=(),
                diagnostics={
                    "type": "lane",
                    "lane": lane_plan.lane.value,
                    "modelId": model_id,
                    "runtimeId": runtime_id,
                    "state": "failed",
                    "errorCode": error["code"],
                    "failureClass": error["failureClass"],
                    "elapsedMs": round((loop.time() - started) * 1000.0, 3),
                },
                error=error,
                model_id=model_id,
                runtime_id=runtime_id,
            )

        adapter_diagnostics: dict[str, Any] = {}
        diagnostics_getter = getattr(adapter, "diagnostics", None)
        if callable(diagnostics_getter):
            try:
                adapter_diagnostics = dict(diagnostics_getter(request.request_id) or {})
            except Exception as exc:  # diagnostics must not corrupt the lane
                adapter_diagnostics = {
                    "parserError": type(exc).__name__,
                    "parserDiagnosticAvailable": False,
                }

        safe = filter_protected_candidates(request, values)
        gate_rejected = max(0, len(values) - len(safe))
        diagnostics = {
            "type": "lane",
            "lane": lane_plan.lane.value,
            "modelId": model_id,
            "runtimeId": runtime_id,
            "state": "completed",
            "parsedCount": len(values),
            "acceptedCount": len(safe),
            "gateRejectedCount": gate_rejected,
            "parserMode": adapter_diagnostics.get("parserMode"),
            "parserFailure": adapter_diagnostics.get("parserFailure"),
            "parserDiagnosticAvailable": adapter_diagnostics.get(
                "parserDiagnosticAvailable", True
            ),
            "finishReason": adapter_diagnostics.get("finishReason"),
            "outputChars": adapter_diagnostics.get("outputChars"),
            "outputSha256": adapter_diagnostics.get("outputSha256"),
            "elapsedMs": adapter_diagnostics.get("elapsedMs"),
        }
        return LaneResult(
            lane=lane_plan.lane,
            plan=lane_plan,
            values=safe[: lane_plan.candidate_budget],
            diagnostics=diagnostics,
            model_id=model_id,
            runtime_id=runtime_id,
        )

    @staticmethod
    def _to_candidates(result: LaneResult) -> tuple[Candidate, ...]:
        return tuple(
            Candidate(
                text=value,
                lane=result.lane,
                family=UNKNOWN_CANDIDATE_FAMILY,
                generation_index=index,
                model_id=result.model_id,
                runtime_id=result.runtime_id,
            )
            for index, value in enumerate(result.values)
        )

    async def stream(
        self,
        request: StudioRequest,
        *,
        generation_id: str | None = None,
    ) -> AsyncIterator[CandidateBatch]:
        """Stream candidates for one generation of ``request``.

        ``generation_id`` is the server-issued execution id that ``service.py``
        also passes to :meth:`cancel`. When it is omitted a fresh id is minted
        so direct engine callers keep working, and it still cannot collide with
        a server-issued one.
        """
        request_id = request.request_id
        # A duplicate live external request id is rejected before any lifecycle
        # state is read or written, so the rejected stream cannot consume the
        # live generation's cancel tombstone or replace its lane tasks.
        if request_id in self._active:
            raise RuntimeError(f"request_id already active: {request_id}")

        plan = build_execution_plan(request)
        accumulator = _CanonicalAccumulator(
            plan,
            source_text=request.selected_text,
            # Protected coordinates are document-absolute and are enforced by
            # safety.filter_protected_candidates with the full document source.
            # The accumulator's ledger uses the selected slice for the distinct
            # unchanged-source rule, so it must not re-evaluate those coordinates
            # against a different string.
            protected=(),
        )
        # Cancel-before-stream survives entry: the tombstone is consumed here,
        # after the duplicate check and before any lane task starts. An exact
        # generation tombstone wins over the looser request-scoped one.
        generation = generation_id or uuid.uuid4().hex
        pre_stream_reason = self._cancelled_generation.take(generation)
        if pre_stream_reason is None:
            pre_stream_reason = self._cancelled_request.take(request_id)

        tasks: dict[asyncio.Task[LaneResult], CandidateLane] = {}
        fast_task = asyncio.create_task(
            self._run_lane(request, plan.fast, self._fast, plan.semantic_mode)
        )
        tasks[fast_task] = CandidateLane.FAST
        if plan.diversity is not None:
            diversity_task = asyncio.create_task(
                self._run_lane(request, plan.diversity, self._diversity, plan.semantic_mode)
            )
            tasks[diversity_task] = CandidateLane.DIVERSITY
        self._active[request_id] = set(tasks)
        self._active_generation[request_id] = generation
        if pre_stream_reason is not None:
            # Registered under this generation id so the finalizer for a
            # different generation can never drop it.
            self._cancelled[request_id] = (generation, pre_stream_reason)

        # Diagnostics and errors accumulate across every lane completion in this
        # generation, not per wait round: a lane that fails early must still be
        # reported on the terminal batch emitted after a later lane finishes.
        lane_diagnostics: list[dict[str, Any]] = []
        lane_errors: list[dict[str, Any]] = []
        try:
            while tasks:
                entry = self._cancelled.get(request_id)
                if entry is not None and entry[0] == generation:
                    yield accumulator.cancel(entry[1])
                    return

                done, _pending = await asyncio.wait(
                    tasks.keys(), return_when=asyncio.FIRST_COMPLETED
                )
                entry = self._cancelled.get(request_id)
                if entry is not None and entry[0] == generation:
                    yield accumulator.cancel(entry[1])
                    return

                # ``done`` is a set, so collect the lane each task belongs to
                # before removing it and process the round in a fixed lane
                # order. Scheduling jitter must not decide delivery order.
                lane_rank = {
                    CandidateLane.FAST: 0,
                    CandidateLane.DIVERSITY: 1,
                }
                completed: list[tuple[int, LaneResult]] = []
                for task in sorted(
                    done,
                    key=lambda item: lane_rank.get(tasks.get(item, CandidateLane.DIVERSITY), 2),
                ):
                    lane_order = lane_rank.get(tasks.get(task, CandidateLane.DIVERSITY), 2)
                    tasks.pop(task, None)
                    self._active.get(request_id, set()).discard(task)
                    if task.cancelled():
                        continue
                    completed.append((lane_order, task.result()))

                all_finished = not tasks
                for index, (_rank, result) in enumerate(completed):
                    lane_diagnostics.append(result.diagnostics)
                    if result.error is not None:
                        lane_errors.append(result.error)
                    # Exactly one call in the round may close the generation.
                    # Closing it per finished lane would emit one final snapshot
                    # per lane, and the service stops at the first final event,
                    # silently dropping the other lane's candidates.
                    is_final_add = all_finished and index == len(completed) - 1
                    batches = accumulator.add(
                        self._to_candidates(result),
                        all_finished=is_final_add,
                        diagnostics=tuple(lane_diagnostics),
                        errors=tuple(lane_errors),
                    )
                    for batch in batches:
                        yield batch
                    if not batches and lane_diagnostics and not is_final_add:
                        yield accumulator.status_batch(
                            diagnostics=tuple(lane_diagnostics),
                            errors=tuple(lane_errors),
                        )

                if all_finished:
                    if not completed:
                        # Every lane was cancelled before producing a result.
                        for batch in accumulator.add(
                            (),
                            all_finished=True,
                            diagnostics=tuple(lane_diagnostics),
                            errors=tuple(lane_errors),
                        ):
                            yield batch
                    return
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            # Cleanup is scoped to this generation: an older finalizer running
            # late must not orphan the lanes of a newer generation that reused
            # the same external request id, nor drop that generation's cancel.
            active = self._active.get(request_id)
            if active is not None:
                active.difference_update(tasks)
                if not active:
                    self._active.pop(request_id, None)
            if self._active_generation.get(request_id) == generation:
                self._active_generation.pop(request_id, None)
            entry = self._cancelled.get(request_id)
            if entry is not None and entry[0] == generation:
                self._cancelled.pop(request_id, None)
            self._cancelled_generation.discard(generation)
            self._cancelled_request.discard(request_id)


__all__ = ["LaneAdapter", "LaneResult", "StudioEngine", "UNKNOWN_CANDIDATE_FAMILY"]
