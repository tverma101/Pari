#!/usr/bin/env python3
"""CPU/synthetic tests for Issue #29 progressive useful-option timing.

These run with no model, no GPU and no network. They drive the shared progressive
contract with synthetic chunked streams and prove that:

- the first usable candidate is found even when it straddles a chunk boundary;
- thresholds 3 and 10 are crossed at the correct chunk;
- duplicate normalized candidates do not advance unique-depth thresholds;
- commentary and prose wrappers do not advance thresholds;
- a response that ends at 7 candidates leaves first-10 null;
- JSON, numbered/bulleted and newline parser modes behave consistently while
  accumulating;
- final diagnostics equal a one-shot parse of the same completed text.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
from types import SimpleNamespace
from pathlib import Path

from word_studio_output_parser import diagnose

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run-english-core-vllm.py"
NEWLINE = chr(10)


def load_runner():
    """Load the hyphenated CLI runner that owns the shared timing contract."""
    spec = importlib.util.spec_from_file_location("pari_english_core_vllm_runner", RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {RUNNER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER_MODULE = load_runner()
ProgressiveOptionTracker = RUNNER_MODULE.ProgressiveOptionTracker
partial_option_values = RUNNER_MODULE.partial_option_values
partial_candidate_count = RUNNER_MODULE.partial_candidate_count
summarize_progressive_option_timing = RUNNER_MODULE.summarize_progressive_option_timing


def drive(tracker: ProgressiveOptionTracker, chunks: list[str]) -> str:
    """Feed a synthetic chunk stream exactly as a live runner would."""
    accumulated = ""
    for chunk in chunks:
        accumulated += chunk
        tracker.observe(chunk, accumulated)
    tracker.finish(accumulated)
    return accumulated


def chunk_by(text: str, size: int) -> list[str]:
    return [text[index:index + size] for index in range(0, len(text), size)]


def json_option_chunks(values: list[str]) -> list[str]:
    """Chunk a JSON options array so each chunk closes exactly one candidate.

    The synthetic stream mirrors a real decoder: separators arrive between
    candidates and never complete one, so candidate N completes on chunk N.
    """
    chunks = ['{"options":["' + values[0] + '"']
    chunks += [',"' + value + '"' for value in values[1:]]
    return chunks


def test_chunk_boundary_first_candidate() -> None:
    """The first candidate's closing quote lands in a later chunk than its text."""
    chunks = ['{"options":["cl', "ear and dir", 'ect"']
    assert partial_candidate_count("".join(chunks[:2])) == 0

    partial_tracker = ProgressiveOptionTracker()
    drive(partial_tracker, chunks[:2])
    assert partial_tracker.result("".join(chunks[:2]))["firstCandidateLatencySeconds"] is None

    tracker = ProgressiveOptionTracker()
    completed = drive(tracker, chunks)
    result = tracker.result(completed)
    assert partial_candidate_count(completed) == 1
    assert result["firstCandidateLatencySeconds"] is not None
    assert result["firstCandidateLatencySeconds"] >= 0.0
    assert result["firstThreeCandidatesLatencySeconds"] is None
    assert result["firstTenCandidatesLatencySeconds"] is None
    assert result["progressiveOptionTiming"]["uniqueUsableCandidateCount"] == 1
    assert result["progressiveOptionTiming"]["identityExtractionMismatchCount"] == 0


def test_thresholds_crossed_at_correct_chunk() -> None:
    values = [
        "clear", "easy to follow", "straightforward", "simple", "understandable",
        "plain", "easy", "accessible", "readable", "uncomplicated",
    ]
    tracker = ProgressiveOptionTracker(requested=len(values))
    crossings: dict[int, int] = {}
    accumulated = ""
    for index, chunk in enumerate(json_option_chunks(values), start=1):
        accumulated += chunk
        tracker.observe(chunk, accumulated)
        for crossing in tracker.result(accumulated)["progressiveOptionTiming"]["crossings"]:
            crossings.setdefault(crossing["threshold"], crossing["chunkIndex"])
    assert crossings == {1: 1, 3: 3, 10: 10}

    result = tracker.result(accumulated + "]}")
    assert result["firstCandidateLatencySeconds"] is not None
    assert result["firstThreeCandidatesLatencySeconds"] >= result["firstCandidateLatencySeconds"]
    assert result["firstTenCandidatesLatencySeconds"] >= result["firstThreeCandidatesLatencySeconds"]
    assert result["progressiveOptionTiming"]["unmetThresholds"] == []
    assert result["progressiveOptionTiming"]["identityExtractionMismatchCount"] == 0
    assert result["progressiveOptionTiming"]["uniqueUsableCandidateCount"] == 10
    assert result["progressiveOptionTiming"]["rawCompletedCandidateCount"] == 10


def test_duplicates_do_not_advance_unique_thresholds() -> None:
    # `normalize` collapses whitespace and case-folds only, so these are the
    # candidates the frozen contract treats as normalized duplicates.
    values = ["clear", "clear", "CLEAR", "  Clear  ", "plain", "simple", "easy"]
    tracker = ProgressiveOptionTracker(requested=10)
    accumulated = drive(tracker, json_option_chunks(values)) + "]}"
    result = tracker.result(accumulated)
    evidence = result["progressiveOptionTiming"]
    assert evidence["rawCompletedCandidateCount"] == 7
    assert evidence["duplicateCandidateCount"] == 3
    assert evidence["uniqueUsableCandidateCount"] == 4
    assert result["firstCandidateLatencySeconds"] is not None
    assert result["firstThreeCandidatesLatencySeconds"] is not None
    assert result["firstTenCandidatesLatencySeconds"] is None
    assert evidence["unmetThresholds"] == [10]
    assert result["diagnostics"]["parsedCount"] == 7


def test_commentary_does_not_advance_thresholds() -> None:
    values = [
        "Sure, here are ten alternatives:",
        "clear",
        "Note: these are all short rewrites.",
        "plain",
        "easy",
    ]
    tracker = ProgressiveOptionTracker(requested=10)
    accumulated = drive(tracker, json_option_chunks(values)) + "]}"
    result = tracker.result(accumulated)
    evidence = result["progressiveOptionTiming"]
    assert evidence["rawCompletedCandidateCount"] == 5
    assert evidence["commentaryCandidateCount"] == 2
    assert evidence["uniqueUsableCandidateCount"] == 3
    assert result["firstCandidateLatencySeconds"] is not None
    assert result["firstThreeCandidatesLatencySeconds"] is not None
    assert result["firstTenCandidatesLatencySeconds"] is None


def test_unchanged_source_is_not_usable() -> None:
    values = ["the quick brown fox", "clear", "plain", "simple", "easy", "short"]
    tracker = ProgressiveOptionTracker(source="the quick brown fox", requested=10)
    accumulated = drive(tracker, json_option_chunks(values)) + "]}"
    result = tracker.result(accumulated)
    evidence = result["progressiveOptionTiming"]
    assert evidence["unchangedSourceCandidateCount"] == 1
    assert evidence["uniqueUsableCandidateCount"] == 5
    assert result["firstTenCandidatesLatencySeconds"] is None
    assert result["diagnostics"]["unchangedSourceCount"] == 1


def test_seven_candidates_leaves_first_ten_null() -> None:
    values = ["clear", "plain", "simple", "easy", "short", "terse", "brief"]
    tracker = ProgressiveOptionTracker(requested=10)
    completed = drive(tracker, json_option_chunks(values)) + "]}"
    result = tracker.result(completed)
    assert result["progressiveOptionTiming"]["uniqueUsableCandidateCount"] == 7
    assert result["firstCandidateLatencySeconds"] is not None
    assert result["firstThreeCandidatesLatencySeconds"] is not None
    assert result["firstTenCandidatesLatencySeconds"] is None
    assert result["progressiveOptionTiming"]["unmetThresholds"] == [10]
    assert "word_studio_too_few_candidates" in result["diagnostics"]["statuses"]


def test_parser_modes_consistent_under_streaming() -> None:
    values = ["clear", "plain", "simple", "easy", "short", "terse", "brief", "neat", "clean", "lean"]

    json_text = json.dumps({"options": values}, ensure_ascii=False)
    json_tracker = ProgressiveOptionTracker(requested=10)
    json_completed = drive(json_tracker, chunk_by(json_text, 7))
    json_result = json_tracker.result(json_completed)
    assert json_result["firstTenCandidatesLatencySeconds"] is not None
    assert json_result["progressiveOptionTiming"]["identityExtractionMismatchCount"] == 0
    assert "json_object" in json_result["progressiveOptionTiming"]["parserModesObserved"]

    bulleted = NEWLINE.join("- " + value for value in values)
    bullet_tracker = ProgressiveOptionTracker(requested=10)
    bullet_completed = drive(bullet_tracker, chunk_by(bulleted, 5))
    bullet_result = bullet_tracker.result(bullet_completed)
    assert bullet_result["firstTenCandidatesLatencySeconds"] is not None
    assert bullet_result["progressiveOptionTiming"]["uniqueUsableCandidateCount"] == 10
    assert "numbered_or_bulleted_list" in bullet_result["progressiveOptionTiming"]["parserModesObserved"]

    newline_list = NEWLINE.join(values)
    newline_tracker = ProgressiveOptionTracker(requested=10)
    newline_completed = drive(newline_tracker, chunk_by(newline_list, 5))
    newline_result = newline_tracker.result(newline_completed)
    assert newline_result["firstTenCandidatesLatencySeconds"] is not None
    assert newline_result["progressiveOptionTiming"]["uniqueUsableCandidateCount"] == 10

    for completed, result in (
        (json_completed, json_result),
        (bullet_completed, bullet_result),
        (newline_completed, newline_result),
    ):
        assert result["diagnostics"] == diagnose(completed, requested=10)
        assert result["diagnostics"]["parsedCount"] == 10


def test_final_diagnostics_equal_one_shot_parse() -> None:
    values = ["clear", "plain", "simple", "easy", "short", "terse", "brief", "neat", "clean", "lean"]
    text = json.dumps({"options": values}, ensure_ascii=False)
    tracker = ProgressiveOptionTracker(requested=10)
    completed = drive(tracker, chunk_by(text, 3))
    streamed = tracker.result(completed)["diagnostics"]
    one_shot = diagnose(text, requested=10)
    assert streamed == one_shot
    assert streamed["parserMode"] == "json_object"
    assert streamed["uniqueNormalizedCount"] == 10
    assert streamed["statuses"] == ["ok"]


def test_prose_without_a_list_crosses_no_threshold() -> None:
    text = (
        "I would rewrite this sentence in a clearer way. "
        "There are many good options for making it easier to follow."
    )
    tracker = ProgressiveOptionTracker(requested=10)
    completed = drive(tracker, chunk_by(text, 4))
    result = tracker.result(completed)
    assert result["firstCandidateLatencySeconds"] is None
    assert result["firstThreeCandidatesLatencySeconds"] is None
    assert result["firstTenCandidatesLatencySeconds"] is None
    assert result["progressiveOptionTiming"]["unmetThresholds"] == [1, 3, 10]
    assert result["progressiveOptionTiming"]["uniqueUsableCandidateCount"] == 0


def test_inapplicable_row_keeps_nulls() -> None:
    tracker = ProgressiveOptionTracker(applicable=False)
    completed = drive(tracker, chunk_by('{"options":["clear","plain"]}', 4))
    result = tracker.result(completed)
    assert result["firstCandidateLatencySeconds"] is None
    assert result["firstThreeCandidatesLatencySeconds"] is None
    assert result["firstTenCandidatesLatencySeconds"] is None
    assert result["progressiveOptionTiming"]["applicable"] is False
    assert result["diagnostics"] is None


def test_partial_values_match_frozen_counter() -> None:
    """Identity recovery never counts more candidates than the frozen parser."""
    samples = [
        '{"options":["a","b","c"',
        '{"options":["a","b"],"x":1',
        "1. alpha" + NEWLINE + "2. beta" + NEWLINE + "3. gam",
        "- alpha" + NEWLINE + "- beta" + NEWLINE + "- gamma" + NEWLINE + "- del",
        "Here are options:" + NEWLINE + "1. one" + NEWLINE + "2. two",
        '{"options":["esc quote","second"]}',
        "plain prose with no list at all",
        '{"options":[]}',
        "",
    ]
    for text in samples:
        values, _mode = partial_option_values(text)
        assert len(values) == partial_candidate_count(text), text


def test_summary_counts_and_null_preservation() -> None:
    values = ["clear", "plain", "simple", "easy", "short", "terse", "brief"]
    full = ProgressiveOptionTracker(requested=10)
    full_row = full.result(drive(full, json_option_chunks(values)) + "]}")
    short = ProgressiveOptionTracker(requested=10)
    short_row = short.result(drive(short, json_option_chunks(values[:3])) + "]}")
    inapplicable = ProgressiveOptionTracker(applicable=False)
    naive_row = inapplicable.result("A")
    summary = summarize_progressive_option_timing([full_row, short_row, naive_row])
    assert summary["applicableRows"] == 2
    assert summary["inapplicableRows"] == 1
    assert summary["crossedRowCounts"]["firstCandidateLatencySeconds"] == 2
    assert summary["nullPreservedRowCounts"]["firstTenCandidatesLatencySeconds"] == 2
    assert summary["schemaVersion"] == RUNNER_MODULE.PROGRESSIVE_SCHEMA_VERSION
    assert summary["thresholds"] == [1, 3, 10]


def test_threshold_timestamps_are_monotonic_and_set_once() -> None:
    values = ["clear", "plain", "simple", "easy", "short", "terse", "brief", "neat", "clean", "lean"]
    tracker = ProgressiveOptionTracker(requested=10)
    accumulated = ""
    seen_first_ten = None
    for chunk in json_option_chunks(values):
        accumulated += chunk
        tracker.observe(chunk, accumulated)
        value = tracker.result(accumulated)["firstTenCandidatesLatencySeconds"]
        if value is not None:
            assert seen_first_ten is None, "a threshold must be timestamped once only"
            seen_first_ten = value
    assert seen_first_ten is not None
    result = tracker.result(accumulated + "]}")
    assert result["firstTenCandidatesLatencySeconds"] == seen_first_ten
    crossings = result["progressiveOptionTiming"]["crossings"]
    assert len([c for c in crossings if c["threshold"] == 10]) == 1
    timings = [c["elapsedSeconds"] for c in crossings]
    assert timings == sorted(timings)


class _FakeAsyncEngine:
    """Minimal stand-in for the vLLM async engine's incremental generate()."""

    def __init__(self, deltas_by_request: dict[str, list[str]], finish_reason: str = "stop"):
        self._deltas = deltas_by_request
        self._finish_reason = finish_reason
        self.request_ids: list[str] = []

    def generate(self, prompt, sampling, request_id):
        self.request_ids.append(request_id)
        deltas = self._deltas[request_id]

        async def stream():
            for delta in deltas:
                yield SimpleNamespace(
                    outputs=[SimpleNamespace(delta=delta, text=None, token_ids=[1], finish_reason=None)],
                    finished=False,
                )
            yield SimpleNamespace(
                outputs=[
                    SimpleNamespace(
                        delta="",
                        text="".join(deltas),
                        token_ids=list(range(len(deltas))),
                        finish_reason=self._finish_reason,
                    )
                ],
                finished=True,
            )

        return stream()


def test_vllm_stream_rows_carry_the_shared_schema() -> None:
    """The async-engine row builder emits real progressive fields from deltas."""
    values = ["clear", "plain", "simple", "easy", "short", "terse", "brief", "neat", "clean", "lean"]
    # One delta closes each candidate, exactly as a real decoder streams them.
    deltas = json_option_chunks(values) + ["]}"]
    engine = _FakeAsyncEngine({"ws-1": deltas})
    task = {
        "id": "ws-1",
        "suite": "word_studio_strength",
        "selectedText": "the quick brown fox",
        "requestedCount": 10,
    }
    rows = asyncio.run(
        RUNNER_MODULE._stream_batch(
            engine,
            [task],
            ["prompt"],
            [object()],
            "sequential",
        )
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "ws-1"
    assert row["output"] == "".join(deltas)
    assert row["finishReason"] == "stop"
    assert row["firstCandidateLatencySeconds"] is not None
    assert row["firstThreeCandidatesLatencySeconds"] is not None
    assert row["firstTenCandidatesLatencySeconds"] is not None
    assert row["progressiveOptionTiming"]["uniqueUsableCandidateCount"] == 10
    assert row["diagnostics"]["parsedCount"] == 10
    assert row["diagnostics"]["statuses"] == ["ok"]


def test_vllm_stream_forced_choice_row_stays_null() -> None:
    engine = _FakeAsyncEngine({"fc-1": ["B"]})
    task = {"id": "fc-1", "generative": False}
    rows = asyncio.run(
        RUNNER_MODULE._stream_batch(engine, [task], ["prompt"], [object()], "sequential")
    )
    row = rows[0]
    assert row["output"] == "B"
    assert row["firstCandidateLatencySeconds"] is None
    assert row["firstThreeCandidatesLatencySeconds"] is None
    assert row["firstTenCandidatesLatencySeconds"] is None
    assert row["progressiveOptionTiming"]["applicable"] is False
    assert row["diagnostics"] is None


def test_offline_word_studio_row_keeps_nulls_and_final_diagnostics() -> None:
    """The offline batch path never fabricates a threshold it did not measure."""
    task = {"id": "ws", "suite": "word_studio_strength", "selectedText": "fox", "requestedCount": 10}
    values = ["clear", "plain", "simple", "easy", "short", "terse", "brief", "neat", "clean", "lean"]
    text = json.dumps({"options": values}, ensure_ascii=False)
    block = RUNNER_MODULE.offline_progressive_block(
        "offline llm.generate returns final RequestOutputs only",
        applicable=RUNNER_MODULE.is_word_studio_generative(task),
        text=text,
        source=RUNNER_MODULE.word_studio_source(task),
        requested=RUNNER_MODULE.word_studio_requested(task),
    )
    assert block["firstCandidateLatencySeconds"] is None
    assert block["firstThreeCandidatesLatencySeconds"] is None
    assert block["firstTenCandidatesLatencySeconds"] is None
    assert block["progressiveOptionTiming"]["supported"] is False
    assert block["progressiveOptionTiming"]["uniqueUsableCandidateCount"] == 10
    assert block["diagnostics"] == diagnose(text, source="fox", requested=10)
    summary = summarize_progressive_option_timing([block])
    assert summary["applicableRows"] == 1
    assert summary["crossedRowCounts"]["firstTenCandidatesLatencySeconds"] == 0
    assert summary["nullPreservedRowCounts"]["firstCandidateLatencySeconds"] == 1


def test_offline_forced_choice_row_is_inapplicable() -> None:
    block = RUNNER_MODULE.offline_progressive_block("offline", applicable=False, text="A")
    assert block["progressiveOptionTiming"]["applicable"] is False
    assert block["diagnostics"] is None
    summary = summarize_progressive_option_timing([block])
    assert summary["applicableRows"] == 0
    assert summary["inapplicableRows"] == 1


def test_streaming_backend_resolution() -> None:
    class Bare:
        pass

    class ArgsOnly:
        AsyncEngineArgs = object

    class Modern:
        AsyncEngineArgs = object
        AsyncLLM = object

    assert RUNNER_MODULE.streaming_backend(Bare()) == (None, None)
    assert RUNNER_MODULE.streaming_backend(ArgsOnly()) == (None, None)
    kind, cls = RUNNER_MODULE.streaming_backend(Modern())
    assert kind == "AsyncLLM" and cls is object


def test_word_studio_row_detection() -> None:
    assert RUNNER_MODULE.is_word_studio_generative({"suite": "word_studio_strength"})
    assert RUNNER_MODULE.is_word_studio_generative({"wordStudio": True})
    assert not RUNNER_MODULE.is_word_studio_generative({"suite": "english_core_shadow"})
    assert RUNNER_MODULE.word_studio_source({"selectedText": "a", "sourceText": "b"}) == "a"
    assert RUNNER_MODULE.word_studio_source({"sourceText": "b"}) == "b"
    assert RUNNER_MODULE.word_studio_source({}) is None
    assert RUNNER_MODULE.word_studio_requested({"requestedCount": 7}) == 7
    assert RUNNER_MODULE.word_studio_requested({}) == 10
    assert RUNNER_MODULE.word_studio_requested({"requestedCount": "bad"}) == 10


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    print(f"Progressive useful-option timing tests passed ({len(tests)} cases).")


if __name__ == "__main__":
    main()
