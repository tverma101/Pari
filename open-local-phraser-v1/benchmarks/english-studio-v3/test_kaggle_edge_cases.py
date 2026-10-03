#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from kaggle_failure_taxonomy import STAGES, classify, primary
from word_studio_output_parser import diagnose, parse_options, partial_candidate_count

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

    # requested=10 treats >2 duplicate entries as excessive. Make the fixture
    # cross that declared threshold rather than expecting one duplicate to fail.
    diag = diagnose('{"options":["same","same","same","same","different"]}', source="same", requested=10)
    assert "word_studio_too_few_candidates" in diag["statuses"]
    assert "word_studio_excessive_duplicates" in diag["statuses"]
    assert "contains_unchanged_source" in diag["statuses"]
    assert diag["duplicateCount"] == 3

    assert partial_candidate_count('{"options":["one","two","thr') == 2
    assert partial_candidate_count('{"options":["one","two","three"]') == 3
    assert partial_candidate_count("1. one\n2. two\n3. three") == 3
    assert partial_candidate_count("Here are options:\n1. one\n2. two") == 0


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


def test_failure_classifier_architecture() -> None:
    # Real upstream messages, not paraphrases:
    #   transformers models/auto/configuration_auto.py ("does not recognize this
    #   architecture"), vLLM vllm/model_executor/models/registry.py ("Model
    #   architectures [...] are not supported for now." and the removed-arch
    #   variant), llama.cpp src/llama-model.cpp ("unsupported/unknown model
    #   architecture").
    cases = {
        "Unsupported model architecture QwenThingForConditionalGeneration": "unsupported_model_architecture",
        "ValueError: Model architectures ['Qwen3NextForCausalLM'] are not supported for now. "
        "Supported architectures: ['LlamaForCausalLM', 'Qwen2ForCausalLM']": "unsupported_model_architecture",
        "Model architecture Qwen3NextForCausalLM was supported in vLLM until v0.11.0, "
        "and is not supported anymore.": "unsupported_model_architecture",
        "The checkpoint you are trying to load has model type `qwen3_thing` but "
        "Transformers does not recognize this architecture.": "unsupported_model_architecture",
        "llama_model_load: error: unsupported model architecture: 'llama4'": "unsupported_model_architecture",
        "llama_model_load: error: unknown model architecture: 'qwen4'": "unsupported_model_architecture",
        "The model type `foo` is not recognized": "unsupported_model_architecture",
    }
    for text, expected in cases.items():
        hits = classify(text)
        assert expected in hits, (text, expected, hits)
        assert primary(text) == expected, (text, primary(text), hits)

    # Ambiguous or unrelated failures must not be relabelled as architecture
    # failures; these stay unclassified or keep their own specific category.
    not_architecture = {
        # A vLLM "Supported architectures:" list carries no unsupported signal.
        "Supported architectures: ['LlamaForCausalLM', 'Qwen2ForCausalLM']": "unclassified_runtime_failure",
        # "architecture" in one traceback line, unrelated failure in another:
        # the old unbounded `.*` gap paired these and mislabelled the log.
        # #53 regression: speculation that is *rejected* is `mtp_unsupported`,
        # matching the pre-existing fixture at the top of this file, not
        # `mtp_runtime_failure` (which now needs a real runtime fault).
        "Resolved model architecture for /kaggle/input/weights\n"
        "ValueError: Speculative decoding is not supported for this model": "mtp_unsupported",
        "Model architecture: LlamaForCausalLM\n"
        "ValueError: The current GGUF file is k-quants, and quantization method "
        "k_quants is not supported": "unsupported_quantization",
        "This kernel requires Ampere sm_80 but device is sm_75": "unsupported_compute_capability",
        "Marlin quantization method is not supported on this GPU": "unsupported_quantization",
        # llama.cpp feature gap, not an unsupported architecture.
        "LLAMA_SPLIT_MODE_TENSOR not implemented for architecture 'llama3'": "unclassified_runtime_failure",
    }
    for text, expected in not_architecture.items():
        hits = classify(text)
        assert "unsupported_model_architecture" not in hits, (text, hits)
        assert primary(text) == expected, (text, primary(text), hits)


#: Issue #53, adversarial fixture list 1-7: informational log vocabulary must
#: not become a failure category.
INFORMATIONAL_NEGATIVES = {
    # 1. a /kaggle/... traceback path is not a control-plane failure
    "kaggle_session_or_control_plane_failure": (
        'Traceback (most recent call last):\n'
        '  File "/kaggle/working/bench/run_candidate.py", line 118, in <module>\n'
        "    total = measured / 0\n"
        "ZeroDivisionError: division by zero"
    ),
    # 2. a device inventory line is not an unsupported-GPU failure
    "unsupported_compute_capability": (
        "NVIDIA Tesla T4, compute capability 7.5, total memory 15360 MiB\n"
        "ValueError: tokenizer vocab file not found"
    ),
    # 3. a selected attention backend is not an unsupported-backend failure
    "attention_backend_unsupported": (
        "INFO Using FlashInfer attention backend\n"
        "CUDA out of memory during generation"
    ),
    # 4. a reported dtype is not an unsupported-dtype failure
    "bf16_or_fp8_unsupported": (
        "Loading model weights, dtype=bf16\n"
        "FileNotFoundError: [Errno 2] No such file or directory: 'config.json'"
    ),
    # 5. successful NCCL init is not a tensor-parallel failure
    "tensor_parallel_failure": (
        "INFO NCCL initialized, rank 0 of 2\n"
        "ValueError: failed to load tokenizer: vocab.json is missing"
    ),
    # 6. an informational MTP acceptance line is not an MTP runtime failure
    "mtp_runtime_failure": (
        "MTP enabled, acceptance=0.7\n"
        "OSError: [Errno 28] No space left on device"
    ),
    # 7. tokenizer metadata is not a tokenizer load failure
    "tokenizer_load_failure": (
        "tokenizer: LlamaTokenizerFast, vocab size 128000\n"
        "CUDA out of memory while loading model weights"
    ),
}

#: Issue #53, adversarial fixture list 8-12 plus the genuine failures for the
#: same categories, which the tightening must not erase.
INFORMATIONAL_POSITIVES = {
    # 8. a real sm_80 requirement on a T4
    "unsupported_compute_capability": "RuntimeError: this kernel requires Ampere sm_80 but the device is sm_75",
    # 9. a real load-stage OOM
    "cuda_oom_load": "torch.OutOfMemoryError: CUDA out of memory while initializing engine",
    # 10. a real generation-stage OOM
    "cuda_oom_generate": "torch.OutOfMemoryError: CUDA out of memory during generation: failed to allocate KV cache",
    # 11. a real Kaggle accelerator/session shutdown
    "kaggle_session_or_control_plane_failure": (
        "KaggleError: your accelerator has been disabled; the notebook session was stopped"
    ),
    # 12. a real missing torch operator, with no spurious GPU category
    "custom_cuda_op_missing": "RuntimeError: Operator torch.ops.aten._scaled_mm does not exist",
    # genuine failures for the categories the negatives above suppress
    "tokenizer_load_failure": "OSError: failed to load tokenizer: vocab.json is missing",
    "tensor_parallel_failure": "RuntimeError: NCCL error: unhandled system error",
    "mtp_runtime_failure": "RuntimeError: speculative decoding failed: draft model produced invalid tokens",
    "mtp_unsupported": "ValueError: speculative decoding is not supported for this model",
    "attention_backend_unsupported": "ImportError: flash_attn is not supported on this build",
    "bf16_or_fp8_unsupported": "ValueError: bfloat16 is not supported on this GPU",
}

#: Categories that must never co-occur with a real load/generation OOM. The OOM
#: categories themselves are deliberately absent: they are the expected answer.
NO_SPURIOUS_GPU_CATEGORIES = {
    "custom_cuda_op_missing", "unsupported_compute_capability",
    "attention_backend_unsupported", "bf16_or_fp8_unsupported",
    "tensor_parallel_failure", "kaggle_session_or_control_plane_failure",
    "torch_cuda_binary_mismatch", "cuda_driver_runtime_mismatch",
    "unsupported_model_architecture", "unsupported_quantization",
    "unsupported_kernel", "tokenizer_load_failure", "runtime_crash",
}


def test_failure_classifier_informational_negatives() -> None:
    """Bare environment/log vocabulary must not become a failure category."""
    for category, log in INFORMATIONAL_NEGATIVES.items():
        hits = classify(log)
        assert category not in hits, (category, log, hits)


def test_failure_classifier_informational_positives() -> None:
    """Genuine failure evidence for the same categories is still detected."""
    for category, log in INFORMATIONAL_POSITIVES.items():
        hits = classify(log)
        assert category in hits, (category, log, hits)


def test_failure_classifier_no_spurious_gpu_categories() -> None:
    """A missing torch operator stays an op failure, not a GPU failure."""
    hits = classify(INFORMATIONAL_POSITIVES["custom_cuda_op_missing"])
    assert hits == ["custom_cuda_op_missing"], hits

    # The #1 /kaggle path fixture must not invent anything either.
    path_only = classify(INFORMATIONAL_NEGATIVES["kaggle_session_or_control_plane_failure"])
    assert path_only == ["unclassified_runtime_failure"], path_only

    # A real OOM is one category and one category only. "torch" followed by
    # "CUDA" is not a torch/CUDA build mismatch, and an OOM is not a crash.
    assert classify(INFORMATIONAL_POSITIVES["cuda_oom_load"]) == ["cuda_oom_load"]
    assert classify(INFORMATIONAL_POSITIVES["cuda_oom_generate"]) == ["cuda_oom_generate"]
    for log in (
        INFORMATIONAL_POSITIVES["cuda_oom_load"],
        INFORMATIONAL_POSITIVES["cuda_oom_generate"],
    ):
        leaked = set(classify(log)) & NO_SPURIOUS_GPU_CATEGORIES
        assert not leaked, (log, leaked)

    # #11 must not also claim a torch/CUDA build or dtype mismatch.
    assert classify(INFORMATIONAL_POSITIVES["kaggle_session_or_control_plane_failure"]) == [
        "kaggle_session_or_control_plane_failure"
    ]


def test_failure_classifier_oom_stage_attribution() -> None:
    """Real OOM signal required, then load-vs-generate attributed by stage."""
    assert primary("CUDA out of memory while initializing engine") == "cuda_oom_load"
    assert primary(
        "CUDA out of memory during generation: failed to allocate KV cache"
    ) == "cuda_oom_generate"

    # A bare stage word with no OOM signal is not an OOM at all.
    no_signal = "KV cache warmup complete; while loading the next shard"
    assert "cuda_oom_load" not in classify(no_signal)
    assert "cuda_oom_generate" not in classify(no_signal)

    # Declared stage overrides ambiguous log wording (both stage words present).
    ambiguous = "CUDA out of memory while loading during generation"
    assert classify(ambiguous, stage="load") == ["cuda_oom_load"]
    assert classify(ambiguous, stage="generate") == ["cuda_oom_generate"]

    # Declared stage never invents an OOM out of a healthy log.
    healthy = "INFO NCCL initialized, dtype=bf16, compute capability 7.5"
    for stage in STAGES:
        assert "cuda_oom_load" not in classify(healthy, stage=stage), stage
        assert "cuda_oom_generate" not in classify(healthy, stage=stage), stage

    # install/download/server_start/cleanup attribute an OOM to load, since model
    # construction happens before any request can be served.
    for stage in ("install", "download", "server_start", "cleanup"):
        assert classify("CUDA out of memory", stage=stage) == ["cuda_oom_load"], stage

    # An unknown stage is rejected loudly rather than silently ignored.
    try:
        classify("CUDA out of memory", stage="not_a_stage")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown stage must raise ValueError")


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
    test_failure_classifier_architecture()
    test_failure_classifier_informational_negatives()
    test_failure_classifier_informational_positives()
    test_failure_classifier_no_spurious_gpu_categories()
    test_failure_classifier_oom_stage_attribution()
    test_prebuilt_registry()
    print("Kaggle/T4 edge-case regression tests passed.")


if __name__ == "__main__":
    main()
