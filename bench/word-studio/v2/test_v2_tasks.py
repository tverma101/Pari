"""The frozen Word Studio v2 task sets match their source and manifest (#85)."""
from __future__ import annotations

import json
import unittest
from collections import Counter

from v2 import build_tasks, prompts


class FrozenTaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.sets = {name: build_tasks.load_tasks(name) for name in build_tasks.SET_FILES}

    def test_committed_files_match_a_fresh_build(self) -> None:
        self.assertEqual(build_tasks.main(["--check"]), 0)

    def test_sizes_and_kind_counts_follow_the_design(self) -> None:
        self.assertEqual(len(self.sets["screen"]), 40)
        self.assertEqual(len(self.sets["full"]), 200)
        for name, target in build_tasks.SET_TARGETS.items():
            self.assertEqual(dict(Counter(t["kind"] for t in self.sets[name])), target)

    def test_screen_and_full_share_no_paragraph_or_sentence(self) -> None:
        screen, full = self.sets["screen"], self.sets["full"]
        self.assertFalse({t["paragraph_id"] for t in screen} & {t["paragraph_id"] for t in full})
        self.assertFalse({t["paragraph"] for t in screen} & {t["paragraph"] for t in full})

    def test_ids_are_unique_and_selections_point_into_the_paragraph(self) -> None:
        tasks = self.sets["screen"] + self.sets["full"]
        self.assertEqual(len({t["id"] for t in tasks}), len(tasks))
        for task in tasks:
            sel = task["selection"]
            if task["kind"] == "word_sentences":
                self.assertIsNone(sel)
                self.assertTrue(task["word"])
                continue
            self.assertEqual(task["paragraph"][sel["start"]:sel["end"]], sel["text"], task["id"])
            self.assertIn(sel["text"], task["sentence"])

    def test_every_prompt_carries_the_paragraph_and_the_json_contract(self) -> None:
        for task in self.sets["screen"] + self.sets["full"]:
            system, user = task["messages"]
            self.assertEqual(system, {"role": "system", "content": prompts.SYSTEM})
            self.assertEqual(user["role"], "user")
            self.assertIn(task["paragraph"], user["content"])
            self.assertIn(f"Give {task['requested_options']} ", user["content"].replace("Write ", "Give "))
            if task["kind"] in prompts.SELECTION_KINDS:
                self.assertIn(f"[[{task['selection']['text']}]]", user["content"])
            self.assertEqual(task["prompt_version"], prompts.PROMPT_VERSION)

    def test_manifest_records_hashes_licence_and_reuse(self) -> None:
        manifest = json.loads(build_tasks.MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["source"]["license"], "CC0-1.0")
        self.assertTrue(manifest["reuse"]["reused"])
        self.assertTrue(manifest["reuse"]["not_reused"])
        for name, entry in manifest["sets"].items():
            data = (build_tasks.HERE / entry["path"]).read_bytes()
            self.assertEqual(build_tasks.sha256_bytes(data), entry["sha256"], name)


if __name__ == "__main__":
    unittest.main()
