"""Code checks, blind packets and citation-checked aggregation (#87)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable

from v2 import aggregate, blind, build_tasks, hard_checks, run_candidate

TASKS = {t["id"]: t for t in build_tasks.load_tasks("screen")}


def ok(raw: str, finish: str = "stop") -> dict[str, Any]:
    return {"status": "ok", "raw_text": raw, "finish_reason": finish}


def options(*values: str) -> str:
    return json.dumps({"options": list(values)})


def flags(task_id: str, *values: str) -> list[dict[str, Any]]:
    return hard_checks.check(TASKS[task_id], ok(options(*values)))["options"]


class HardCheckTests(unittest.TestCase):
    def test_tap_word_rules(self) -> None:
        result = flags("ws2-screen-p01-tap_word-1", "beneficial", "Good", "beneficial", "a really very good", "50")
        self.assertEqual(result[0]["fail"], [])
        self.assertIn("echo", result[1]["fail"])
        self.assertIn("duplicate", result[2]["fail"])
        self.assertIn("too_many_words", result[3]["fail"])
        self.assertIn("invented_number", result[4]["fail"])
        self.assertFalse(result[1]["judge"])

    def test_options_beyond_the_request_are_not_judged(self) -> None:
        words = [f"word{chr(97 + i)}" for i in range(12)]
        result = flags("ws2-screen-p01-tap_word-1", *words)
        self.assertEqual([o["judge"] for o in result], [True] * 10 + [False] * 2)
        self.assertEqual(result[10]["fail"], ["beyond_requested"])

    def test_phrase_to_word_needs_one_word(self) -> None:
        result = flags("ws2-screen-p02-phrase_to_word-1", "steadfast", "very steadfast", "well-meaning")
        self.assertEqual(result[0]["fail"], [])
        self.assertIn("too_many_words", result[1]["fail"])
        self.assertEqual(result[2]["fail"], [], "a hyphenated word is one word")

    def test_word_sentences_needs_the_word_or_a_form_of_it(self) -> None:
        task = "ws2-screen-p04-word_sentences-1"  # deprivation
        result = flags(task, "Sleep deprivation hurts grades.", "Teens who are deprived of sleep struggle.",
                       "Sleep matters for students.")
        self.assertEqual(result[0]["fail"], [])
        self.assertEqual(result[1]["fail"], [], '"deprived" is a form of "deprivation"')
        self.assertIn("missing_word", result[2]["fail"])

    def test_condense_must_be_shorter(self) -> None:
        task = "ws2-screen-p01-condense-1"
        selected = TASKS[task]["selection"]["text"]
        result = flags(task, "A ban would help students focus and score better.", selected + " Truly.")
        self.assertEqual(result[0]["fail"], [])
        self.assertIn("not_shorter", result[1]["fail"])

    def test_numbers_and_quotes_must_survive(self) -> None:
        numbers = flags("ws2-screen-p06-academic-1",
                        "A 2023 survey found that nearly half of adolescents reported worse body image.",
                        "A recent survey found that nearly half of adolescents reported worse body image.",
                        "A 2023 survey of 500 teens found that nearly half reported worse body image.")
        self.assertEqual(numbers[0]["fail"], [])
        self.assertIn("number_changed", numbers[1]["fail"])
        self.assertIn("invented_number", numbers[2]["fail"])
        quotes = flags("ws2-screen-p07-academic-1",
                       "Ultimately, Macbeth calls life “a tale told by an idiot,” revealing his emptiness.",
                       "Ultimately, Macbeth calls life meaningless, revealing his emptiness.")
        self.assertEqual(quotes[0]["fail"], [], "curly quotes keep the quotation")
        self.assertIn("quote_dropped", quotes[1]["fail"])

    def test_negation_and_names_only_warn(self) -> None:
        result = flags("ws2-screen-p01-academic-1",
                       "Some parents fear they will be unable to contact their children during an emergency.",
                       "Some parents fear they will not be able to contact their children during an emergency.")
        self.assertEqual(result[0]["fail"], [])
        self.assertIn("negation_changed", result[0]["warn"])
        self.assertTrue(result[0]["judge"])
        self.assertEqual(result[1]["warn"], [])
        names = flags("ws2-screen-p03-condense-1", "Before 1440, books were copied by hand, which was slow.")
        self.assertIn("name_dropped", names[0]["warn"])

    def test_formats(self) -> None:
        task = TASKS["ws2-screen-p01-tap_word-1"]
        self.assertEqual(hard_checks.check(task, ok(options("fine")))["format"], "strict")
        fenced = "```json\n" + options("fine") + "\n```"
        self.assertEqual(hard_checks.check(task, ok(fenced))["format"], "lenient")
        self.assertEqual(hard_checks.check(task, ok("I cannot help with that."))["format"], "unparseable")
        failed = hard_checks.check(task, {"status": "error", "raw_text": None, "error": {"type": "X"}})
        self.assertEqual((failed["format"], failed["options"]), ("no_output", []))
        self.assertTrue(hard_checks.check(task, ok(options("fine"), finish="length"))["truncated"])


class ScriptedBackend:
    """Returns the same options for every task."""

    def __init__(self, values: list[str], broken: bool = False) -> None:
        self.raw = options(*values)
        self.broken = broken

    def environment(self) -> dict[str, Any]:
        return {}

    def load(self) -> dict[str, Any]:
        if self.broken:
            raise OSError("Revision Not Found")
        return {}

    def generate(self, messages, *, max_new_tokens: int, seed: int, on_text: Callable[[str], None]) -> dict[str, Any]:
        on_text(self.raw)
        return {"text": self.raw, "rendered_prompt": "<p>", "prompt_tokens": 1, "new_tokens": 1,
                "finish_reason": "stop"}


JUDGED = ["ws2-screen-p01-tap_word-1", "ws2-screen-p01-condense-1"]
LABELS = {"cand-a": {"1": 2, "2": 1, "3": 0}, "cand-b": {"1": 1, "3": 1, "4": 2}}


class BlindAggregateTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.run_dir = root / "runs" / "2026-10-16-screen-test"
        backends = {"cand-a": ScriptedBackend(["alpha", "beta", "gamma"]),
                    "cand-b": ScriptedBackend(["alpha", "alpha", "delta", "epsilon"]),
                    "cand-broken": ScriptedBackend([], broken=True)}
        for cid, backend in backends.items():
            candidate = {"candidate_id": cid, "model_id": f"fake/{cid}", "revision": "0" * 40}
            run_candidate.run(candidate, "screen", self.run_dir / cid, backend, log=lambda _: None)
        self.judging = root / "judging" / self.run_dir.name
        self.index = blind.build(self.run_dir, self.judging, task_ids=JUDGED)

    def fill_scores(self, edit: Callable[[list[dict[str, Any]], dict[str, Any]], None] | None = None) -> Path:
        """Fill the template the way the judge would. Only the test reads the key to pick labels."""
        key = json.loads((self.judging / "sealed" / "key.json").read_text(encoding="utf-8"))
        rows = aggregate.read_jsonl(self.judging / "scores.template.jsonl")
        rows[0].update(judge="claude-opus-5-5", session="test-session")
        for row in rows[1:]:
            cid = key["tasks"][row["task_id"]][row["label"]]["candidate_id"]
            row["relevance"] = {k: LABELS[cid][k] for k in row["relevance"]}
            row["criteria"] = {c: 4 for c in blind.CRITERIA}
            row["note"] = "option 3 is off" if 0 in row["relevance"].values() else ""
        if edit:
            edit(rows, key)
        path = self.judging / "scores.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return path

    def test_packets_are_blind(self) -> None:
        texts = [p.read_text(encoding="utf-8") for p in (self.judging / "packets").glob("*")]
        self.assertEqual(len(texts), len(JUDGED) + 1)
        template = (self.judging / "scores.template.jsonl").read_text(encoding="utf-8")
        for text in [*texts, template]:
            for leak in ("cand-a", "cand-b", "fake/", "outputs/", str(self.run_dir)):
                self.assertNotIn(leak, text)
        tap = (self.judging / "packets" / "ws2-screen-p01-tap_word-1.md").read_text(encoding="utf-8")
        self.assertIn("a [[good]] idea", tap)
        self.assertIn("## Output A", tap)
        self.assertIn("## Output B", tap)
        self.assertNotIn("## Output C", tap, "the failed run is not judged")
        self.assertIn("not judged, counts as 0 (fail: duplicate)", tap)
        key = json.loads((self.judging / "sealed" / "key.json").read_text(encoding="utf-8"))
        self.assertEqual([e["candidate_id"] for e in key["not_judged"]], ["cand-broken"])

    def test_aggregate_traces_every_number(self) -> None:
        result = aggregate.aggregate(self.judging, self.fill_scores())
        a, b = result["candidates"]["cand-a"], result["candidates"]["cand-b"]
        self.assertEqual((a["top3_at_bar"], a["top1_at_bar"], a["top3_strong"]), (0.6667, 1.0, 0.3333))
        self.assertEqual((a["usable_per_task"], a["strong_share"]), (2.0, round(2 / 15, 4)))
        self.assertEqual((b["top3_at_bar"], b["top3_strong"], b["usable_per_task"]), (0.6667, 0.0, 3.0))
        self.assertEqual(b["fail_flags"], {"duplicate": 2})
        self.assertEqual(result["ranking"], ["cand-b", "cand-a"], "tie on top-3 goes to usable per task")
        self.assertEqual(a["criteria_means"]["fit"], 4)
        self.assertEqual(len(a["citations"]), 2)
        self.assertTrue(all(c["raw_output"].endswith(f"{c['task_id']}.json") for c in a["citations"]))
        self.assertEqual(result["not_judged"][0]["candidate_id"], "cand-broken")
        self.assertEqual(a["latency_t4"]["first_option"]["n"], 2)
        self.assertTrue(result["sources"]["rubric_unchanged_since"])
        self.assertIn("cand-b", aggregate.markdown(result))

    def assert_refused(self, scores: Path, fragment: str) -> None:
        with self.assertRaises(aggregate.VerificationError) as caught:
            aggregate.aggregate(self.judging, scores)
        self.assertTrue(any(fragment in p for p in caught.exception.problems), caught.exception.problems)

    def test_a_changed_raw_output_is_refused(self) -> None:
        scores = self.fill_scores()
        raw = self.run_dir / "cand-a" / "outputs" / f"{JUDGED[0]}.json"
        raw.write_text(raw.read_text(encoding="utf-8").replace("gamma", "GAMMA"), encoding="utf-8")
        self.assert_refused(scores, "changed after packets were built")

    def test_a_wrong_citation_is_refused(self) -> None:
        def edit(rows, key):
            rows[1]["output_sha256"] = "0" * 64
        self.assert_refused(self.fill_scores(edit), "output_sha256 does not match")

    def test_labelling_a_code_failed_option_is_refused(self) -> None:
        def edit(rows, key):
            for row in rows[1:]:
                if key["tasks"][row["task_id"]][row["label"]]["candidate_id"] == "cand-b":
                    row["relevance"]["2"] = 2
                    return
        self.assert_refused(self.fill_scores(edit), "relevance keys wrong")

    def test_missing_rows_header_and_notes_are_refused(self) -> None:
        self.assert_refused(self.fill_scores(lambda rows, key: rows.pop()), "not scored")
        self.assert_refused(self.fill_scores(lambda rows, key: rows[0].update(judge=None)), "name the judge")

        def no_note(rows, key):
            for row in rows[1:]:
                row["note"] = ""
        self.assert_refused(self.fill_scores(no_note), "a 0 label needs a note")

        def bad_criteria(rows, key):
            rows[1]["criteria"]["fit"] = 6
        self.assert_refused(self.fill_scores(bad_criteria), "criteria must give")

    def test_judging_is_never_overwritten(self) -> None:
        with self.assertRaises(SystemExit):
            blind.build(self.run_dir, self.judging, task_ids=JUDGED)


if __name__ == "__main__":
    unittest.main()
