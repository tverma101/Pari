"""The v2 runner keeps raw outputs, times options from the stream, and records failures (#86)."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Callable

from v2 import run_candidate

CANDIDATE = {"candidate_id": "fake", "model_id": "fake/model", "revision": "0" * 40}


class FakeBackend:
    def __init__(self, fail_on: str | None = None) -> None:
        self.fail_on = fail_on
        self.loaded = False

    def environment(self) -> dict[str, Any]:
        return {"python": "test", "peak_memory": {"cuda:0": 1}}

    def load(self) -> dict[str, Any]:
        self.loaded = True
        return {"model_class": "Fake"}

    def generate(self, messages: list[dict[str, str]], *, max_new_tokens: int, seed: int,
                 on_text: Callable[[str], None]) -> dict[str, Any]:
        if self.fail_on and self.fail_on in messages[1]["content"]:
            on_text('{"options": ["half')
            raise RuntimeError("CUDA out of memory")
        pieces = ['{"options": [', '"alpha", ', '"beta", ', '"gamma"', "]}"]
        for piece in pieces:
            on_text(piece)
        return {"text": "".join(pieces), "rendered_prompt": "<rendered>", "prompt_tokens": 12,
                "new_tokens": 9, "finish_reason": "stop"}


class BrokenBackend(FakeBackend):
    def load(self) -> dict[str, Any]:
        raise OSError("Revision Not Found for url: https://huggingface.co/fake/model/resolve/000/config.json")


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / "run"

    def read_run(self) -> dict[str, Any]:
        return json.loads((self.out / "run.json").read_text(encoding="utf-8"))

    def test_completed_run_keeps_every_raw_output_and_stream_timing(self) -> None:
        record = run_candidate.run(CANDIDATE, "screen", self.out, FakeBackend(), limit=3, log=lambda _: None)
        self.assertEqual(record["status"], "completed")
        self.assertFalse(record["complete_set"], "a limited run is never a complete set")
        outputs = sorted((self.out / "outputs").glob("*.json"))
        self.assertEqual(len(outputs), 3)
        for path in outputs:
            out = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(out["status"], "ok")
            self.assertEqual(out["raw_text"], '{"options": ["alpha", "beta", "gamma"]}')
            self.assertEqual(out["rendered_prompt"], "<rendered>")
            timing = out["timing"]
            self.assertEqual(len(timing["option_ms"]), 3)
            self.assertEqual(timing["option_ms"], sorted(timing["option_ms"]))
            self.assertEqual(len(timing["stream"]), 5)
            self.assertEqual(out["task_id"], path.stem)
        run = self.read_run()
        self.assertEqual(run["tasks"], {"ok": 3, "error": 0, "failed_ids": []})
        self.assertIn("never scores", run["scores"])
        self.assertTrue(run["task_file_sha256"])

    def test_load_failure_is_recorded_as_failed_with_no_outputs(self) -> None:
        record = run_candidate.run(CANDIDATE, "screen", self.out, BrokenBackend(), log=lambda _: None)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["stage"], "load")
        self.assertEqual(record["error"]["type"], "OSError")
        self.assertIn("Revision Not Found", record["error"]["message"])
        self.assertFalse((self.out / "outputs").exists())
        self.assertEqual(self.read_run()["status"], "failed")

    def test_generation_failure_fails_the_run_but_keeps_other_outputs(self) -> None:
        tasks = run_candidate.build_tasks.load_tasks("screen")[:3]
        target = tasks[1]["messages"][1]["content"][-120:]
        record = run_candidate.run(CANDIDATE, "screen", self.out, FakeBackend(fail_on=target), limit=3,
                                   log=lambda _: None)
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["tasks"]["ok"], 2)
        self.assertEqual(record["tasks"]["failed_ids"], [tasks[1]["id"]])
        failed = json.loads((self.out / "outputs" / f"{tasks[1]['id']}.json").read_text(encoding="utf-8"))
        self.assertEqual(failed["status"], "error")
        self.assertEqual(failed["error"]["type"], "RuntimeError")
        self.assertEqual(failed["raw_text"], '{"options": ["half')

    def test_existing_run_is_never_overwritten(self) -> None:
        run_candidate.run(CANDIDATE, "screen", self.out, FakeBackend(), limit=1, log=lambda _: None)
        with self.assertRaises(SystemExit):
            run_candidate.run(CANDIDATE, "screen", self.out, FakeBackend(), limit=1, log=lambda _: None)

    def test_candidates_and_the_broken_control_resolve(self) -> None:
        control = run_candidate.find_candidate("control-missing-revision")
        self.assertEqual(control["role"], "broken_control")
        self.assertEqual(control["listed_in"], "bench/word-studio/v2/controls.json")
        real = run_candidate.find_candidate("qwen35-4b")
        self.assertEqual(len(real["revision"]), 40)
        with self.assertRaises(SystemExit):
            run_candidate.find_candidate("no-such-model")

    def test_checkpoint_coverage_finds_unfilled_weights(self) -> None:
        model = ["experts.0.qweight", "experts.0.scales", "experts.0.g_idx_sort_indices", "norm.weight"]
        stored = ["experts.0.qweight", "experts.0.scales", "mtp.fc.weight", "visual.proj.weight"]
        missing, unused = run_candidate.checkpoint_coverage(
            model, stored, kernel_buffers=run_candidate.GPTQModelBackend.KERNEL_BUFFERS,
            unused_prefixes=run_candidate.GPTQModelBackend.UNUSED_PREFIXES)
        self.assertEqual(missing, ["norm.weight"])
        self.assertEqual(unused, ["visual.proj.weight"])
        self.assertEqual(run_candidate.checkpoint_coverage(stored[:2], stored[:2]), ([], []))

    def test_seeds_are_stable_per_task(self) -> None:
        self.assertEqual(run_candidate.task_seed("ws2-screen-p01-tap_word-1"),
                         run_candidate.task_seed("ws2-screen-p01-tap_word-1"))
        self.assertNotEqual(run_candidate.task_seed("a"), run_candidate.task_seed("b"))

    def test_token_streamer_releases_compact_json_per_token(self) -> None:
        pieces = ['{"', 'options', '":["', 'fast', '","', 'quick', '","', 'rap', 'id', '"]}']
        vocab = {i: p for i, p in enumerate(pieces)}
        streamer = run_candidate.TokenStreamer(lambda ids: "".join(vocab[i] for i in ids), timeout=1)
        clock = run_candidate.StreamClock()
        streamer.put([[90, 91, 92]])  # the prompt, which generate passes first
        for i in range(len(pieces)):
            time.sleep(0.003)
            streamer.put([i])
        streamer.end()
        released = list(streamer)
        self.assertEqual([text for _, text in released], pieces)
        self.assertEqual(sorted(at for at, _ in released), [at for at, _ in released])
        for at, text in released:
            clock.on_text(text, at)
        timing = clock.finish("".join(pieces))
        self.assertEqual(len(timing["option_ms"]), 3)
        self.assertEqual(len(timing["stream"]), len(pieces), "one stream entry per token, not per space")
        self.assertLess(timing["option_ms"][0], timing["option_ms"][2])

    def test_token_streamer_holds_back_a_split_character(self) -> None:
        decoded = {1: "caf", 2: "caf\ufffd", 3: "café"}
        streamer = run_candidate.TokenStreamer(lambda ids: decoded[len(ids)], timeout=1)
        streamer.put([[7]])
        for token in (1, 2, 3):
            streamer.put([token])
        streamer.end()
        self.assertEqual([text for _, text in streamer], ["caf", "é"])

    def test_runner_source_has_no_fallback_numbers(self) -> None:
        source = Path(run_candidate.__file__).read_text(encoding="utf-8").lower()
        for banned in ("fallback_metrics", "calibrated_", "simulated"):
            self.assertNotIn(banned, source)


if __name__ == "__main__":
    unittest.main()
