# Kaggle agent execution — literal instructions, no improvisation

This file exists so an execution agent does **not** decide how to run the benchmark.
Follow these commands literally. Do not redesign, optimize, repair, or substitute
components during the run.

## Hard rules

1. Do not change benchmark prompts, weights, task files, parsers, model revisions, quantization, dtype semantics, or candidate identity after seeing results.
2. Do not compile C++, CUDA, Rust, vLLM, llama.cpp, FlashAttention, Triton extensions, or model-specific kernels.
3. Never run `cmake`, `ninja`, `make`, `nvcc`, `cargo build`, `setup.py build`, `pip install -e`, `--no-binary`, or a source-distribution fallback.
4. Use only the pinned prebuilts in `kaggle-prebuilt-runtimes.json`. The dispatcher installs/verifies them automatically.
5. If a compatible pinned binary/model configuration fails, preserve the artifact and move on. Do not invent a workaround.
6. Wrong, malformed, verbose, refusal, truncated, or low-quality model answers are benchmark observations. Do not retry them for a prettier answer.
7. Runtime failure is never English score = 0. Keep it as `runtime_unqualified`.
8. Never merge from this execution task.

## Canonical entry points

- `prepare-kaggle-benchmark.py` — CPU/data preparation before GPU time.
- `verify-kaggle-benchmark-preparation.py` — proves generated tasks still match their preparation receipt.
- `run-kaggle-roster.py` — run the frozen roster mechanically.
- `run-kaggle-candidate.py` — one candidate/stage; normally called by the roster runner.
- `run-kaggle-vllm-streaming-latency.py` — finalist interactive latency only.
- `build-kaggle-candidate-matrix.py` — explicit completed/failed/not-run matrix.
- `KAGGLE_BENCHMARK_HARDENING.md` — failure and evidence contract.

The runners themselves handle:

- product-suite generation and exact case-count validation;
- exact model revisions;
- vLLM vs Prism runtime routing;
- pinned-binary install/receipt verification;
- Prism CUDA 12.8 → 12.4 **prebuilt-only** compatibility ladder;
- Hub artifact/disk preflight;
- allowed OOM batch fallback;
- raw output preservation;
- protocol diagnostics;
- candidate matrix updates.

Do not duplicate those decisions manually.

## Pinned runtime builds

### vLLM 0.30.0 CUDA 12.9 x86_64

Release: `https://github.com/vllm-project/vllm/releases/tag/v0.30.0`

Wheel: `https://github.com/vllm-project/vllm/releases/download/v0.30.0/vllm-0.30.0%2Bcu129-cp38-abi3-manylinux_2_28_x86_64.whl`

SHA-256: `e98cb69659bfcfc849cf11ce0781a7161d40b02b51a6c3636924a5909f2aabcc`

### Prism llama.cpp pinned commit `842b1880415d6f508f03b789e5ce70194def7bfd`

CUDA 12.8 binary:
`https://github.com/PrismML-Eng/llama.cpp/releases/download/prism-b10735-842b188/llama-prism-b10735-842b188-bin-linux-cuda-12.8-x64.tar.gz`

SHA-256: `5cbac5269804e4eb63676aeaec1ee7d4cff6e22b87da91de9b05795bf635998e`

CUDA 12.4 fallback binary:
`https://github.com/PrismML-Eng/llama.cpp/releases/download/prism-b10735-842b188/llama-prism-b10735-842b188-bin-linux-cuda-12.4-x64.tar.gz`

SHA-256: `b58caa10e38ea2d3af419bc1c908f785b5f8756b07c98cb1752d50e1e985d4c6`

Both Prism binaries are vendor prebuilts from the same pinned source commit. No source build is permitted.

---

# Literal run sequence

## S0 — checkout, accelerator OFF

Keep the Kaggle accelerator at `None` for S0–S1.

```bash
git clone --branch bench/english-studio-v3 https://github.com/tverma101/Pari.git pari
cd pari/open-local-phraser-v1/benchmarks/english-studio-v3
export BENCHMARK_REVISION="$(git rev-parse HEAD)"
```

Do not edit benchmark files in the Kaggle notebook.

## S1 — prove and prepare the benchmark package, still accelerator OFF

```bash
bash self-check-english-core.sh
bash self-check-kaggle-runtime.sh
python prepare-kaggle-benchmark.py
python verify-kaggle-benchmark-preparation.py \
  --benchmark-revision "$BENCHMARK_REVISION"
```

This step builds and verifies every generated benchmark task **before GPU time**:

- 68 shadow cases;
- 1,570 pinned public-fast cases;
- 305 pinned SemanticQA LCC cases;
- combined 1,943-case English Core screen;
- 100 cross-granularity Word Studio tasks;
- 112 strength/rewrite Word Studio tasks;
- 16 tracked protocol-smoke tasks.

The public dataset builder runs inside an isolated binary-wheel-only venv, and the
SemanticQA checkout is forced to the exact clean pinned commit. No model weights or
GPU runtimes are downloaded by benchmark preparation.

If any S1 command fails, STOP. That is a benchmark/data-preparation failure, not a
model result. Do not turn the GPU on to debug it.

## S2 — enable T4×2 and prove the environment

Only after S1 succeeds, enable Kaggle `GPU T4 x2`, then run:

```bash
python kaggle-preflight.py --output /kaggle/working/results/preflight.json
```

If this fails, STOP. Do not download a model. The environment is unqualified.

The preflight records real Kaggle markers, exactly two T4s, compute capability 7.5,
VRAM/free VRAM, existing GPU processes, CUDA/driver, disk, libc, topology and P2P.
P2P warnings alone do not disqualify independent one-GPU replicas.

## S3 — run the roster

One command:

```bash
python run-kaggle-roster.py \
  --phase all \
  --probe-mtp-smoke \
  --benchmark-revision "$BENCHMARK_REVISION"
```

The roster runner first re-verifies the preparation receipt, task hashes/counts,
current Git revision, and T4 preflight. It refuses to start a model if any of those
are stale or incomplete.

For each candidate it attempts, in order:

1. shared 16-case protocol smoke;
2. full 1,943-case English Core screen;
3. 100-case cross-granularity Word Studio transform suite;
4. 112-case strength/rewrite Word Studio suite.

If a candidate fails a gate, later quality stages for that candidate are skipped and
the next candidate is attempted. Failure evidence stays on disk.

The same `kaggle-protocol-smoke.jsonl` is used for both vLLM and Prism/Bonsai. It
covers forced choice, JSON alternatives, Unicode, negation, conditions, protected
names/numbers, longer context, repeated warm request, casual register, word↔phrase
behavior and sentence→1–3-word compression. Smoke is not an English score.

`--probe-mtp-smoke` runs only MTP methods explicitly listed for that candidate and
only after ordinary smoke succeeds. MTP failure does not invalidate ordinary decode.

## S4 — inspect completeness, not vibes

The roster runner regenerates these after attempts:

```text
/kaggle/working/results/candidate-matrix.json
/kaggle/working/results/candidate-matrix.md
/kaggle/working/results/roster-orchestration.json
```

Every roster model must remain visible as completed, failed, skipped after a prior
failure, or `not_run`. Do not delete failed candidates from the report.

## S5 — finalist interactive latency

Only after ordinary quality runs identify finalists, measure actual usable-option
latency. For each vLLM finalist:

```bash
python run-kaggle-vllm-streaming-latency.py "$CANDIDATE" \
  --stage transform \
  --benchmark-revision "$BENCHMARK_REVISION"
```

This launches the pinned local vLLM server, validates the CLI **before model load**,
proves GPU VRAM use, streams the product tasks, and records:

- TTFT;
- full completion latency;
- first complete parsed candidate;
- first 3 complete parsed candidates;
- first 10 complete parsed candidates;
- malformed/duplicate/too-few candidate diagnostics.

Do not substitute token/sec or TTFT for first-useful-option latency.

Only after normal streaming latency succeeds may an explicitly supported speculative
variant be measured, for example:

```bash
python run-kaggle-vllm-streaming-latency.py "$CANDIDATE" \
  --stage transform \
  --decode mtp \
  --speculative-tokens 1 \
  --benchmark-revision "$BENCHMARK_REVISION"
```

Use a method only when it appears in that candidate's `mtpMethodsToProbe`.

## S6 — cleanup

Preserve authorized result artifacts, terminate local runtime/server processes, then
stop the Kaggle session and set its accelerator to off/None. Verify the provider
control plane reports it stopped. Zero GPU utilization or a closed browser tab is
not proof that the Kaggle accelerator stopped.

---

# STOP conditions — record, do not repair

Stop the exact configuration and move on after the declared same-config retry when
any of these occurs:

- no compatible pinned binary;
- pip attempts a source build;
- CMake/Ninja/Make/NVCC/Rust compilation begins;
- unsupported sm75/T4 kernel or model architecture;
- BF16/FP8-only assumption;
- FlashAttention/FlashInfer/xFormers/Triton/PTX/custom CUDA op unavailable;
- GPTQ/AWQ/Marlin/bitsandbytes kernel incompatibility;
- PyTorch/CUDA/cuDNN/driver mismatch;
- GLIBC/GLIBCXX/Python ABI failure or illegal instruction;
- gated/auth model failure or persistent Hub rate/download failure;
- insufficient disk;
- tokenizer/chat-template/remote-code dependency failure;
- model cannot fit at batch 1 under the frozen configuration;
- CUDA device assert or persistent CUDA-graph failure;
- silent CPU fallback;
- GPU offload cannot be proven;
- NCCL/P2P/TP failure;
- persistent timeout/runtime crash;
- output/request count cannot be attributed safely by task ID.

Do not silently change checkpoint, quantization, runtime family, tokenizer, prompt,
dtype semantics, or model identity to get a green run. A changed configuration is a
new experiment and must be represented separately.
