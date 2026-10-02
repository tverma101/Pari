#!/usr/bin/env python3
from __future__ import annotations

from studio_backend import (
    Candidate,
    CandidateAccumulator,
    CandidateLane,
    Operation,
    SemanticMode,
    StudioRequest,
    TextRange,
    build_execution_plan,
    compile_prompt,
)


def request_for(text: str, selected: str, operation: Operation, count: int = 40) -> StudioRequest:
    start = text.index(selected)
    return StudioRequest(
        document_text=text,
        selection=TextRange(start, start + len(selected)),
        operation=operation,
        requested_candidates=count,
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

    # Case/whitespace duplicates do not inflate progressive thresholds.
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


def main() -> None:
    test_router()
    test_prompt_contract()
    test_progressive_delivery_and_cancel()
    test_final_partial_snapshot()
    print("Studio backend contract tests passed.")


if __name__ == "__main__":
    main()
