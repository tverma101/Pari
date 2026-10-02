#!/usr/bin/env python3
"""Deterministic coarse failure classifier for Kaggle/T4 benchmark attempts.

Classification is diagnostic only. It never changes prompts, retries content, or
turns infrastructure failure into an English score.
"""
from __future__ import annotations

import re

RULES: list[tuple[str, tuple[str, ...]]] = [
    ("disk_space_failure", ("no space left on device", "disk quota exceeded", "errno 28", "not enough space")),
    ("model_access_or_auth_failure", ("gated repo", "gated repository", "401 unauthorized", "authentication required", "access to model .* restricted")),
    ("model_download_rate_limit", ("429 too many requests", "rate limit", "ratelimit")),
    ("model_download_failure", ("huggingface", "connectionerror", "readtimeout", "download", "403", "404", "snapshot_download", "sslerror", "certificate verify failed")),
    ("artifact_hash_mismatch", ("sha256 mismatch", "hash mismatch", "checksum", "safetensors header too large", "metadata incomplete buffer")),
    ("cuda_oom_load", ("cuda out of memory", "outofmemoryerror", "while loading", "allocate memory", "initializing engine", "profile_run")),
    ("cuda_oom_generate", ("cuda out of memory", "outofmemoryerror", "during generation", "kv cache", "failed to allocate kv")),
    ("cuda_memory_fragmentation", ("reserved memory is >> allocated memory", "expandable_segments", "memory fragmentation", "fragmented")),
    ("device_side_assert", ("device-side assert triggered", "cuda error: device-side assert", "device side assert")),
    ("unsupported_compute_capability", ("compute capability", "sm_75", "sm75", "requires sm_80", "requires ampere", "unsupported gpu architecture", "minimum capability")),
    ("unsupported_model_architecture", ("model architecture .* not supported", "unsupported architecture", "architectures .* unsupported", "model type .* not recognized", "unknown model architecture")),
    ("unsupported_quantization", ("unsupported quantization", "quantization method", "gptq.*not supported", "awq.*not supported", "marlin.*not supported", "bitsandbytes.*not supported", "quantization config.*unsupported")),
    ("unsupported_kernel", ("no kernel image is available", "invalid device function", "cutlass", "fused.*kernel", "kernel.*not supported")),
    ("attention_backend_unsupported", ("flashinfer", "flash attention", "flash_attn", "flashattention", "xformers", "attention backend.*not supported", "cannot use flash")),
    ("triton_or_ptx_failure", ("triton.*unsupported", "ptx.*unsupported", "ptxas fatal", "unsupported ptx version", "triton compilation", "failed to compile triton")),
    ("custom_cuda_op_missing", ("no module named .*cuda", "undefined symbol.*cuda", "custom op.*not found", "operator .* does not exist", "torch.ops.*not found")),
    ("bf16_or_fp8_unsupported", ("bfloat16", "bf16", "fp8", "float8", "not supported on this gpu", "requires.*fp8")),
    ("torch_cuda_binary_mismatch", ("torch.*cuda", "compiled with cuda", "not compiled with cuda", "cuda version mismatch", "pytorch.*cuda.*mismatch")),
    ("cuda_driver_runtime_mismatch", ("cuda driver version is insufficient", "driver/library version mismatch", "libcuda", "cuda error 35", "unsupported cuda version", "forward compatibility was attempted")),
    ("cudnn_failure", ("cudnn_status", "could not load libcudnn", "cudnn.*not supported")),
    ("native_library_or_abi_failure", ("glibc_", "glibcxx_", "version .* not found", "undefined symbol", "cannot open shared object file", "ldd", "symbol lookup error")),
    ("python_abi_mismatch", ("wrong elf class", "invalid elf header", "python abi", "cp3.*not compatible", "not a supported wheel on this platform")),
    ("illegal_instruction", ("illegal instruction", "sigill")),
    ("tensor_parallel_failure", ("nccl", "tensor parallel", "peer access", "p2p", "unhandled system error", "connection closed by peer", "processgroupnccl", "duplicate gpu detected")),
    ("cuda_graph_failure", ("cuda graph", "cudagraph", "graph capture", "capture failed")),
    ("mtp_unsupported", ("speculative.*unsupported", "mtp.*unsupported", "qwen3_next_mtp.*unsupported", "no speculative", "draft model.*unsupported")),
    ("mtp_runtime_failure", ("speculative", "mtp", "draft tokens", "acceptance")),
    ("tokenizer_load_failure", ("tokenizer", "sentencepiece", "tokenizers", "failed to load tokenizer", "vocab", "protobuf")),
    ("chat_template_failure", ("chat template", "apply_chat_template", "template.*undefined", "no chat template", "jinja")),
    ("remote_code_dependency_failure", ("trust_remote_code", "remote code", "requires you to execute", "custom modeling code", "missing dependency.*modeling")),
    ("runtime_import_failure", ("modulenotfounderror", "importerror", "failed to import", "cannot import name")),
    ("dependency_install_failure", ("could not find a version that satisfies", "no matching distribution found", "resolutionimpossible", "pip subprocess", "dependency conflict")),
    ("source_build_attempt_forbidden", ("building wheel for", "cmake", "ninja", "nvcc", "bdist_wheel", "cargo build", "setup.py build", "compiling extension", "build_ext")),
    ("silent_cpu_fallback_detected", ("device=cpu", "using cpu", "cpu backend", "offloaded to cpu", "gpu layers: 0", "0 layers offloaded")),
    ("gpu_offload_unverified", ("offload.*unverified", "no cuda offload evidence", "gpu placement unverified")),
    ("context_length_config_failure", ("max model len", "max_model_len", "context length", "context window", "requested tokens.*exceed", "sequence length.*exceed")),
    ("server_port_conflict", ("address already in use", "errno 98", "failed to bind", "port .* in use")),
    ("generation_timeout", ("timeoutexpired", "timed out", "deadline exceeded", "request timeout", "read timed out")),
    ("runtime_crash", ("segmentation fault", "core dumped", "killed", "sigsegv", "sigabrt", "worker died", "engine dead", "enginecore.*failed", "child process failed")),
    ("kaggle_session_or_control_plane_failure", ("kaggle", "kernel.*error", "session.*stopped", "accelerator.*unavailable", "control plane", "kernel died")),
    ("model_load_failure", ("failed to load model", "error loading model", "model load", "safetensors", "gguf", "failed to mmap")),
]


def classify(text: str) -> list[str]:
    s = str(text or "").lower()
    hits: list[str] = []
    for category, patterns in RULES:
        if any(re.search(pattern, s, flags=re.I | re.S) for pattern in patterns):
            hits.append(category)
    if "cuda_oom_load" in hits and "cuda_oom_generate" in hits:
        if any(x in s for x in ("loading model", "load model", "initializing engine", "profile_run")):
            hits.remove("cuda_oom_generate")
        elif any(x in s for x in ("generate", "generation", "kv cache", "request")):
            hits.remove("cuda_oom_load")
    # A specific download/auth/rate-limit classification is more informative than
    # the broad model_download_failure hit caused by generic HTTP text.
    if "model_download_failure" in hits and any(
        x in hits for x in ("model_access_or_auth_failure", "model_download_rate_limit", "artifact_hash_mismatch")
    ):
        hits.remove("model_download_failure")
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
