#!/usr/bin/env python3
"""Deterministic coarse failure classifier for Kaggle/T4 benchmark attempts.

Classification is diagnostic only. It never changes prompts, retries content, or
turns infrastructure failure into an English score.

Wrappers often classify the whole stdout/stderr of a failed attempt, so a bare
environment name ("NCCL initialized", "dtype=bf16", "compute capability 7.5",
"MTP enabled", "/kaggle/working/foo.py") must never on its own become a failure
category. Those categories use subject+signal patterns in ``RULES`` that must
both match on one log line; categories whose vocabulary cannot collide keep
plain keyword patterns.

``classify(text, stage=...)`` accepts the stage the caller already knows
(``install``, ``download``, ``load``, ``server_start``, ``generate``,
``cleanup``) and uses it to attribute load-vs-generation OOM instead of guessing.
``stage`` is optional and purely refining, so callers that pass only a log keep
working unchanged.
"""
from __future__ import annotations

import re

# Sentence-bounded gap used by the architecture rule. Matching is done with
# re.S, so a bare `.*` can pair an "architecture" mention in one traceback line
# with a "not supported" phrase from an unrelated failure further down the log,
# and a bare "architecture" match would swallow compute-capability,
# quantization and attention-backend failures.
_ARCH_GAP = r"[^.\n]{0,120}"

#: Shorter sentence-bounded gap for the evidence rules. Bounded to one sentence
#: on purpose: an evidence rule must see its subject and its failure signal
#: together, never thousands of lines apart in the same concatenated log.
_EG = r"[^.\n]{0,80}"

#: Execution stages a caller may declare. ``stage`` only refines attribution; it
#: never turns a log that lacks failure evidence into a failure.
STAGES = (
    "install",
    "download",
    "load",
    "server_start",
    "generate",
    "cleanup",
)

RULES: list[tuple[str, tuple[str, ...]]] = [
    ("disk_space_failure", ("no space left on device", "disk quota exceeded", "errno 28", "not enough space")),
    ("model_access_or_auth_failure", ("gated repo", "gated repository", "401 unauthorized", "authentication required", "access to model .* restricted")),
    ("model_download_rate_limit", ("429 too many requests", "rate limit", "ratelimit")),
    ("model_download_failure", ("huggingface", "connectionerror", "readtimeout", "download", "403", "404", "snapshot_download", "sslerror", "certificate verify failed")),
    ("artifact_hash_mismatch", ("sha256 mismatch", "hash mismatch", "checksum", "safetensors header too large", "metadata incomplete buffer")),
    # OOM load/generate are derived by `_oom_stage`, which needs a real
    # allocation-failure signal before it looks at stage wording. Bare tokens
    # such as "while loading", "allocate memory", "profile_run" and "kv cache"
    # used to live here and matched healthy logs, so these entries are empty and
    # their position in RULES only fixes precedence (OOM outranks the generic
    # runtime categories below).
    ("cuda_oom_load", ()),
    ("cuda_oom_generate", ()),
    ("cuda_memory_fragmentation", ("reserved memory is >> allocated memory", "expandable_segments", "memory fragmentation", "fragmented")),
    ("device_side_assert", ("device-side assert triggered", "cuda error: device-side assert", "device side assert")),
    # A bare "compute capability 7.5" / "sm_75" is normal T4 inventory. These
    # patterns each require a failure verb attached to the device requirement.
    ("unsupported_compute_capability", (
        f"requires?{_EG}(sm_|compute capability|ampere|volta|turing|hopper|ada)",
        f"unsupported (gpu|compute) capability",
        f"unsupported gpu architecture",
        f"unsupported compute capability",
        f"minimum capability",
        f"(device )?capability{_EG}(is )?(not |too )(supported|low|insufficient)",
    )),
    # Verbatim upstream shapes this must cover:
    #   transformers AutoConfig: "... but Transformers does not recognize this
    #     architecture."
    #   vLLM registry: "Model architectures [...] are not supported for now."
    #     and "Model architecture X was supported in vLLM until v0.11, and is not
    #     supported anymore."
    #   llama.cpp: "unsupported model architecture: 'llama4'" / "unknown model
    #     architecture: 'X'".
    ("unsupported_model_architecture", (
        "does not recognize this architecture",
        "unsupported model architecture",
        "unknown model architecture",
        "unsupported architecture",
        f"model architectures?{_ARCH_GAP}(not supported|unsupported|not recognized|unrecognized|unknown|not implemented)",
        f"model architecture{_ARCH_GAP}was supported in vllm until",
        f"model type{_ARCH_GAP}(not recognized|unsupported|not supported)",
        f"architectures{_ARCH_GAP}unsupported",
    )),
    ("unsupported_quantization", ("unsupported quantization", "quantization method", "gptq.*not supported", "awq.*not supported", "marlin.*not supported", "bitsandbytes.*not supported", "quantization config.*unsupported")),
    # "cutlass" on its own is a normal vLLM compile log line.
    ("unsupported_kernel", ("no kernel image is available", "invalid device function", f"cutlass{_EG}(error|fail|unsupported|not supported)", f"fused{_EG}kernel{_EG}(error|fail|unsupported)", f"kernel{_EG}(is )?not supported", f"cuda error{_EG}kernel")),
    # Backend *names* alone are normal selection/import chatter. Require an
    # explicit rejection of the backend.
    ("attention_backend_unsupported", (
        f"(flashinfer|flash_?attn?|flashattention|xformers){_EG}(not supported|unsupported|does not exist|not available|no module named|failed to (import|load|compile))",
        f"(not supported|unsupported|no module named|failed to (import|load|compile)){_EG}(flashinfer|flash_?attn?|flashattention|xformers)",
        "cannot use flash",
        f"attention backend{_EG}(not supported|unsupported|unavailable)",
    )),
    ("triton_or_ptx_failure", ("triton.*unsupported", "ptx.*unsupported", "ptxas fatal", "unsupported ptx version", "triton compilation", "failed to compile triton")),
    ("custom_cuda_op_missing", ("no module named .*cuda", "undefined symbol.*cuda", "custom op.*not found", "operator .* does not exist", "torch.ops.*not found")),
    # dtype names alone appear in every model config line. Require the dtype and
    # an explicit rejection/requirement of it.
    ("bf16_or_fp8_unsupported", (
        f"(bfloat16|bf16|fp8|float8){_EG}(not supported|unsupported|is not available|requires|not implemented|cannot|unable to)",
        f"(not supported|unsupported|does not support|requires|not implemented){_EG}(bfloat16|bf16|fp8|float8)",
        "not supported on this gpu",
        f"requires{_EG}fp8",
    )),
    # "torch" followed anywhere by "cuda" is not evidence of a build mismatch:
    # "torch.OutOfMemoryError: CUDA out of memory" is a plain OOM. Each pattern
    # below requires an actual build/version statement.
    ("torch_cuda_binary_mismatch", (
        f"(torch|pytorch){_EG}(compiled|built|build|version|binary)",
        f"compiled with cuda{_EG}[0-9]",
        "not compiled with cuda",
        "cuda version mismatch",
        "torch.*cuda.*mismatch",
        "torchvision.{0,60}(mismatch|incompatible|version)",
    )),
    ("cuda_driver_runtime_mismatch", ("cuda driver version is insufficient", "driver/library version mismatch", "libcuda", "cuda error 35", "unsupported cuda version", "forward compatibility was attempted")),
    ("cudnn_failure", ("cudnn_status", "could not load libcudnn", "cudnn.*not supported")),
    ("native_library_or_abi_failure", ("glibc_", "glibcxx_", "version .* not found", "undefined symbol", "cannot open shared object file", "ldd", "symbol lookup error")),
    ("python_abi_mismatch", ("wrong elf class", "invalid elf header", "python abi", "cp3.*not compatible", "not a supported wheel on this platform")),
    ("illegal_instruction", ("illegal instruction", "sigill")),
    # "NCCL initialized" / "tensor parallel size 2" are normal startup lines.
    # Require the subject with an actual collective/distributed failure.
    ("tensor_parallel_failure", (
        f"(nccl|processgroupnccl){_EG}(error|failed|failure|exception|timeout|unhandled|abort|invalid|unavailable)",
        f"(error|failed|failure|exception|timeout|unhandled|abort|invalid|unavailable){_EG}(nccl|processgroupnccl)",
        f"(tensor parallel|p2p|peer access){_EG}(error|failed|failure|not supported|unsupported|unavailable|disabled|mismatch|timeout)",
        "unhandled system error",
        "connection closed by peer",
        "duplicate gpu detected",
        "nccl error",
    )),
    ("cuda_graph_failure", ("cuda graph", "cudagraph", "graph capture", "capture failed")),
    ("mtp_unsupported", (
        f"(speculative|mtp|draft model|speculat){_EG}(not supported|unsupported|not enabled|disabled|not available|is not enabled|unavailable|no speculative)",
        f"(not supported|unsupported|not enabled|disabled|not available){_EG}(speculative|mtp|draft model)",
        f"qwen3_next_mtp{_EG}(unsupported|not supported)",
    )),
    # "MTP enabled, acceptance=0.7" is informational. Require an actual MTP
    # exception/failure signal, not the mere presence of speculation vocabulary.
    ("mtp_runtime_failure", (
        f"(speculative|mtp|draft token|draft model){_EG}(error|failed|failure|exception|invalid|mismatch|crash|aborted|timeout|rejected|disabled)",
        f"(error|failed|failure|exception|invalid|mismatch|crash|aborted|timeout|rejected|disabled){_EG}(speculative|mtp|draft token|draft model)",
        f"speculation{_EG}(error|failed|failure)",
    )),
    # tokenizer/vocab/protobuf appear in ordinary load metadata; require a load
    # or parse failure tied to them.
    ("tokenizer_load_failure", (
        f"(tokenizer|sentencepiece|tokenizers|vocab|protobuf){_EG}(not found|failed|failure|error|exception|cannot|unable to|missing|invalid|corrupt|unknown)",
        f"(failed to load|failure|error|exception|cannot|unable to|missing|invalid|corrupt){_EG}(tokenizer|sentencepiece|tokenizers|vocab|protobuf)",
    )),
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
    # A "/kaggle/working/..." path must never imply a control-plane failure, and a
    # "CUDA kernel failed" line is not a Kaggle session failure either, so every
    # pattern here needs an explicit Kaggle/session/accelerator context word plus
    # a failure phrase.
    ("kaggle_session_or_control_plane_failure", (
        f"kaggle{_EG}(error|fail|died|crash|stopped|terminated|disconnect|unavailable|reject)",
        f"kernels?[-_ ]?(status|output|pull|run|list|status){_EG}(error|fail|denied|reject|unauthor)",
        f"(session|notebook){_EG}(stopped|expired|terminated|died|disconnected|unavailable|crashed)",
        f"accelerator{_EG}(unavailable|disabled|detached|lost|removed|not available|limit)",
        f"control plane{_EG}(error|failure|unavailable|rejected)",
        "failed to (start|attach|create) (a )?(session|kernel|notebook)",
        "kernel exited (with )?(unexpected|error|code)",
        "session (has )?(been )?(stopped|terminated|expired)",
        "your accelerator has been disabled",
        f"cuda gpus{_EG}(unavailable|not available|limit reached)",
    )),
    ("model_load_failure", ("failed to load model", "error loading model", "model load", "safetensors", "gguf", "failed to mmap")),
]

def _oom_stage(text: str, stage: str | None) -> str:
    """Attribute a real CUDA OOM to ``load`` or ``generate``.

    Requires a genuine allocation-failure signal. The caller's declared stage
    wins when it is unambiguous; otherwise the log's own wording decides. Bare
    stage words in the log ("while loading", "kv cache") are only consulted
    after an OOM signal exists.
    """
    if not re.search(
        r"cuda out of memory|outofmemoryerror|cuda error: out of memory|"
        r"failed to allocate|can't allocate memory|cannot allocate memory",
        text,
        flags=re.I,
    ):
        return ""
    if stage in ("load", "generate"):
        return stage
    if stage in ("install", "download", "server_start", "cleanup"):
        # Server startup / install / download are model-construction-ish for our
        # purposes: an OOM there is a load-shaped capacity failure.
        return "load"
    # Log-wording fallback. Generation evidence wins when both appear, because a
    # KV/allocation failure inside a request is the actionable signal.
    if re.search(
        r"during (generation|decode|inference)|generat|decode|kv cache|kv_cache|"
        r"failed to allocate kv|per-request|per request|request \d|forward pass",
        text,
        flags=re.I,
    ):
        return "generate"
    if re.search(
        r"loading model|load model|model load|loading weights|initialize|initializing|"
        r"engine|profile_run|cuda graph|weight|shard",
        text,
        flags=re.I,
    ):
        return "load"
    return ""


#: Categories decided by `_oom_stage` instead of by their RULES patterns.
_OOM_CATEGORIES = ("cuda_oom_load", "cuda_oom_generate")


def classify(text: str, stage: str | None = None) -> list[str]:
    """Classify one attempt log.

    ``stage`` is the execution stage the caller already knows
    (``install``/``download``/``load``/``server_start``/``generate``/``cleanup``).
    It is optional; when absent the classifier falls back to log wording, and
    when the log has no positive failure evidence the result is
    ``unclassified_runtime_failure`` rather than a confident wrong guess.
    """
    s = str(text or "")
    if stage is not None and str(stage).strip().lower() not in STAGES:
        raise ValueError(f"unknown stage {stage!r}; expected one of {STAGES}")
    stage = str(stage).strip().lower() if stage is not None else None
    low = s.lower()
    hits: list[str] = []
    for category, patterns in RULES:
        if category in _OOM_CATEGORIES:
            continue
        if any(re.search(pattern, low, flags=re.I | re.S) for pattern in patterns):
            hits.append(category)

    oom = _oom_stage(s, stage)
    if oom == "load":
        hits.insert(0, "cuda_oom_load")
    elif oom == "generate":
        hits.insert(0, "cuda_oom_generate")

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


def primary(text: str, stage: str | None = None) -> str:
    return classify(text, stage=stage)[0]


if __name__ == "__main__":
    import argparse, json
    from pathlib import Path
    ap = argparse.ArgumentParser()
    ap.add_argument("log", type=Path)
    ap.add_argument("--stage", choices=STAGES, default=None)
    args = ap.parse_args()
    text = args.log.read_text(encoding="utf-8", errors="replace")
    print(json.dumps({"primary": primary(text, stage=args.stage), "all": classify(text, stage=args.stage)}, indent=2))
