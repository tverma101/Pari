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
        "Unsupported model architecture QwenThingForConditionalGeneration": "unsupported_model_architecture",
        "Marlin quantization method is not supported on this GPU": "unsupported_quantization",
        "FlashInfer attention backend not supported for compute capability 7.5": "attention_backend_unsupported",
        "ptxas fatal: Unsupported .version 8.9; failed to compile Triton kernel": "triton_or_ptx_failure",
        "No module named flash_attn_2_cuda": "custom_cuda_op_missing",
        "bfloat16 is not supported on this GPU": "bf16_or_fp8_unsupported",
        "PyTorch was not compiled with CUDA enabled": "torch_cuda_binary_mismatch",
        "CUDA driver version is insufficient for CUDA runtime version": "cuda_driver_runtime_mismatch",
        "CUDNN_STATUS_NOT_SUPPORTED": "cudnn_failure",
        "GLIBCXX_3.4.32 not found": "native_library_or_abi_failure",
        "this wheel is not a supported wheel on this platform": "python_abi_mismatch",
        "Illegal instruction (core dumped)": "illegal_instruction",
        "ProcessGroupNCCL unhandled system error; P2P peer access failed": "tensor_parallel_failure",
        "CUDA graph capture failed": "cuda_graph_failure",
        "MTP speculative decoding unsupported for this architecture": "mtp_unsupported",
        "No chat template is defined for this tokenizer": "chat_template_failure",
        "trust_remote_code custom modeling code missing dependency modeling_foo": "remote_code_dependency_failure",
        "No space left on device": "disk_space_failure",
        "401 Unauthorized: access to model is restricted gated repo": "model_access_or_auth_failure",
        "429 Too Many Requests from model hub rate limit": "model_download_rate_limit",
        "Building wheel for flash-attn": "source_build_attempt_forbidden",
        "using CPU backend after CUDA init": "silent_cpu_fallback_detected",
        "requested sequence length exceeds context window": "context_length_config_failure",
        "bind failed: Address already in use": "server_port_conflict",
        "CUDA error: device-side assert triggered": "device_side_assert",
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
