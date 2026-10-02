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
9. Never merge from this execution task.

## Canonical sources

- Issue #25 — benchmark run.
- Issue #28 — blocking hardening requirements.
- `KAGGLE_BENCHMARK_HARDENING.md` — failure/qualification contract.
- `kaggle-candidate-roster.json` — exact model revisions.
- `kaggle-prebuilt-runtimes.json` — exact runtime builds.
- `kaggle-preflight.py` — real 2×T4 gate.
- `word_studio_output_parser.py` — deterministic product-output parser.
- `kaggle_failure_taxonomy.py` — runtime failure classifier.

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

### S0 — checkout

```bash
git clone --branch bench/english-studio-v3 https://github.com/tverma101/Pari.git pari
cd pari/open-local-phraser-v1/benchmarks/english-studio-v3
```

Record `git rev-parse HEAD`. Do not edit benchmark files in the run notebook.

### S1 — environment gate

```bash
python kaggle-preflight.py --output /kaggle/working/results/preflight.json
```

If exit != 0: archive the preflight artifact, classify the environment as unqualified, stop. Do not touch models.

### S2 — self-check

```bash
bash self-check-english-core.sh
```

If this fails: this is a benchmark-package failure, not a model result. Stop model evaluation until the benchmark package itself is fixed in Git.

### S3 — install runtime from a binary only

For a vLLM candidate:

```bash
python install-kaggle-prebuilt-runtime.py vllm-0.30.0-cu129-linux-x86_64
```

For Bonsai/Prism:

```bash
python install-kaggle-prebuilt-runtime.py prism-llamacpp-b10735-cuda12.8-linux-x86_64
```

If install/import/version smoke fails: save logs; classify with `kaggle_failure_taxonomy.py`; mark exact runtime config unqualified; DO NOT compile anything.

### S4 — candidate protocol smoke

Run only the predeclared 16-case smoke/fixed prefix using the candidate's exact roster configuration. Do not alter prompts after seeing output.

For vLLM use the existing `run-english-core-vllm.py` with `--limit 16` and the exact revision/config from the roster.

Allowed batch fallback, and only this fallback:

`32 -> 16 -> 8 -> 4 -> 1`

If a batch fails because of OOM, retain its log and try the next batch. Any other failure stops the exact configuration and is classified.

### S5 — validate smoke

Require:

- output/result artifact exists;
- 16 unique expected IDs;
- no output-count mismatch;
- scorer/parser can read the file;
- failure/format diagnostics are preserved;
- no silent CPU fallback.

Wrong answers do not fail the smoke. The smoke proves execution and observability.

### S6 — full English Core

Run all 1,943 fixed cases with the first stable predeclared batch size. Save raw result and all runtime metadata.

Do not change settings halfway through. An interrupted run must retain a checkpoint; a resumed run must not duplicate or skip IDs.

### S7 — format diagnostics

Report strict output compliance and conservative recoverable parsing separately. Do not rewrite outputs.

### S8 — Word Studio

Run the frozen Word Studio suite on finalists. Then:

```bash
python word_studio_output_parser.py RAW_RESULT.json PARSED_RESULT.json --requested 10
```

Do not regenerate malformed lists. Count malformed/too-few/duplicate candidates as product observations.

### S9 — speed variants

Only after ordinary decoding succeeds:

- MTP/speculative config if officially supported by the exact model/runtime;
- one T4 baseline;
- TP2 only when required or measured;
- independent two-GPU/replica path if it fits.

Never change the benchmark prompts for speed runs.

### S10 — cleanup

Save authorized result artifacts, terminate runtime/server processes, and verify the Kaggle session/accelerator is off. Do not claim shutdown merely because GPU utilization is zero.

## STOP conditions — do not debug into a different experiment

Stop the exact candidate configuration and record the failure if you see any of these after the allowed same-config retry:

- unsupported T4 compute capability/kernel;
- BF16/FP8-only kernel assumption;
- FlashAttention/FlashInfer/Triton kernel unavailable on sm75;
- GPTQ/AWQ/Marlin implementation requires newer architecture;
- bitsandbytes kernel unsupported;
- CUDA driver/runtime mismatch;
- GLIBC/GLIBCXX/ABI failure;
- tokenizer/chat-template cannot initialize;
- no binary wheel/distribution exists;
- pip starts building a wheel/source package;
- CMake/Ninja/Make/NVCC/Rust compilation begins;
- model cannot fit at batch 1 under the frozen configuration;
- silent CPU fallback;
- GPU offload cannot be proven;
- NCCL/P2P/TP failure;
- MTP unsupported or crashes (ordinary decoding may remain separately qualified);
- persistent generation timeout/runtime crash;
- output/request count mismatch that the runner cannot safely attribute by ID.

Do not "fix" any of the above by silently changing model identity. Move on and preserve the evidence.
