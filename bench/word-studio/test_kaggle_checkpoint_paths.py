"""Regression coverage for the repo cleanup's Kaggle source identity paths."""
from __future__ import annotations

import inspect
import unittest

import kaggle_run_checkpoint as checkpoint


class KaggleCheckpointPathTests(unittest.TestCase):
    def test_runner_and_checkpoint_use_the_current_benchmark_root(self) -> None:
        expected = "bench/word-studio/"
        self.assertEqual(checkpoint.BENCHMARK_RELEVANT_PREFIX, expected)
        self.assertEqual(
            inspect.signature(checkpoint.verify_git_identity)
            .parameters["relevant_prefix"].default,
            expected,
        )

    def test_status_classification_only_trusts_current_benchmark_paths(self) -> None:
        lines = (
            " M bench/word-studio/run-kaggle-candidate.py",
            "?? bench/word-studio/new-source.py",
            "?? bench/word-studio/__pycache__/runner.pyc",
            "?? bench/word-studio/studio_backend/__pycache__/service.pyc",
            " M README.md",
            "?? open-local-phraser-v1/benchmarks/english-studio-v3/old.py",
            "?? bench/word-studio-old/near-miss.py",
        )

        self.assertEqual(
            checkpoint.classify_git_status(lines, "bench/word-studio/"),
            (
                " M bench/word-studio/run-kaggle-candidate.py",
                "?? bench/word-studio/new-source.py",
            ),
        )


if __name__ == "__main__":
    unittest.main()
