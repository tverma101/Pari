#!/usr/bin/env python3
"""Regression tests for interrupted-run resume identity and prefix safety."""
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run-english-core-vllm.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("pari_vllm_runner", RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load vLLM runner module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(outputs):
    return {
        "model": {"repoOrName": "org/model", "revision": "a" * 40},
        "taskFileSha256": "b" * 64,
        "taskCount": 4,
        "promptModeRequested": "chat",
        "decoding": {
            "temperature": 0.0,
            "topP": 1.0,
            "topK": -1,
            "maxNewTokens": 220,
            "forcedChoiceMaxNewTokens": 8,
            "seed": 0,
            "batchSize": 2,
            "tensorParallelSize": 1,
            "dtype": "half",
            "languageModelOnly": True,
            "speculativeConfig": None,
        },
        "outputs": outputs,
        "reproducibility": {"benchmarkRevision": "deadbee"},
    }


def validate(module, run):
    return module.validate_resume(
        run,
        ids=["a", "b", "c", "d"],
        task_hash="b" * 64,
        model_repo="org/model",
        revision="a" * 40,
        prompt_mode="chat",
        expected_decoding={
            "temperature": 0.0,
            "topP": 1.0,
            "topK": -1,
            "maxNewTokens": 220,
            "forcedChoiceMaxNewTokens": 8,
            "seed": 0,
            "batchSize": 2,
            "tensorParallelSize": 1,
            "dtype": "half",
            "languageModelOnly": True,
            "speculativeConfig": None,
        },
        benchmark_revision="deadbee",
    )


def must_fail(fn, message: str) -> None:
    try:
        fn()
    except SystemExit:
        return
    raise AssertionError(message)


def main() -> None:
    module = load_runner()

    assert validate(module, fixture([])) == 0
    assert validate(module, fixture([{"id": "a"}])) == 1
    assert validate(module, fixture([{"id": "a"}, {"id": "b"}])) == 2
    assert validate(module, fixture([{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}])) == 4

    must_fail(lambda: validate(module, fixture([{"id": "b"}])), "non-prefix result was accepted")
    must_fail(lambda: validate(module, fixture([{"id": "a"}, {"id": "a"}])), "duplicate IDs were accepted")
    must_fail(lambda: validate(module, fixture([{"id": "a"}, {"id": "c"}])), "gapped prefix was accepted")

    wrong_model = fixture([{"id": "a"}])
    wrong_model["model"]["revision"] = "c" * 40
    must_fail(lambda: validate(module, wrong_model), "changed model revision was accepted")

    wrong_decode = fixture([{"id": "a"}])
    wrong_decode["decoding"]["batchSize"] = 1
    must_fail(lambda: validate(module, wrong_decode), "changed batch size was accepted")

    wrong_benchmark = fixture([{"id": "a"}])
    wrong_benchmark["reproducibility"]["benchmarkRevision"] = "cafef00"
    must_fail(lambda: validate(module, wrong_benchmark), "changed benchmark revision was accepted")

    print("Resume contract regression tests passed.")


if __name__ == "__main__":
    main()
