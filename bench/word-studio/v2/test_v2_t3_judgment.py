from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from v2 import import_t3_judgment as importer


def write(path: Path, data: bytes | str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


class T3JudgmentImportTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.judging = self.root / "judging"
        rubric_sha = importer.sha(importer.RUBRIC)
        packet_hash = write(self.judging / "packets/task-1.md", "Output A\nOutput B\n")
        index = {"tasks": ["task-1"], "outputs_per_task": 2,
                 "rubric_sha256": rubric_sha, "key_sha256": "a" * 64,
                 "packet_hashes": {"task-1": packet_hash}}
        index_sha = write(self.judging / "packets/index.json", json.dumps(index))
        template = [
            {"header": True, "judge": None, "session": None, "blind": True,
             "rubric_sha256": rubric_sha, "key_sha256": "a" * 64,
             "packets_index_sha256": index_sha},
            {"task_id": "task-1", "label": "A", "output_ref": "out-a",
             "output_sha256": "b" * 64, "relevance": {"1": None, "2": None},
             "criteria": {name: None for name in importer.CRITERIA}, "note": ""},
            {"task_id": "task-1", "label": "B", "output_ref": "out-b",
             "output_sha256": "c" * 64, "relevance": {}, "criteria": None, "note": ""},
        ]
        write(self.judging / "scores.template.jsonl",
              "".join(json.dumps(row) + "\n" for row in template))
        self.answer = {"scores": [
            {"task_id": "task-1", "label": "A",
             "criteria": {name: 4 for name in importer.CRITERIA},
             "relevance": {"1": 2, "2": 0}, "note": "Option 2 changes the meaning."},
            {"task_id": "task-1", "label": "B", "criteria": None,
             "relevance": {}, "note": ""},
        ]}
        self.response = self.root / "response.json"
        write(self.response, json.dumps(self.answer))
        self.provenance = {"provider_instance_id": "provider-test",
                           "delegated_task_id": "delegated-task-test",
                           "child_run_id": "child-run-test"}

    def run_import(self, **kwargs):
        return importer.run(self.judging, self.response,
                            **(self.provenance | kwargs))

    def test_import_preserves_citations_and_binds_t3_receipt(self) -> None:
        result = self.run_import()
        self.assertTrue(result["wrote_scores"])
        rows = importer.load_jsonl(self.judging / "scores.jsonl")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["judge"], "gpt-6.1-sol")
        self.assertEqual(rows[0]["provider"], "t3-code")
        self.assertEqual(rows[0]["effort_level"], "high")
        self.assertEqual(rows[0]["service_tier"], "standard")
        self.assertEqual(rows[1]["output_ref"], "out-a")
        self.assertEqual(rows[1]["output_sha256"], "b" * 64)
        self.assertEqual(rows[1]["relevance"], {"1": 2, "2": 0})
        receipt = json.loads((self.judging / "judge-session-receipt.json").read_text())
        self.assertEqual(receipt["sessions"], {"task-1": "child-run-test"})
        self.assertEqual(receipt["packet_index_sha256"],
                         importer.sha(self.judging / "packets/index.json"))
        self.assertEqual(receipt["scores_sha256"], importer.sha(self.judging / "scores.jsonl"))
        self.assertEqual(receipt["input_sha256"], importer.sha(self.response))

    def test_dry_run_writes_no_scores_or_receipt(self) -> None:
        result = self.run_import(dry_run=True)
        self.assertFalse(result["wrote_scores"])
        self.assertFalse((self.judging / "scores.jsonl").exists())
        self.assertFalse((self.judging / "judge-session-receipt.json").exists())

    def test_rejects_incomplete_duplicate_or_identity_fields(self) -> None:
        bad = dict(self.answer)
        bad["scores"] = self.answer["scores"][:1]
        with self.assertRaisesRegex(ValueError, "missing or extra"):
            importer.validate(bad, importer.load_jsonl(self.judging / "scores.template.jsonl")[1:])
        bad = {"scores": [*self.answer["scores"], self.answer["scores"][0]]}
        with self.assertRaisesRegex(ValueError, "missing or extra"):
            importer.validate(bad, importer.load_jsonl(self.judging / "scores.template.jsonl")[1:])
        bad = json.loads(json.dumps(self.answer))
        bad["scores"][0]["candidate_id"] = "must-not-be-present"
        with self.assertRaisesRegex(ValueError, "only task_id"):
            importer.validate(bad, importer.load_jsonl(self.judging / "scores.template.jsonl")[1:])

    def test_rejects_invalid_labels_and_zero_without_note(self) -> None:
        bad = json.loads(json.dumps(self.answer))
        bad["scores"][0]["relevance"]["1"] = True
        with self.assertRaisesRegex(ValueError, "integer 0, 1 or 2"):
            importer.validate(bad, importer.load_jsonl(self.judging / "scores.template.jsonl")[1:])
        bad = json.loads(json.dumps(self.answer))
        bad["scores"][0]["note"] = ""
        with self.assertRaisesRegex(ValueError, "zero needs"):
            importer.validate(bad, importer.load_jsonl(self.judging / "scores.template.jsonl")[1:])

    def test_refuses_overwrite(self) -> None:
        self.run_import()
        with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
            self.run_import()


if __name__ == "__main__":
    unittest.main()
