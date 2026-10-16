"""The Kaggle kernel is filled in correctly and records crashes as failures (#86)."""
from __future__ import annotations

import ast
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

KAGGLE = Path(__file__).resolve().parents[3] / "kaggle" / "word-studio"


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"kaggle_ws_{name}", KAGGLE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class KaggleKernelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_launch_fills_config_and_metadata(self) -> None:
        launch = load("launch")
        config = {"run_id": "r1", "repo_url": launch.REPO_URL, "git_sha": "a" * 40, "task_set": "screen",
                  "candidates": ["qwen35-4b"], "pip": launch.PIP, "per_candidate_timeout_s": 60, "limit": None}
        folder = launch.build_kernel(self.dir / "k", config, "someone")
        source = (folder / "kernel.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertNotIn(launch.CONFIG_LINE, source)
        namespace: dict = {}
        exec(compile(source.split("\nWORK = ")[0], "kernel.py", "exec"), namespace)
        self.assertEqual(namespace["CONFIG"], config)
        meta = json.loads((folder / "kernel-metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["id"], "someone/pari-word-studio-v2")
        self.assertTrue(meta["is_private"])
        self.assertTrue(meta["enable_gpu"] and meta["enable_internet"])
        self.assertEqual(meta["machine_shape"], "NvidiaTeslaT4")

    def test_every_listed_candidate_is_known(self) -> None:
        launch = load("launch")
        known = launch.known_candidates()
        self.assertIn("control-missing-revision", known)
        self.assertIn("qwen35-4b", known)

    def test_launch_refuses_runs_longer_than_a_kaggle_session(self) -> None:
        launch = load("launch")
        with self.assertRaises(SystemExit) as caught:
            launch.main(["--set", "screen", "--candidates", "qwen35-2b,qwen35-4b,smollm3-3b",
                         "--timeout-s", "20000", "--dry-run"])
        self.assertIn("12-hour session", str(caught.exception))

    def test_unfilled_kernel_refuses_to_run(self) -> None:
        kernel = load("kernel")
        with self.assertRaises(SystemExit):
            kernel.main()

    def test_mark_failed_records_a_crash_once(self) -> None:
        kernel = load("kernel")
        run_json = self.dir / "cand" / "run.json"
        kernel.mark_failed(run_json, "timed out after 60 s")
        record = json.loads(run_json.read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["error"]["type"], "ProcessExit")
        self.assertEqual(record["candidate"]["candidate_id"], "cand")
        done = {"status": "completed", "tasks": {"ok": 40}}
        run_json.write_text(json.dumps(done), encoding="utf-8")
        kernel.mark_failed(run_json, "late kill")
        self.assertEqual(json.loads(run_json.read_text(encoding="utf-8")), done)

    def test_running_record_becomes_failed(self) -> None:
        kernel = load("kernel")
        run_json = self.dir / "cand" / "run.json"
        run_json.parent.mkdir(parents=True)
        run_json.write_text(json.dumps({"status": "running", "stage": "generate"}), encoding="utf-8")
        kernel.mark_failed(run_json, "run_candidate exited with code -9")
        record = json.loads(run_json.read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["stage"], "generate")
        self.assertIn("-9", record["error"]["message"])


if __name__ == "__main__":
    unittest.main()
