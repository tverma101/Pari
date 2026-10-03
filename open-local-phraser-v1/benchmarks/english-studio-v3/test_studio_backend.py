#!/usr/bin/env python3
from __future__ import annotations

import asyncio

from studio_backend import (
    Candidate,
    CandidateAccumulator,
    CandidateLane,
    Operation,
    ProtectedSpan,
    SemanticMode,
    StudioEngine,
    StudioRequest,
    TextRange,
    build_execution_plan,
    candidate_preserves_protected_content,
    compile_prompt,
)
from studio_backend.engine import UNKNOWN_CANDIDATE_FAMILY
from studio_backend.router import families_for


def request_for(text: str, selected: str, operation: Operation, count: int = 40, **kwargs) -> StudioRequest:
    start = text.index(selected)
    return StudioRequest(
        document_text=text,
        selection=TextRange(start, start + len(selected)),
        operation=operation,
        requested_candidates=count,
        **kwargs,
    )


def test_router() -> None:
    req = request_for("The examples clarified the rule for me.", "clarified", Operation.REPLACE)
    plan = build_execution_plan(req)
    assert plan.semantic_mode == SemanticMode.FULL_PRESERVATION
    assert plan.fast.lane == CandidateLane.FAST
    assert plan.diversity is not None
    assert plan.fast.candidate_budget + plan.diversity.candidate_budget == 40
    assert plan.progressive_thresholds == (3, 10, 40)
    assert "word_to_phrase" in plan.diversity.families

    gist = request_for(
        "I like the tool, but sometimes it changes words that were already fine.",
        "I like the tool, but sometimes it changes words that were already fine.",
        Operation.COMPRESS_GIST,
        10,
    )
    gist_plan = build_execution_plan(gist)
    assert gist_plan.semantic_mode == SemanticMode.INTENTIONAL_COMPRESSION
    assert gist_plan.progressive_thresholds == (3, 10)

    expand = request_for("The change was helpful.", "helpful", Operation.EXPAND, 3)
    expand_plan = build_execution_plan(expand)
    assert expand_plan.semantic_mode == SemanticMode.CONTROLLED_EXPANSION
    assert expand_plan.progressive_thresholds == (3,)


def test_prompt_contract() -> None:
    text = 'Jordan sent report-v2.pdf to help@example.com at 8:30 PM and wrote “Do not restart”.'
    req = request_for(text, "sent", Operation.REPLACE, 10)
    plan = build_execution_plan(req)
    prompt = compile_prompt(req, plan.fast, plan.semantic_mode)
    assert prompt.candidate_budget == plan.fast.candidate_budget
    assert "report-v2.pdf" in prompt.user
    assert "help@example.com" in prompt.user
    assert "8:30 PM" in prompt.user
    assert "Do not restart" in prompt.user
    assert "Return exactly" in prompt.user and '"options"' in prompt.user
    assert "vocabulary sophistication" in prompt.user

    gist_text = "The tool is useful overall, but it sometimes rewrites words that were already fine."
    gist_req = request_for(gist_text, gist_text, Operation.COMPRESS_GIST, 10)
    gist_plan = build_execution_plan(gist_req)
    gist_prompt = compile_prompt(gist_req, gist_plan.fast, gist_plan.semantic_mode)
    assert "Omission of secondary detail is intentional" in gist_prompt.user
    assert "do not introduce a new proposition" in gist_prompt.user


# Families that silently request a register change. PRESERVE_REGISTER must never
# select one of these for any source register.
REGISTER_CHANGING_FAMILIES = {
    "casual_variant",
    "formal_variant",
    "more_casual",
    "more_formal",
    "less_formal",
    "informal_variant",
}

# Families whose names denote gist/detail loss. Only COMPRESS_GIST routes
# (SemanticMode.INTENTIONAL_COMPRESSION) may request them; every other route is
# FULL_PRESERVATION or CONTROLLED_EXPANSION and must not hint at proposition loss.
INTENTIONAL_COMPRESSION_FAMILIES = {
    "gist_label",
    "compact_concept",
    "one_word_gist",
    "two_word_gist",
    "three_word_gist",
    "alternate_abstraction",
}

REGISTER_SOURCES = {
    "formal": "The committee shall review the submission prior to the commencement of the hearing.",
    "casual": "hey can you take a peek at this before friday when u get a sec",
    "technical": "The async worker retries the idempotency key until the broker acknowledges the duplicate.",
    "emotional": "I am absolutely furious that nobody bothered to warn us about the shutdown.",
}


def test_route_family_invariants() -> None:
    for label, source in REGISTER_SOURCES.items():
        req = request_for(source, source, Operation.PRESERVE_REGISTER, 10)
        plan = build_execution_plan(req)
        assert plan.semantic_mode == SemanticMode.FULL_PRESERVATION, label
        for lane_plan in (plan.fast, plan.diversity):
            assert lane_plan is not None, label
            requested = set(lane_plan.families)
            assert not (requested & REGISTER_CHANGING_FAMILIES), (
                f"PRESERVE_REGISTER {lane_plan.lane.value} lane requests a register change for {label} source: "
                f"{sorted(requested & REGISTER_CHANGING_FAMILIES)}"
            )

    assert "same_register_lexical_variant" in families_for(Operation.PRESERVE_REGISTER, CandidateLane.DIVERSITY)
    assert "casual_variant" not in families_for(Operation.PRESERVE_REGISTER, CandidateLane.DIVERSITY)
    assert "casual_variant" not in families_for(Operation.PRESERVE_REGISTER, CandidateLane.FAST)

    # Intentional-compression families stay isolated to COMPRESS_GIST, the only
    # operation whose semantic mode permits detail loss.
    for operation in Operation:
        for lane in CandidateLane:
            families = set(families_for(operation, lane))
            leaking = families & INTENTIONAL_COMPRESSION_FAMILIES
            if operation == Operation.COMPRESS_GIST:
                # The gist route is allowed (and expected) to request these.
                continue
            assert not leaking, (
                f"{operation.value}/{lane.value} requests gist families {sorted(leaking)} "
                "outside COMPRESS_GIST"
            )

    # Every gist family must actually be reachable, so the invariant above
    # cannot pass by renaming the whole set away.
    gist_families = set(families_for(Operation.COMPRESS_GIST, CandidateLane.FAST)) | set(
        families_for(Operation.COMPRESS_GIST, CandidateLane.DIVERSITY)
    )
    assert INTENTIONAL_COMPRESSION_FAMILIES <= gist_families


def candidate(text: str, index: int, lane: CandidateLane = CandidateLane.FAST) -> Candidate:
    return Candidate(text=text, lane=lane, family="fixture", generation_index=index)


def test_progressive_delivery_and_cancel() -> None:
    req = request_for("The examples clarified the rule for me.", "clarified", Operation.REPLACE, 10)
    plan = build_execution_plan(req)
    acc = CandidateAccumulator(plan)

    assert acc.add([candidate("made clearer", 0), candidate("helped explain", 1)]) == ()
    first = acc.add([candidate("cleared up", 2)])
    assert len(first) == 1
    assert first[0].sequence == 1
    assert len(first[0].candidates) == 3
    assert not first[0].final

    assert acc.add([candidate("  MADE CLEARER  ", 3)]) == ()
    remaining = [candidate(f"option {i}", i, CandidateLane.DIVERSITY) for i in range(4, 11)]
    final = acc.add(remaining, all_finished=True)
    assert final
    assert final[-1].final
    assert final[-1].cumulative_unique_count == 10
    assert len(final[-1].candidates) == 10

    cancelled = CandidateAccumulator(plan)
    cancel_batch = cancelled.cancel()
    assert cancel_batch.cancelled and cancel_batch.final
    assert cancelled.add([candidate("ignored", 0)], all_finished=True) == ()


def test_final_partial_snapshot() -> None:
    req = request_for("The explanation was hard to follow.", "hard to follow", Operation.SHORTEN, 10)
    plan = build_execution_plan(req)
    acc = CandidateAccumulator(plan)
    batches = acc.add([candidate("confusing", 0), candidate("unclear", 1)], all_finished=True)
    assert len(batches) == 1
    assert batches[0].final
    assert len(batches[0].candidates) == 2


def test_protected_gate() -> None:
    text = "Jordan uploaded report-v2.pdf before the deadline."
    selected = "uploaded report-v2.pdf"
    start = text.index(selected)
    req = StudioRequest(
        document_text=text,
        selection=TextRange(start, start + len(selected)),
        operation=Operation.REWRITE,
        requested_candidates=10,
        protected_spans=(ProtectedSpan("report-v2.pdf", text.index("report-v2.pdf"), text.index("report-v2.pdf") + len("report-v2.pdf")),),
    )
    assert candidate_preserves_protected_content(req, "sent report-v2.pdf")
    assert not candidate_preserves_protected_content(req, "sent the report")


class FakeAdapter:
    def __init__(self, values: list[str], delay: float) -> None:
        self.values = values
        self.delay = delay
        self.cancelled: set[str] = set()

    async def generate(self, prompt, *, request_id: str) -> list[str]:
        await asyncio.sleep(self.delay)
        return list(self.values)

    async def cancel(self, request_id: str) -> None:
        self.cancelled.add(request_id)


async def _engine_progressive_case() -> None:
    req = request_for("The examples clarified the rule for me.", "clarified", Operation.REPLACE, 10)
    fast = FakeAdapter(["made clearer", "helped explain", "cleared up", "explained", "made plain", "made easier", "clarified better"], 0.01)
    diversity = FakeAdapter(["made easier to understand", "helped me understand", "made more understandable"], 0.03)
    engine = StudioEngine(fast, diversity)
    batches = [batch async for batch in engine.stream(req)]
    assert len(batches) == 2
    assert len(batches[0].candidates) == 3
    assert not batches[0].final
    assert len(batches[1].candidates) == 10
    assert batches[1].final
    assert batches[0].candidates[0].lane == CandidateLane.FAST
    assert batches[1].candidates[-1].lane == CandidateLane.DIVERSITY


async def _engine_cancel_case() -> None:
    req = request_for("The explanation was hard to follow.", "hard to follow", Operation.REPLACE, 10)
    fast = FakeAdapter(["confusing"] * 10, 5.0)
    diversity = FakeAdapter(["unclear"] * 10, 5.0)
    engine = StudioEngine(fast, diversity)

    async def collect():
        return [batch async for batch in engine.stream(req)]

    task = asyncio.create_task(collect())
    await asyncio.sleep(0.02)
    await engine.cancel(req.request_id)
    batches = await asyncio.wait_for(task, timeout=1.0)
    assert len(batches) == 1
    assert batches[0].cancelled and batches[0].final
    assert req.request_id in fast.cancelled
    assert req.request_id in diversity.cancelled


async def _engine_no_fabricated_family_provenance() -> None:
    """The generator returns a flat options array, so no candidate may claim a family."""
    source = "The committee shall review the submission before the hearing convenes."
    req = request_for(source, source, Operation.PRESERVE_REGISTER, 10)
    plan = build_execution_plan(req)
    assert plan.diversity is not None
    # A lane that requests several families is exactly the case that used to
    # produce round-robin labels.
    assert len(plan.diversity.families) >= 3

    fast = FakeAdapter([f"fast option {i}" for i in range(5)], 0.01)
    diversity = FakeAdapter([f"diverse option {i}" for i in range(5)], 0.02)
    engine = StudioEngine(fast, diversity)
    batches = [batch async for batch in engine.stream(req)]

    streamed = [c for batch in batches for c in batch.candidates]
    assert streamed, "expected streamed candidates"
    for item in streamed:
        assert item.family == UNKNOWN_CANDIDATE_FAMILY, (
            f"candidate claimed unobserved family {item.family!r}"
        )

    # The requested search plan stays observable and separate from candidate metadata.
    for lane_plan in (plan.fast, plan.diversity):
        assert lane_plan.families and UNKNOWN_CANDIDATE_FAMILY not in lane_plan.families
    assert {item.lane for item in streamed} == {CandidateLane.FAST, CandidateLane.DIVERSITY}


def test_engine() -> None:
    asyncio.run(_engine_progressive_case())
    asyncio.run(_engine_cancel_case())


def main() -> None:
    test_router()
    test_route_family_invariants()
    test_prompt_contract()
    test_progressive_delivery_and_cancel()
    test_final_partial_snapshot()
    test_protected_gate()
    test_engine()
    asyncio.run(_engine_no_fabricated_family_provenance())
    print("Studio backend contract tests passed.")


if __name__ == "__main__":
    main()
