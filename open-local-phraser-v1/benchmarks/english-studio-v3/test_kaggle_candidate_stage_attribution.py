#!/usr/bin/env python3
"""CPU-only checks for explicit failure-stage attribution in candidate wrappers."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent


def load_vllm_wrapper():
    spec = importlib.util.spec_from_file_location(
        "pari_test_vllm_candidate", HERE / "run-kaggle-vllm-candidate.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load vLLM candidate wrapper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def assert_all_classifier_calls_name_a_stage(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "classify"
    ]
    if not calls:
        raise AssertionError(f"no classify calls found in {path.name}")
    missing = [call.lineno for call in calls if not any(arg.arg == "stage" for arg in call.keywords)]
    if missing:
        raise AssertionError(f"classify calls without explicit stage in {path.name}: {missing}")


def main() -> None:
    vllm = load_vllm_wrapper()
    cases = [
        ("CUDA out of memory while initializing engine", "load", "cuda_oom_load"),
        ("CUDA out of memory; completed 0/16", "generate", "cuda_oom_generate"),
        ("RuntimeError: worker failed", "load", "unclassified_runtime_failure"),
    ]
    for text, expected_stage, expected_category in cases:
        stage, categories = vllm.classify_child_failure(text)
        assert stage == expected_stage, (stage, expected_stage, text)
        assert categories[0] == expected_category, (categories, expected_category, text)

    assert_all_classifier_calls_name_a_stage(HERE / "run-kaggle-vllm-candidate.py")
    assert_all_classifier_calls_name_a_stage(HERE / "run-kaggle-prism-candidate.py")
    print("Kaggle candidate stage-attribution tests passed (CPU only).")


if __name__ == "__main__":
    main()
