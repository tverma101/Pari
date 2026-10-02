#!/usr/bin/env python3
"""Deterministic coarse failure classifier for Kaggle/T4 benchmark attempts.

Classification is diagnostic only. It never changes prompts, retries content, or
turns infrastructure failure into an English score.
"""
from __future__ import annotations

import re
from typing import Iterable

RULES: list[tuple[str, tuple[str, ...]]] = [
    ("cuda_oom_load", ("cuda out of memory", "outofmemoryerror", "while loading", "allocate memory")),
    ("cuda_oom_generate", ("cuda out of memory", "outofmemoryerror", "during generation", "kv cache")),
    ("unsupported_compute_capability", ("compute capability", "sm_75", "sm75", "requires sm_80", "requires ampere", "unsupported gpu architecture")),
    ("unsupported_quantization", ("unsupported quantization", "quantization method", "gptq.*not supported", "awq.*not supported", "marlin.*not supported", "bitsandbytes.*not supported")),
    ("unsupported_kernel", ("no kernel image is available", "invalid device function", "cutlass", "flashinfer", "flash attention", "flash_attn", "triton.*unsupported", "fused.*kernel")),
    ("bf16_or_fp8_unsupported", ("bfloat16", "bf16", "fp8", "float8", "not supported on this gpu")),
    ("cuda_driver_runtime_mismatch", ("cuda driver version is insufficient", "driver/library version mismatch", "libcuda", "cuda error 35", "unsupported cuda version")),
    ("native_library_or_abi_failure", ("glibc_", "glibcxx_", "version .* not found", "undefined symbol", "cannot open shared object file", "ldd", "symbol lookup error")),
    ("tensor_parallel_failure", ("nccl", "tensor parallel", "peer access", "p2p", "unhandled system error", "connection closed by peer", "processgroupnccl")),
    ("mtp_unsupported", ("speculative.*unsupported", "mtp.*unsupported", "qwen3_next_mtp.*unsupported", "no speculative", "draft model.*unsupported")),
    ("mtp_runtime_failure", ("speculative", "mtp", "draft tokens", "acceptance") ),
    ("tokenizer_load_failure", ("tokenizer", "sentencepiece", "tokenizers", "failed to load tokenizer", "vocab")),
    ("chat_template_failure", ("chat template", "apply_chat_template", "template.*undefined", "no chat template")),
    ("model_download_failure", ("huggingface", "connectionerror", "readtimeout", "download", "403", "404", "snapshot_download")),
    ("artifact_hash_mismatch", ("sha256 mismatch", "hash mismatch", "checksum")),
    ("runtime_import_failure", ("modulenotfounderror", "importerror", "failed to import", "cannot import name")),
    ("dependency_install_failure", ("could not find a version that satisfies", "no matching distribution found", "resolutionimpossible", "pip subprocess")),
    ("source_build_attempt_forbidden", ("building wheel for", "cmake", "ninja", "nvcc", "bdist_wheel", "cargo build", "setup.py build")),
    ("silent_cpu_fallback_detected", ("device=cpu", "using cpu", "cpu backend", "offloaded to cpu", "gpu layers: 0")),
    ("gpu_offload_unverified", ("offload.*unverified", "no cuda offload evidence", "gpu placement unverified")),
    ("generation_timeout", ("timeoutexpired", "timed out", "deadline exceeded", "request timeout")),
    ("runtime_crash", ("segmentation fault", "core dumped", "killed", "sigsegv", "sigabrt", "worker died", "engine dead")),
    ("kaggle_session_or_control_plane_failure", ("kaggle", "kernel.*error", "session.*stopped", "accelerator.*unavailable", "control plane")),
    ("model_load_failure", ("failed to load model", "error loading model", "model load", "safetensors", "gguf")),
]


def classify(text: str) -> list[str]:
    s = str(text or "").lower()
    hits: list[str] = []
    for category, patterns in RULES:
        if any(re.search(pattern, s, flags=re.I | re.S) for pattern in patterns):
            hits.append(category)
    # Refine generic OOM when context is available; preserve both only if truly ambiguous.
    if "cuda_oom_load" in hits and "cuda_oom_generate" in hits:
        if any(x in s for x in ("loading model", "load model", "initializing engine", "profile_run")):
            hits.remove("cuda_oom_generate")
        elif any(x in s for x in ("generate", "generation", "kv cache", "request")):
            hits.remove("cuda_oom_load")
    return hits or ["unclassified_runtime_failure"]


def primary(text: str) -> str:
    return classify(text)[0]


if __name__ == "__main__":
    import argparse, json
    from pathlib import Path
    ap = argparse.ArgumentParser()
    ap.add_argument("log", type=Path)
    args = ap.parse_args()
    text = args.log.read_text(encoding="utf-8", errors="replace")
    print(json.dumps({"primary": primary(text), "all": classify(text)}, indent=2))
