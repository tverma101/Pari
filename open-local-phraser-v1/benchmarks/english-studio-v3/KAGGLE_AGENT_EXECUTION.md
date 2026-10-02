# Kaggle agent execution — literal instructions, no improvisation

This file exists so an execution agent does **not** reason about how to run the benchmark. Follow the state machine below literally.

## Hard rules

1. Do not redesign the benchmark, prompts, parser, model roster, quantization, or scoring while executing a run.
2. Do not compile C++, CUDA, Rust, llama.cpp, vLLM, FlashAttention, Triton extensions, or any model runtime.
3. Do not run `cmake`, `ninja`, `make`, `nvcc`, `cargo build`, `setup.py build`, `pip install -e`, or a pip source distribution.
4. Use only `kaggle-prebuilt-runtimes.json` + `install-kaggle-prebuilt-runtime.py` for native runtimes.
5. If no compatible prebuilt exists, record `runtime_unqualified` and move to the next candidate.
6. Do not retry because an answer is wrong, malformed, a refusal, or poor. Those are benchmark observations.
7. Do not change a model configuration to make it pass. A different quantization/dtype/runtime/checkpoint is a separate candidate configuration.
8. Never score a runtime failure as English = 0.
9. Use `run-kaggle-candidate.py`; do not manually reconstruct candidate commands unless repairing the benchmark package itself.
10. Never merge from this execution task.

## Canonical sources

- Issue #25 — benchmark run.
- Issue #28 — blocking hardening requirements.
- `KAGGLE_BENCHMARK_HARDENING.md` — failure/qualification contract.
- `kaggle-candidate-roster.json` — exact model revisions.
- `kaggle-prebuilt-runtimes.json` — exact runtime builds.
- `kaggle-preflight.py` — real 2×T4 gate.
- `run-kaggle-candidate.py` — single candidate dispatcher.
- `protocol_output_diagnostics.py` — format/protocol diagnostics without gold labels.
- `word_studio_output_parser.py` — deterministic product-output parser.
- `kaggle_failure_taxonomy.py` — runtime failure classifier.
- `build-kaggle-candidate-matrix.py` — explicit completed/failed/not-run matrix.

## Actual prebuilt builds

### vLLM 0.30.0 CUDA 12.9 x86_64 official wheel

Release:
`https://github.com/vllm-project/vllm/releases/tag/v0.30.0`

Pinned wheel:
`https://github.com/vllm-project/vllm/releases/download/v0.30.0/vllm-0.30.0%2Bcu129-cp38-abi3-manylinux_2_28_x86_64.whl`

SHA-256:
`e98cb69659bfcfc849cf11ce0781a7161d40b02b51a6c3636924a5909f2aabcc`

If this wheel is incompatible with the Kaggle driver/runtime, STOP that vLLM configuration. Do not build vLLM from source.

### PrismML llama.cpp prebuilt — CUDA 12.4

Release:
`https://github.com/PrismML-Eng/llama.cpp/releases/tag/prism-b10735-842b188`

Pinned build:
`https://github.com/PrismML-Eng/llama.cpp/releases/download/prism-b10735-842b188/llama-prism-b10735-842b188-bin-linux-cuda-12.4-x64.tar.gz`

SHA-256:
`b58caa10e38ea2d3af419bc1c908f785b5f8756b07c98cb1752d50e1e985d4c6`

### PrismML llama.cpp prebuilt — CUDA 12.8

Pinned build:
`https://github.com/PrismML-Eng/llama.cpp/releases/download/prism-b10735-842b188/llama-prism-b10735-842b188-bin-linux-cuda-12.8-x64.tar.gz`

SHA-256:
`5cbac5269804e4eb63676aeaec1ee7d4cff6e22b87da91de9b05795bf635998e`

The CUDA 12.8 Prism build already completed a real Kaggle Bonsai-27B Q1_0 run. Prefer a pinned vendor binary over any source build.

## State machine

Set these once:

```bash
export BENCHMARK_REVISION="$(git rev-parse HEAD)"
export CANDIDATE="qwen35-4b"   # replace only with an exact id from kaggle-candidate-roster.json
```

### S0 — checkout

```bash
git clone --branch bench/english-studio-v3 https://github.com/tverma101/Pari.git pari
cd pari/open-local-phraser-v1/benchmarks/english-studio-v3
export BENCHMARK_REVISION="$(git rev-parse HEAD)"
```

Do not edit benchmark files in the run notebook.

### S1 — environment gate

```bash
python kaggle-preflight.py --output /kaggle/working/results/preflight.json
```

If exit != 0: archive the preflight artifact, classify the environment as unqualified, stop. Do not touch models.

The preflight records T4 identity, compute capability, free VRAM, existing GPU processes, libc/ldd, disk space, topology and peer access. P2P warnings do not disqualify independent one-GPU replicas.

### S2 — benchmark-package self-check and frozen product builds

```bash
bash self-check-english-core.sh
python build-word-studio-strength-suite.py \
  --synthetic-seed word-studio-synthetic.seed.json
python build-word-studio-transform-suite.py
```

Expected product files:

- `word-studio-strength.jsonl` — 112 strength/rewrite tasks.
- `word-studio-transform.jsonl` — exactly 100 arbitrary cross-granularity tasks.

If any command fails: this is a benchmark-package failure, not a model result. Stop model evaluation until the package is fixed in Git.

### S3 — install runtime from a binary only

For a vLLM candidate:

```bash
python install-kaggle-prebuilt-runtime.py vllm-0.30.0-cu129-linux-x86_64
```

For Bonsai/Prism:

```bash
python install-kaggle-prebuilt-runtime.py prism-llamacpp-b10735-cuda12.8-linux-x86_64
```

If install/import/version smoke fails: save logs; mark exact runtime config unqualified; DO NOT compile anything.

### S4 — candidate protocol smoke

Exactly one command:

```bash
python run-kaggle-candidate.py "$CANDIDATE" \
  --stage smoke \
  --benchmark-revision "$BENCHMARK_REVISION"
```

The dispatcher chooses vLLM vs Prism from the frozen roster. It applies only the predeclared OOM batch fallback. It records protocol diagnostics automatically.

Wrong answers do not fail the smoke. The smoke proves execution and observability.

### S5 — full English Core

```bash
python run-kaggle-candidate.py "$CANDIDATE" \
  --stage full \
  --benchmark-revision "$BENCHMARK_REVISION"
```

Run all 1,943 fixed cases. Do not change settings halfway through.

### S6 — Word Studio slider/rewrite suite

```bash
python run-kaggle-candidate.py "$CANDIDATE" \
  --stage word-studio \
  --benchmark-revision "$BENCHMARK_REVISION"
```

This is single-request/interactive oriented (`batch=1`). Malformed or too-short candidate lists are recorded; do not regenerate them.

### S7 — cross-granularity transform suite

```bash
python run-kaggle-candidate.py "$CANDIDATE" \
  --stage transform \
  --benchmark-revision "$BENCHMARK_REVISION"
```

This runs 100 tasks covering word→phrase, phrase→word, phrase→phrase, clause transforms, sentence rewrites, sentence→1–3 word semantic compression, split/join, register/vocabulary constraints, collocations, protected context, and expansion/compression.

Intentional semantic-compression cases are labeled separately and must not be judged with full-paraphrase equivalence thresholds.

### S8 — status matrix

After each candidate, always run:

```bash
python build-kaggle-candidate-matrix.py
```

The matrix must continue showing candidates/stages as `not_run`, `runtime_unqualified`, `benchmark_blocked`, or completed. Never delete failed/unrun rows.

### S9 — speed variants

Only after ordinary decoding succeeds, and only for methods listed in that candidate's `mtpMethodsToProbe`:

```bash
python run-kaggle-candidate.py "$CANDIDATE" \
  --stage smoke \
  --decode mtp \
  --speculative-tokens 1 \
  --benchmark-revision "$BENCHMARK_REVISION"
```

Then repeat the needed full/product stage only if the smoke succeeds. Replace `mtp` with `qwen3_next_mtp` only when that exact method is listed in the roster.

Never change benchmark prompts for speed runs. MTP unsupported/failure does not invalidate the ordinary-decode model run.

### S10 — cleanup

Save authorized result artifacts, terminate runtime/server processes, and verify the Kaggle session/accelerator is off. Do not claim shutdown merely because GPU utilization is zero.

## STOP conditions — do not debug into a different experiment

Stop the exact candidate configuration and preserve the failure if you see any of these after the allowed same-config retry:

- unsupported T4 compute capability/kernel or model architecture;
- BF16/FP8-only kernel assumption;
- FlashAttention/FlashInfer/xFormers/Triton/PTX kernel unavailable on sm75;
- missing custom CUDA op;
- GPTQ/AWQ/Marlin/bitsandbytes implementation requires newer architecture;
- PyTorch/CUDA/cuDNN binary mismatch;
- CUDA driver/runtime mismatch;
- GLIBC/GLIBCXX/Python ABI failure or illegal instruction;
- tokenizer/chat-template/remote-code dependency cannot initialize;
- gated/auth model access, persistent Hub failure, or corrupted/hash-mismatched artifact;
- insufficient disk space;
- no binary wheel/distribution exists;
- pip starts building a wheel/source package;
- CMake/Ninja/Make/NVCC/Rust compilation begins;
- model cannot fit at batch 1 under the frozen configuration;
- CUDA device-side assert or persistent CUDA-graph failure;
- silent CPU fallback;
- GPU offload cannot be proven;
- NCCL/P2P/TP failure;
- MTP unsupported or crashes (ordinary decoding may remain separately qualified);
- persistent generation timeout/runtime crash;
- server port/bind failure not resolved by the predeclared runner setup;
- output/request count mismatch that the runner cannot safely attribute by ID.

Do not "fix" any of the above by silently changing model identity, quantization, runtime, tokenizer, prompt, dtype semantics, or checkpoint. Move on and preserve the evidence.
