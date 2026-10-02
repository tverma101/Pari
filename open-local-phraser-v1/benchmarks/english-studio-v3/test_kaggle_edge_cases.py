#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from kaggle_failure_taxonomy import classify
from word_studio_output_parser import diagnose, parse_options

HERE = Path(__file__).resolve().parent


def test_word_studio_parser() -> None:
    good_json = '{"options":["clear","easy to follow","straightforward","simple","understandable","plain","easy","accessible","readable","uncomplicated"]}'
    options, mode = parse_options(good_json)
    assert mode == "json_object" and len(options) == 10

    numbered = "\n".join(f"{i}. option {i}" for i in range(1, 11))
    options, mode = parse_options(numbered)
    assert mode == "numbered_or_bulleted_list" and len(options) == 10

    prose = "Here are ten great alternatives:\n1. one\n2. two"
    options, mode = parse_options(prose)
    assert mode == "unparseable" and options == []

    diag = diagnose('{"options":["same","same","different"]}', source="same", requested=10)
    assert "word_studio_too_few_candidates" in diag["statuses"]
    assert "word_studio_excessive_duplicates" in diag["statuses"]
    assert "contains_unchanged_source" in diag["statuses"]


def test_failure_classifier() -> None:
    cases = {
        "CUDA out of memory while loading model weights": "cuda_oom_load",
        "CUDA out of memory during generation while allocating KV cache": "cuda_oom_generate",
        "RuntimeError: no kernel image is available for execution on the device": "unsupported_kernel",
        "This kernel requires Ampere sm_80 but device is sm_75": "unsupported_compute_capability",
        "CUDA driver version is insufficient for CUDA runtime version": "cuda_driver_runtime_mismatch",
        "GLIBCXX_3.4.32 not found": "native_library_or_abi_failure",
        "ProcessGroupNCCL unhandled system error; P2P peer access failed": "tensor_parallel_failure",
        "MTP speculative decoding unsupported for this architecture": "mtp_unsupported",
        "Building wheel for flash-attn": "source_build_attempt_forbidden",
        "using CPU backend after CUDA init": "silent_cpu_fallback_detected",
    }
    for text, expected in cases.items():
        hits = classify(text)
        assert expected in hits, (text, expected, hits)


def test_prebuilt_registry() -> None:
    registry = json.loads((HERE / "kaggle-prebuilt-runtimes.json").read_text(encoding="utf-8"))
    assert registry["policy"]["sourceBuildDefault"] == "forbidden"
    ids = [row["id"] for row in registry["artifacts"]]
    assert len(ids) == len(set(ids))
    for row in registry["artifacts"]:
        assert row["url"].startswith("https://github.com/")
        digest = row["sha256"]
        assert len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest.lower())


def main() -> None:
    test_word_studio_parser()
    test_failure_classifier()
    test_prebuilt_registry()
    print("Kaggle/T4 edge-case regression tests passed.")


if __name__ == "__main__":
    main()
