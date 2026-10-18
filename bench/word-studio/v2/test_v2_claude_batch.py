"""Unit tests for evidence-safe, resumable Claude scoring; no CLI/network required."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from v2 import claude_batch_judge as judge


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BlindClaudeBatchTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.rubric = root / "RUBRIC.md"
        self.judging = root / "judging"
        rubric_hash = write(self.rubric, "Grade relevance as 0, 1, or 2.")
        packet_hash = write(self.judging / "packets/t1.md",
                            "## Output A\n1. sound\n2. unrelated\n## Output B\nNo options to judge.")
        index = {
            "tasks": ["t1"], "outputs_per_task": 2,
            "rubric_sha256": rubric_hash, "key_sha256": "a" * 64,
            "packet_hashes": {"t1": packet_hash}
        }
        index_hash = write(self.judging / "packets/index.json", json.dumps(index))
        self.template = [
            {"header": True, "judge": None, "session": None, "blind": True,
             "rubric_sha256": rubric_hash, "key_sha256": "a" * 64,
             "packets_index_sha256": index_hash},
            {"task_id": "t1", "label": "A", "output_ref": "o-a",
             "output_sha256": "b" * 64, "relevance": {"1": None, "2": None},
             "criteria": {key: None for key in judge.CRITERIA}, "note": ""},
            {"task_id": "t1", "label": "B", "output_ref": "o-b",
             "output_sha256": "c" * 64, "relevance": {},
             "criteria": None, "note": ""},
        ]
        write(self.judging / "scores.template.jsonl",
              "".join(json.dumps(row) + "\n" for row in self.template))
        self.good = {"scores": [
            {"label": "B", "criteria": None, "relevance": {}, "note": ""},
            {"label": "A", "criteria": {key: 4 for key in judge.CRITERIA},
             "relevance": {"1": 2, "2": 0}, "note": "Option 2 changes the sense"},
        ]}

    def fake(self, prompt, model):
        self.assertIn("PACKET:", prompt)
        self.assertIn("RUBRIC:", prompt)
        self.assertNotIn("candidate_id", prompt)
        self.assertEqual(model, "claude-explicit-test")
        return self.good, "test-session"

    def test_dry_run_checks_hashes_without_scoring(self):
        result = judge.run(self.judging, self.rubric, "claude-explicit-test", dry_run=True)
        self.assertEqual(result["blind_outputs"], 2)
        self.assertFalse((self.judging / "claude-progress").exists())

    def test_completed_scores_preserve_raw_references_and_session(self):
        result = judge.run(self.judging, self.rubric, "claude-explicit-test",
                           invoke=self.fake)
        self.assertTrue(result["wrote_scores"])
        rows = judge.load_jsonl(self.judging / "scores.jsonl")
        self.assertEqual([r.get("label") for r in rows[1:]], ["A", "B"])
        self.assertEqual(rows[1]["output_ref"], "o-a")
        self.assertEqual(rows[1]["relevance"], {"1": 2, "2": 0})
        self.assertIsNone(rows[2]["criteria"])
        self.assertTrue((self.judging / "claude-session-receipt.json").exists())
        with self.assertRaises(FileExistsError):
            judge.run(self.judging, self.rubric, "claude-explicit-test", invoke=self.fake)

    def test_wrong_labels_and_missing_options_are_rejected(self):
        incorrect = {"scores": [dict(self.good["scores"][0]),
                                dict(self.good["scores"][1], relevance={"1": 2})]}
        with self.assertRaisesRegex(ValueError, "indices"):
            judge.validate(incorrect, self.template[1:])
        incorrect["scores"][1]["relevance"] = {"1": 2, "2": 0}
        incorrect["scores"][1]["note"] = ""
        with self.assertRaisesRegex(ValueError, "reason"):
            judge.validate(incorrect, self.template[1:])
        incorrect["scores"][1]["note"] = "reason"
        incorrect["scores"][1]["relevance"]["2"] = True
        with self.assertRaisesRegex(ValueError, "0, 1 or 2"):
            judge.validate(incorrect, self.template[1:])

    def test_changed_packet_and_rubric_fail_before_judging(self):
        write(self.judging / "packets/t1.md", "tampered")
        with self.assertRaisesRegex(ValueError, "Packet changed"):
            judge.run(self.judging, self.rubric, "claude-explicit-test", invoke=self.fake)
        write(self.judging / "packets/t1.md",
              "## Output A\n1. sound\n2. unrelated\n## Output B\nNo options to judge.")
        write(self.rubric, "changed rubric")
        with self.assertRaisesRegex(ValueError, "commitment"):
            judge.run(self.judging, self.rubric, "claude-explicit-test", invoke=self.fake)

    def test_stale_model_checkpoint_cannot_be_reused(self):
        progress = self.judging / "claude-progress"
        write(progress / "t1.json",
              json.dumps({"model": "wrong-model", "packet_hash": "x", "scores": []}))
        with self.assertRaisesRegex(ValueError, "Stale checkpoint"):
            judge.run(self.judging, self.rubric, "claude-explicit-test", invoke=self.fake)


if __name__ == "__main__":
    unittest.main()
