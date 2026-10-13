#!/usr/bin/env python3
"""Tests for the offline Word Studio judge runner (Issue #73)."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import importlib
judge_mod = importlib.import_module("score-word-studio-judge")
blind_and_compare = judge_mod.blind_and_compare
calibrate_judge_on_pairs = judge_mod.calibrate_judge_on_pairs
compare_hard_rules = judge_mod.compare_hard_rules
evaluate_hard_rules = judge_mod.evaluate_hard_rules
format_judge_prompt = judge_mod.format_judge_prompt


class JudgeTests(unittest.TestCase):
    def setUp(self):
        text = "Meeting starts at 3:00 PM EST in Room 4B."
        start = text.index("3:00 PM EST")
        end = start + len("3:00 PM EST")
        self.task = {
            "id": "task-test-01",
            "sourceText": text,
            "selectedText": text,
            "requestedCount": 2,
            "semanticMode": "alternatives",
            "protectedSpans": [
                {"id": "p1", "text": "3:00 PM EST", "start": start, "end": end, "kind": "time"}
            ],
        }

    def test_hard_rules_reject_protected_corruption(self):
        # Candidate 1 preserves 3:00 PM EST, Candidate 2 corrupts it to 4:00 PM PST
        good_cand = json.dumps(["begins at 3:00 PM EST", "kicks off at 3:00 PM EST"])
        corrupted_cand = json.dumps(["begins at 4:00 PM PST", "kicks off at 4:00 PM PST"])

        result = blind_and_compare(self.task, good_cand, corrupted_cand)
        self.assertEqual(result["winner"], 1, "Good candidate must win against corrupted candidate")
        self.assertEqual(result["decided_by"], "hard_rules", "Must be decided by hard rules without model call")
        self.assertEqual(result["score_cand2"], 0, "Corrupted candidate must receive 0 score")

    def test_hard_rules_both_pass_proceeds_to_judge(self):
        cand1 = json.dumps(["begins at 3:00 PM EST", "commences at 3:00 PM EST"])
        cand2 = json.dumps(["launches at 3:00 PM EST", "takes place at 3:00 PM EST"])

        result = blind_and_compare(self.task, cand1, cand2)
        self.assertEqual(result["decided_by"], "judge_model")

    def test_blinding_invariance(self):
        # Swapping cand1 and cand2 arguments must yield inverse winner
        good_cand = json.dumps(["begins at 3:00 PM EST", "kicks off at 3:00 PM EST"])
        corrupted_cand = json.dumps(["begins at 4:00 PM PST", "kicks off at 4:00 PM PST"])

        res1 = blind_and_compare(self.task, good_cand, corrupted_cand)
        res2 = blind_and_compare(self.task, corrupted_cand, good_cand)

        self.assertEqual(res1["winner"], 1)
        self.assertEqual(res2["winner"], 2)

    def test_format_judge_prompt(self):
        prompt = format_judge_prompt(
            context="The system is reliable.",
            selection="reliable",
            operation="alternatives",
            options_a=["dependable", "trustworthy"],
            options_b=["fast", "quick"],
        )
        self.assertIn("Meaning preservation", prompt)
        self.assertIn("candidate_set_A", prompt)
        self.assertIn("candidate_set_B", prompt)
        self.assertIn("dependable", prompt)

    def test_calibration_on_known_pairs(self):
        pairs = [
            {
                "id": "swords-1",
                "source": "The findings were significant.",
                "selection": "significant",
                "good_candidate": "meaningful",
                "bad_candidate": "trivial",  # opposite meaning
            },
            {
                "id": "swords-2",
                "source": "He resolved the issue promptly.",
                "selection": "resolved the issue promptly",
                "good_candidate": "fixed the problem quickly",
                "bad_candidate": "ignored the problem entirely",
            },
        ]
        # Custom mock model evaluator that prefers semantically matching option
        def mock_evaluator(prompt: str):
            if "meaningful" in prompt:
                pref = "A" if '"meaningful"' in prompt.split("candidate_set_A")[1].split("candidate_set_B")[0] else "B"
                return {"preferred": pref, "reason": "Accurate synonym", "score_A": 9, "score_B": 2}
            if "fixed the problem quickly" in prompt:
                pref = "A" if '"fixed the problem quickly"' in prompt.split("candidate_set_A")[1].split("candidate_set_B")[0] else "B"
                return {"preferred": pref, "reason": "Accurate paraphrase", "score_A": 9, "score_B": 2}
            return {"preferred": "tie", "reason": "uncertain", "score_A": 5, "score_B": 5}

        report = calibrate_judge_on_pairs(pairs, evaluator=mock_evaluator)
        self.assertEqual(report["correct"], 2)
        self.assertTrue(report["calibrated"])


if __name__ == "__main__":
    unittest.main()
