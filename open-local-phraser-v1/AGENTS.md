# Open Local Phraser

This directory is the canonical production app. Do not implement production behavior in `../open-local-phraser-v1-safe-rewrite-lab/`.

## Cloud benchmark shutdown (mandatory)

- Keep Kaggle and other cloud accelerator sessions stopped by default. Start or run one only when the user explicitly authorizes that cloud run.
- After an authorized run finishes, fails, is cancelled, or is no longer actively needed, stop the provider session and set its accelerator to off/None. A terminated inference server, idle notebook, closed browser tab, zero GPU utilization/memory, or saved notebook version does not prove the cloud session stopped.
- Verify the provider control plane reports the session stopped and accelerator off before reporting cleanup complete. Do not leave a session running while reviewing results locally or waiting in the background.
- Before stopping, preserve only authorized outputs in the authorized location; never publish or expose private benchmark inputs/results unless explicitly requested. Do not stop unrelated user-owned sessions.
- An exception to shutdown requires an explicit user override naming the exact resource and how long it may remain active. Stop and verify it when that window ends. If shutdown cannot be confirmed, report the exact uncertainty and do not claim it is off.

## Kaggle English Core / Word Studio benchmark (mandatory)

For Issue #25 and the `bench/english-studio-v3` model-selection work, read and obey all three:

- `benchmarks/english-studio-v3/KAGGLE_AGENT_EXECUTION.md` — literal execution state machine; do not improvise.
- `benchmarks/english-studio-v3/KAGGLE_2XT4_RUN.md` — canonical operational evidence/runbook.
- `benchmarks/english-studio-v3/KAGGLE_BENCHMARK_HARDENING.md` — qualification/failure contract.

Before any GPU model run, execute both package checks:

```bash
cd benchmarks/english-studio-v3
bash self-check-english-core.sh
bash self-check-kaggle-runtime.sh
```

If either check fails, stop. That is a benchmark-package problem, not a model result.

Promotion-quality runtime evidence must be produced on an actual private Kaggle **2× NVIDIA T4 (16 GB each)** run. Do not substitute another GPU/provider or a local run for the T4 qualification step.

### Prebuilt-only rule

Canonical Kaggle execution must use `benchmarks/english-studio-v3/kaggle-prebuilt-runtimes.json` and `install-kaggle-prebuilt-runtime.py`. Do **not** compile native runtimes or extensions during a benchmark run. In particular, do not run CMake, Ninja, Make, NVCC, Cargo builds, `setup.py build`, `pip install -e`, or source builds of vLLM / llama.cpp / FlashAttention / Triton extensions. If a compatible prebuilt wheel/vendor binary is unavailable or incompatible, record the exact runtime configuration as `runtime_unqualified` and move on. Source-build experiments require separate explicit authorization and are not part of Issue #25's normal execution path.

Before any candidate enters English-quality ranking, separately establish:

1. the exact artifact/runtime loads and stays on the declared GPU(s);
2. the benchmark protocol can observe and classify its responses;
3. only then, its English Core / Word Studio quality.

Do not convert model-load, CUDA OOM, unsupported architecture/quantization, unsupported sm75 kernel, BF16/FP8 assumptions, FlashAttention/FlashInfer/Triton failure, GPTQ/AWQ/Marlin kernel limits, bitsandbytes incompatibility, CUDA driver/runtime mismatch, MTP failure, ABI/library failure, NCCL/P2P/TP failure, timeout, Kaggle-session failure, GPU-offload uncertainty, or silent CPU fallback into an English score of zero. Preserve those as structured runtime-unqualified results.

Forced-choice evaluation must preserve both the frozen strict protocol result and a separately labeled conservative recoverable parse where predeclared parser rules can recover an explicit answer such as `A. same`. Never infer answers from arbitrary prose or use the gold label to resolve ambiguity. Word Studio runs must preserve raw output plus parsed candidate count, unique count, duplicate rate, malformed-list status, and time to first/3/10 parsed candidates where measurable.

Use the predeclared batch-size fallback sequence and retry policy from `KAGGLE_BENCHMARK_HARDENING.md`; never silently change checkpoint, quantization, dtype semantics, tokenizer/template, or runtime to make a candidate fit. Such changes create a new candidate configuration.

### Mechanical runner rule

Use `run-kaggle-candidate.py` as the normal candidate entry point. Candidate ID decides whether vLLM or the pinned Prism llama.cpp runtime is used. Do not hand-construct equivalent commands unless repairing the benchmark itself.

```bash
python run-kaggle-candidate.py CANDIDATE_ID --stage smoke --benchmark-revision "$REV"
python run-kaggle-candidate.py CANDIDATE_ID --stage full --benchmark-revision "$REV"
python run-kaggle-candidate.py CANDIDATE_ID --stage transform --benchmark-revision "$REV"
```

For the product suite, build the cross-granularity task file from the tracked seed first:

```bash
python build-word-studio-transform-suite.py
```

For finalist interactive latency, use `run-kaggle-vllm-streaming-latency.py` for vLLM candidates. It launches the pinned prebuilt vLLM server locally, validates the exact CLI before model load, proves T4 VRAM use, streams output, measures first usable candidate / first 3 / first 10, and shuts the server down. Do not substitute TTFT for first-useful-candidate latency.

After each candidate or interrupted batch of candidates, regenerate the explicit completeness matrix:

```bash
python build-kaggle-candidate-matrix.py
```

`not_run` and `runtime_unqualified` rows must remain visible. Never delete a failed candidate from the history to make the comparison cleaner.

Resume may only continue an exact atomic task-ID prefix under the same model revision, task hash, prompt mode, decoding, topology, and benchmark revision. The resume contract is regression-tested by `test_resume_contract.py`. Never splice outputs from changed configurations.

## Architecture

- React 19 + TypeScript + Vite frontend.
- Swift/AppKit/WKWebView desktop wrapper.
- One local-first paragraph workflow with a bundled native MLX generator and a deterministic local-safe fallback; never add a remote fallback.
- Personal and Warmth are the supported visible styles. They share approval memory, protected-content validation, and grammar/flow gates.
- Transient `ParaphraseSession` state until explicit approval.
- Protected-content validation before generation display and approval.
- Native Application Support persistence for approved records and preference memory.
- IndexedDB is a browser-only development fallback; it is not the packaged app database.

## Required checks

```bash
npm run build
npm run qa:approval
npm run build:desktop
```

Keep the old synonym/token helpers where they support contextual replacements. Keep the style selector compact and user-facing, but do not expose technical ranking selectors, model internals, background mutation, or user-facing training concepts.

The native path is configured in `native-models/config.json` (env `PARI_NATIVE_MODEL_ID` / `PARI_NATIVE_MODEL_PATH` override). Qwen3.5-4B is the current **incumbent/control only** — do not bake Qwen strings into new code. See `benchmarks/llm-shootout/README.md` (Ling-3.0-tiny challenger: 7.9B/1.3B active, ~4.2GB MLX-4bit via rapid-mlx) and `benchmarks/quillbot/README.md`. Describe the native path as primary only when packaged loading and installed headless evidence pass. The `local-safe-engine` remains deliberately bounded and deterministic. Do not claim "beats QuillBot" until the frozen 300-500+ held-out benchmark (#8) passes on the hardened English-quality judge (#7) without higher meaning/invention failures (ro-04 regression is the canonical false-pass).
