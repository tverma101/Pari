# Kaggle 2×T4 execution protocol

This is the canonical operational evidence contract for Pari Issue #25 / #28.
For literal execution commands, `KAGGLE_AGENT_EXECUTION.md` is authoritative.
Do not follow older Mac/MLX, source-build, nightly-runtime, or handwritten model
commands from historical notes.

## Goal

Evaluate the frozen Pari LLM roster on a real private Kaggle **2× NVIDIA T4
(16 GB each)** environment while keeping three questions separate:

1. Can the exact model/runtime configuration execute on T4?
2. Can the model follow the benchmark response protocol reliably?
3. How strong is its English Core / Word Studio behavior once execution works?

A runtime failure is never converted into an English score of zero.

## Phase A — CPU/data preparation, accelerator OFF

Keep Kaggle GPU/accelerator disabled while generating benchmark task files.
From a fresh checkout:

```bash
git clone --branch bench/english-studio-v3 https://github.com/tverma101/Pari.git pari
cd pari/open-local-phraser-v1/benchmarks/english-studio-v3
export BENCHMARK_REVISION="$(git rev-parse HEAD)"

bash self-check-english-core.sh
bash self-check-kaggle-runtime.sh
python prepare-kaggle-benchmark.py
python verify-kaggle-benchmark-preparation.py \
  --benchmark-revision "$BENCHMARK_REVISION"
```

`prepare-kaggle-benchmark.py` is deliberately CPU/data-only. It:

- rebuilds the 68-case Pari English Core shadow lane;
- creates an isolated binary-wheel-only Python environment for public datasets;
- builds the deterministic 1,570-case public-fast screen at exact pinned commits;
- creates/reuses a clean SemanticQA checkout at exact commit
  `56c82a587f4a6cef609255cd10af372d8c76600a`;
- builds the official 305-case SemanticQA LCC lane;
- assembles the exact 1,943-case fixed English screen;
- builds the 100-case cross-granularity Word Studio suite;
- builds the 112-case strength/rewrite suite;
- validates all task counts and hashes;
- writes `/kaggle/working/results/benchmark-preparation.json`.

Public-dataset Python packages live in a separate preparation venv and are
installed with `--only-binary=:all:`. Missing wheels are a preparation failure;
never compile dependencies to make preparation pass.

Frozen public-fast dataset commits:

| Source | Commit |
| --- | --- |
| BLiMP | `877fba0801ffb7cbd8c39c1ff314a46f053f6036` |
| SuperGLUE / WiC | `3de24cf8022e94f4ee4b9d55a6f539891524d646` |
| GLUE / CoLA | `bcdcba79d07bc864c1c254ccfcedcce55bcc9a8c` |
| PAWS | `161ece9501cf0a11f3e48bd356eaa82de46d6a09` |

## Phase B — enable T4×2 and qualify the environment

Only after Phase A succeeds, enable Kaggle T4×2 and run:

```bash
python kaggle-preflight.py \
  --output /kaggle/working/results/preflight.json
```

Promotion-quality evidence requires a real Kaggle environment with exactly two
visible NVIDIA T4s, CUDA available, compute capability 7.5 and adequate device
memory. The preflight additionally records free VRAM, existing GPU processes,
disk, libc, topology and peer access. P2P limitations are diagnostic and do not
by themselves disqualify the preferred independent-replica strategy.

## Phase C — execute the frozen roster

One command:

```bash
python run-kaggle-roster.py \
  --phase all \
  --probe-mtp-smoke \
  --benchmark-revision "$BENCHMARK_REVISION"
```

Before any candidate starts, the roster runner verifies the Phase A receipt,
current Git revision, task counts and task-file hashes. It also requires the
promotion-eligible T4 preflight.

For each roster candidate, ordinary decode runs first:

1. 16-case unscored protocol smoke;
2. 1,943-case English Core fixed screen;
3. 100-case Word Studio cross-granularity transform suite;
4. 112-case Word Studio strength/rewrite suite.

If a candidate fails a gate, its evidence remains on disk, later stages are
skipped, and the next roster entry is attempted. The runner regenerates the
candidate completeness matrix after each stage.

The protocol smoke is intentionally not an English-quality score. It covers
forced-choice output, JSON candidate lists, Unicode, negation, conditions,
protected names/numbers, longer context, repeated warm requests, register,
word↔phrase behavior and sentence→1–3-word semantic compression.

## Pinned runtime policy — no source builds

Canonical Issue #25 execution may use only artifacts in
`kaggle-prebuilt-runtimes.json`.

### vLLM

Pinned runtime: **vLLM 0.30.0 CUDA 12.9 x86_64**

Official wheel:
`https://github.com/vllm-project/vllm/releases/download/v0.30.0/vllm-0.30.0%2Bcu129-cp38-abi3-manylinux_2_28_x86_64.whl`

SHA-256:
`e98cb69659bfcfc849cf11ce0781a7161d40b02b51a6c3636924a5909f2aabcc`

The dispatcher installs it with binary-only pip policy and verifies the runtime
receipt plus installed version. A random Kaggle-preinstalled vLLM is not accepted
as canonical evidence.

### Prism llama.cpp / Bonsai

Pinned source commit:
`842b1880415d6f508f03b789e5ce70194def7bfd`

Allowed vendor-prebuilt compatibility ladder:

1. CUDA 12.8 x86_64
2. CUDA 12.4 x86_64

Both are official PrismML release binaries from the same pinned source commit.
Every attempt is logged. If neither binary works, the runtime configuration is
`runtime_unqualified`. Do **not** compile llama.cpp.

CUDA 12.8 SHA-256:
`5cbac5269804e4eb63676aeaec1ee7d4cff6e22b87da91de9b05795bf635998e`

CUDA 12.4 SHA-256:
`b58caa10e38ea2d3af419bc1c908f785b5f8756b07c98cb1752d50e1e985d4c6`

Forbidden during the canonical run include CMake, Ninja, Make, NVCC, Cargo,
`setup.py build`, editable installs, source-distribution pip fallbacks,
FlashAttention source compilation, and custom runtime patching.

## Artifact/model preflight

Before model weights are downloaded, runtime wrappers inspect the pinned Hub
artifact metadata and available disk. They record expected artifact size and
require enough headroom. Model access/auth, persistent Hub failures, unknown
artifact size, revision mismatch, missing exact GGUF file or insufficient disk
are structured runtime/preparation failures, not linguistic results.

For GGUF candidates the exact downloaded file is SHA-256 checked. For
Transformers/vLLM repositories, result identity binds the immutable Hub revision
and canonical pinned file inventory.

## T4 failure handling

At minimum preserve these classes separately when they occur:

- model/load OOM vs generation/KV-cache OOM;
- unsupported model architecture;
- unsupported sm75/T4 kernel;
- FP8/BF16-only assumptions;
- FlashAttention/FlashInfer/xFormers/Triton/PTX/custom-op incompatibility;
- GPTQ/AWQ/Marlin/bitsandbytes implementation limits;
- PyTorch/CUDA/cuDNN/driver mismatch;
- GLIBC/GLIBCXX/Python ABI errors or illegal instruction;
- tokenizer/chat-template/remote-code dependency errors;
- CUDA graph/device-side assert;
- NCCL/P2P/tensor-parallel failure;
- MTP unsupported vs MTP runtime failure;
- silent CPU fallback or unverified GPU offload;
- timeout/crash;
- Kaggle session/control-plane failure;
- forbidden source-build attempt.

The exact frozen configuration may reduce batch size only through the declared
batch fallback. Changing checkpoint, quantization, dtype semantics, tokenizer,
runtime family or model identity creates a new experiment.

## Output/protocol evidence

Raw model text is preserved. Do not clean away `<think>` blocks before protocol
diagnostics.

Forced-choice lanes report both:

- strict letter-only compliance/accuracy;
- conservative recoverable explicit-choice parsing.

The recoverable parser never consults gold labels and never scans arbitrary
prose to guess an answer.

Word Studio outputs report, where applicable:

- requested / parsed / unique option count;
- exact duplicates;
- unchanged-source copies;
- malformed/commentary output;
- finish reason / token-limit cutoff;
- option length distribution;
- first usable option / first 3 / first 10 latency for streaming finalist runs.

A fluent paragraph is not counted as a successful request for ten alternatives.

## Product benchmark contract

`kaggle-execution-manifest.json` defines the normal-decode stage counts:

| Stage | Cases | Role |
| --- | ---: | --- |
| protocol smoke | 16 | execution/format only, unscored |
| English Core fixed screen | 1,943 | common linguistic screen |
| Word Studio transform | 100 | arbitrary cross-granularity behavior |
| Word Studio strength/rewrite | 112 | strength/register/rewrite behavior |

Normal-decode executions including smoke: **2,171**.
Quality/product tasks excluding smoke: **2,155**.

The 100-case transform suite explicitly includes word→phrase, phrase→word,
phrase→phrase, clause transformation, sentence rewriting, sentence→1–3-word
gist compression, split/join, register/vocabulary control, collocation,
protected context, expansion and compression.

Intentional gist compression is not evaluated with ordinary full-paraphrase
semantic-equivalence thresholds because detail loss is part of the requested
operation.

## Finalist speed measurement

Do not choose a model from token/sec alone. After quality evidence identifies
finalists, measure the interactive product path.

For vLLM finalists:

```bash
python run-kaggle-vllm-streaming-latency.py CANDIDATE_ID \
  --stage transform \
  --benchmark-revision "$BENCHMARK_REVISION"
```

This uses the pinned local vLLM server, validates the CLI contract before model
load, proves T4 VRAM use, streams candidate output and measures TTFT plus time to
first / first 3 / first 10 complete parseable alternatives.

MTP/speculative variants may be measured only after ordinary decode succeeds and
only when the exact method appears in that candidate's frozen
`mtpMethodsToProbe`. Unsupported MTP is a separate speed-path failure and does
not invalidate ordinary generation.

For models fitting one T4, prefer measuring a one-GPU baseline and independent
second-GPU generation/replica behavior before assuming TP2 improves latency.
TP2 is required only when the model needs it or measurement shows it helps.

## Historical Bonsai 27B evidence

A previous private Kaggle run established that the pinned PrismML CUDA 12.8
prebuilt plus `prism-ml/Bonsai-27B-gguf` Q1_0 could run on Kaggle T4 CUDA0 with
65/65 layers offloaded. That run completed the then-current 1,943 English screen
and 112 Word Studio strength tasks.

Its strict public-fast result was 943/1,570 (60.06%) with 74.97% valid-output
coverage. A later offline conservative parser replay against the **same raw
outputs** recovered explicit answers such as `A. same`, producing 1,225/1,570
(78.03%) with 99.81% coverage. Treat that change only as parser/format evidence,
not a generation or model-quality improvement. SemanticQA LCC was 121/305
(39.67%). The 68 shadow cases were unvalidated and were not used as published
gold. One candidate's historical run does not select the final model.

The prior run also demonstrated why runtime provenance matters: an earlier
upstream llama.cpp binary failed Kaggle's libc ABI before inference, while the
pinned Prism vendor build worked. The canonical workflow therefore uses verified
prebuilt receipts and never treats ABI failure as bad model quality.

## Resume / interruption safety

vLLM common-screen checkpoints are atomic. Resume is accepted only when existing
outputs are the exact task-ID prefix and model revision, task hash, benchmark
revision, prompt mode, decoding parameters and topology all match. Duplicates,
gaps, reordered IDs or changed configuration are rejected. The contract is
regression-tested by `test_resume_contract.py`.

Do not splice results from different configurations.

## Completion artifacts

At minimum preserve privately:

- `benchmark-preparation.json`;
- `preflight.json`;
- per-runtime install/verification receipts;
- Hub artifact preflight receipts;
- every attempted command/log;
- raw model result JSON;
- protocol diagnostics;
- promotion validation for common full runs;
- `candidate-matrix.json` / `.md`;
- `roster-orchestration.json`;
- finalist streaming latency artifacts.

Do not publish private answer keys, author-review keys or benchmark outputs unless
explicitly requested.

After the run finishes or fails, terminate local servers and verify Kaggle's
control plane shows the session stopped and accelerator off/None. Zero GPU
utilization alone is not proof that the cloud session stopped.
