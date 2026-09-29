# Kaggle 2×T4 execution protocol

This is the operational companion to GitHub Issue #25. It is intentionally
separate from the older Mac/MLX shootout. Candidate feasibility and quality are
unmeasured until the pinned run completes.

## Safe setup and evidence boundary

1. Keep the Kaggle notebook as a private draft. Leave GPU at `None` until the
   fixed-screen task file, manifests, prompt contract, and runner smoke checks
   are present and pass.
2. Leave Internet on only for the pinned source/package/model fetches. Run
   inference locally in the Kaggle runtime; do not send prompts to an inference
   API or invoke an LLM judge.
3. Use the official public upstream model repositories and immutable commits in
   `kaggle-candidate-roster.json`. Do not duplicate public weight files as new
   Kaggle model uploads. Keep generated answer keys, private review material,
   prompts/outputs, and run artifacts inside the private notebook/workspace.
4. Then select `GPU T4 x2`, record the GPU/driver/Python/CUDA/runtime versions,
   and start with a bounded smoke run. A T4 reports CUDA compute capability
   7.5, which meets vLLM's stated GPU minimum; this does **not** guarantee that
   a particular model/runtime/quantization fits or works.
5. Run the complete 1,943-case English Core screen only after smoke output and
   provenance checks pass. Never substitute partial output for a full screen.

Kaggle UI checks: the notebook title should be `Pari Issue 25 — English Core +
Word Studio`; keep the draft private and the accelerator at `None` until the
preflight is complete. Do not use `Share`, `Publish`, or a public dataset/model
visibility option for this evaluation.

## Frozen benchmark build

Use the exact benchmark Git commit saved in the result metadata. In a fresh
Kaggle working directory:

```bash
git clone --branch bench/english-studio-v3 https://github.com/tverma101/Pari.git pari
cd pari/open-local-phraser-v1/benchmarks/english-studio-v3
git checkout BENCHMARK_COMMIT
bash self-check-english-core.sh
python build-english-core-public-fast.py \
  --blimp-revision 877fba0801ffb7cbd8c39c1ff314a46f053f6036 \
  --super-glue-revision 3de24cf8022e94f4ee4b9d55a6f539891524d646 \
  --glue-revision bcdcba79d07bc864c1c254ccfcedcce55bcc9a8c \
  --paws-revision 161ece9501cf0a11f3e48bd356eaa82de46d6a09
python build-semanticqa-lcc-english-core.py \
  --semanticqa-checkout /kaggle/working/semanticqa \
  --promotion
python build-english-core-fixed-screen.py
```

The fixed screen is a mechanical concatenation in this order: 68 fresh shadow
cases, 1,570 pinned public-fast cases, then 305 SemanticQA LCC cases. The
builder checks count, unique IDs, and model-visible gold leakage; it never
opens answer keys. Keep public-fast and SemanticQA evidence separate from the
`author_labeled_unvalidated` shadow lane when scoring.

## Runtime and candidate order

Start ordinary decoding first. For Qwen3.5 dense models use a short context
(`--max-model-len 8192`), text-only mode, and FP16 on T4 unless the runtime
reports another measured precision. Use one GPU for models that fit; use TP=2
only for the 35B GPTQ stretch candidate or where a measured latency comparison
justifies it. The 35B GPTQ candidate is a feasibility experiment, not an
assumption that two T4s suffice.

The current source docs disagree on Qwen3.5 integration details: the Qwen model
card says to use vLLM main/nightly and documents `qwen3_next_mtp`; the current
vLLM 4B recipe documents vLLM 0.17.0+ and MTP method `mtp`. Start with the
latest stable vLLM build that passes a smoke test, save its exact wheel/version,
and test each documented MTP config explicitly. If stable fails, run a
separately identified nightly attempt. Never call unsupported setup a speed
result, and never silently fall back from MTP to normal decoding.

Example complete-screen invocation (choose a fresh output filename per model
and runtime configuration):

```bash
python run-english-core-vllm.py Qwen/Qwen3.5-2B \
  /kaggle/working/results/qwen35-2b.vllm.json \
  --tasks english-core-fixed-screen.jsonl \
  --revision 15852e8c16360a2fea060d615a32b45270f8a8fc \
  --benchmark-revision BENCHMARK_COMMIT \
  --checkpoint-type instruct --quantization bf16_checkpoint_cast_to_fp16_on_T4 \
  --prompt-mode chat --dtype half --language-model-only \
  --max-model-len 8192 --tensor-parallel-size 1 --batch-size 32
```

Run the documented MTP methods as separate runs after the normal baseline:

```bash
# One config per output file; do not overwrite the baseline.
python run-english-core-vllm.py Qwen/Qwen3.5-2B /kaggle/working/results/qwen35-2b.mtp.json \
  --revision 15852e8c16360a2fea060d615a32b45270f8a8fc \
  --benchmark-revision BENCHMARK_COMMIT --checkpoint-type instruct \
  --quantization bf16_checkpoint_cast_to_fp16_on_T4 --prompt-mode chat --dtype half \
  --language-model-only --max-model-len 8192 --tensor-parallel-size 1 \
  --speculative-method mtp --speculative-tokens 1
```

The result runner writes atomically after each batch. A capped `--limit` run is
explicitly `incomplete` and is only for setup/smoke validation. The artifact
hash binds the pinned Hub file inventory and immutable blob IDs; it is not a
second full bytewise hash of the downloaded tensor files. Keep runtime version,
model revision, quantization, tokenizer/template hash, decoding config, exact
task-file hash, and hardware metadata together.

For Bonsai, use the official Q1_0 GGUF files and the vendor's pinned
`PrismML-Eng/llama.cpp` commit `842b1880415d6f508f03b789e5ce70194def7bfd`;
build flags and GPU offload are part of runtime identity. Build the local
server at that commit, download the exact `file` in the candidate roster at its
HF commit, and run `run-english-core-llamacpp.py` against the server's loopback
OpenAI-compatible endpoint. Do not substitute stock llama.cpp or DSpark without
a separately identified run. The model card reports its own hardware results;
those do not predict Kaggle T4 latency. No MTP label is assigned to Bonsai
unless the chosen checkpoint/runtime exposes a working draft path and the
ordinary-vs-speculative pair is measured.

### Pinned PrismML prebuilt ABI rerun

The first private CLI attempt used upstream llama.cpp `b11179` and failed before
inference because it requires `GLIBC_2.38` and `GLIBCXX_3.4.32`, while Kaggle
provides glibc 2.35. CUDA libraries resolved; this is an OS ABI mismatch, not
a T4 or Bonsai-model failure. Reject this exact binary for Kaggle.

The follow-up compatibility experiment uses an official pinned PrismML prebuilt;
it does not change the candidate model or frozen tasks. The vendor's official
release is `prism-b10735-842b188`, built from the exact candidate-roster commit
`842b1880415d6f508f03b789e5ce70194def7bfd` and described as a PrismML fork
prebuilt with Q1_0 support. Its CUDA 12.8 x64 asset is
`llama-prism-b10735-842b188-bin-linux-cuda-12.8-x64.tar.gz` (168,052,249 bytes;
published SHA-256
`5cbac5269804e4eb63676aeaec1ee7d4cff6e22b87da91de9b05795bf635998e`). The
[official release page](https://github.com/PrismML-Eng/llama.cpp/releases/tag/prism-b10735-842b188)
and [pinned release workflow](https://github.com/PrismML-Eng/llama.cpp/blob/842b1880415d6f508f03b789e5ce70194def7bfd/.github/workflows/release-prism.yml)
show the asset and an Ubuntu 22.04 / CUDA 12.8 build. That is a promising match
for Kaggle's observed glibc 2.35, but compatibility remains a hypothesis until
the runner's exact link and launch checks pass.

The CLI runner verifies the release checksum, checks `ldd` for both
`llama-server` and `libggml-cuda.so`, and invokes version/help checks **before**
fetching the 3.8 GB model. It records Kaggle's libc and the exact source commit.
Only after runtime checks pass does it fetch the pinned model and verify its
known SHA-256. It then requires a 16-case smoke, explicit CUDA layer-offload
evidence, the full frozen screen, and the separate 112-case Word Studio slider
suite. The completed v4 result below establishes runtime compatibility and an
initial quality/latency baseline, but not model selection. This is a prebuilt
artifact of the pinned PrismML fork, not stock upstream and not a fresh source
build. Bonsai Q1_0 has no validated MTP path,
so this run does not claim speculative-decoding speedup. The
[Bonsai runtime notes](https://github.com/PrismML-Eng/Bonsai-demo/blob/main/README.md)
document support for the original Q1_0 model format; that does not establish
compatibility for every Bonsai quantization or Bonsai 2's ternary Q2_0 path.

The first PrismML-prebuilt CLI run (kernel version 3, 2026-09-25) verified the
published binary hash, resolved all shared libraries on Kaggle glibc 2.35, and
downloaded the pinned 3,803,452,480-byte model with the expected hash. The
server log said `model loaded`, but its default verbosity omitted the CUDA
layer-allocation lines; the runner correctly stopped before sending any task
because it could not prove GPU offload. This is **not** a Bonsai score, nor
proof that the server ran on CPU. The pinned server README documents
`--list-devices`, `--device`, and `--verbose` (log all messages):
[pinned server CLI documentation](https://github.com/PrismML-Eng/llama.cpp/blob/842b1880415d6f508f03b789e5ce70194def7bfd/tools/server/README.md).
The next bounded attempt enumerates CUDA before downloading weights, explicitly
selects `CUDA0`, enables verbose startup evidence, and waits for that evidence
before running the smoke or benchmark. The job ended with error; Kaggle's
control plane was verified afterward with Draft Session off, accelerator
`None`, and Internet off.

### Version 4 execution and results

The fourth private CLI submission (kernel version 4; run ID
`20260925T172959Z`) used Kaggle kernel slug
`nirasushi/pari-issue-25-bonsai-27b-q1-0-upstream-prebuilt`; the slug retains a
legacy `upstream-prebuilt` name, but version 4 used the PrismML runtime below.
It passed preflight, the 16-case smoke, GPU-offload checks, the
1,943-case fixed screen, and all 112 Word Studio cases at strengths 15, 40, 60,
and 90. The private archive SHA-256 is
`1d5cb9005d41ea1f6659b0bff49fa714ac9e77db398bbde7a188b496fe9bf6a9`. It
contains outputs and summaries, not the private answer keys.

The exact model was `prism-ml/Bonsai-27B-gguf` revision
`f10afb355f104535e3e3e98cf7ab7795c72bd292`, file
`Bonsai-27B-Q1_0.gguf` (3,803,452,480 bytes; SHA-256
`17ef842e47450caeb8eaa3ebfbbab5d2f2278b62b79be107985fb69a2f819aa0`). The
official PrismML CUDA 12.8 prebuilt hash matched the release. Kaggle exposed
two T4s; this run used only `CUDA0`, and startup logs verified 65/65 layers
offloaded to that T4. The server stopped before export. MTP was not used or
claimed. Total run time was 3,748 seconds; the full screen's recorded wall time
was about 1,749 seconds. First-token latency over the 1,943 screen outputs was
0.676 seconds median / 1.385 seconds p95. For Word Studio, complete-output
latency was 19.64 seconds median / 27.06 seconds p95; its first-token median
was 1.216 seconds. Word Studio outputs still require human review and have no
automated quality score.

The original public-fast score uses the strict parser and remains the frozen
benchmark baseline. An offline parser replay against the exact same raw outputs
does not change prompts, generations, or labels:

| Public-fast scoring view | Correct / cases | Accuracy (invalid as wrong) | Valid-output coverage |
| --- | ---: | ---: | ---: |
| Frozen run score, strict parser | 943 / 1,570 | 60.06% | 74.97% |
| Offline replay, anchored-explanation parser | 1,225 / 1,570 | 78.03% | 99.81% |

The replay parsed 390 additional outputs; 282 were correct and 108 wrong, with
three outputs still invalid. Typical previously rejected answers were
`A. same`, `A. acceptable`, or `A. different`: the selected letter was
explicit, but the scorer discarded it because explanatory text followed.
Treat the accuracy increase as a parser/format-coverage result, not improved
generation or a model-quality uplift. The separate SemanticQA LCC lane scored
121/305 (39.67% accuracy; macro-F1 35.44%; 100% output coverage). The 68 shadow
cases remain unvalidated and unscored. Do not combine these protocols into one
number or select a model from this one candidate's screen.

Kaggle reported the job complete. The control page showed the session off,
accelerator `None`, and Internet off before results were downloaded. Local
kernel metadata was also restored to GPU/network off. Results remain in a
private temporary directory and were not added to Git or published.

For repeatable submission, use the official [Kaggle CLI kernel guide](https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels.md)
with account credentials already configured locally (never place a token in
notebook code). Prefer a
fresh, private script kernel for an isolated run: `kernels push` executes the
uploaded code, so pushing this historical multi-run notebook would replay its
prior cells. Keep the local metadata at `enable_gpu: false`,
`enable_internet: false`, and an empty `machine_shape`; only temporarily enable
the exact T4×2 accelerator and Internet for an explicitly authorized run and
its public model/runtime downloads, then restore those local defaults. Use CLI
status/output/logs for runs and fetch only the intended result artifact. The
[Kaggle CLI v2.2.4 changelog](https://github.com/Kaggle/kaggle-cli/blob/v2.2.4/CHANGELOG.md)
documents the SSE implementation for `kernels logs --follow`. In this run,
installed Kaggle CLI 2.2.4 returned 404 when that command was given
`owner/kernel/4`, but streamed live logs when called with `owner/kernel`
(without the version suffix). This is an observed invocation-specific result,
not a claim that all version-specific log requests fail. A 404, missing CLI
status, or script error is not evidence that the provider session stopped.
After completion or failure, verify the draft session is off, the
accelerator is `None`, and Internet is off in Kaggle's control plane. The
documented CLI commands do not provide a stop-and-disable operation.

## Word Studio slider suite

Use `build-word-studio-strength-suite.py` with the hand-authored synthetic seed
and the existing interactive V1 seed. It emits 112 model-visible tasks across
four predeclared strengths (15, 40, 60, 90), plus a separate author-review file.
The task file excludes expectations. Strength semantics are a Pari product
choice, not a scale claimed by the literature: increasing the slider permits
more wording/structure change, never stronger opinions or altered facts.

The prompt requests 10 distinct alternatives so the whole-completion duration
approximates time-to-10 for this one-shot generation interface. The runner's
first-token latency is only a first-token proxy—not time to the first
human-approved option. Parse and inspect actual alternatives; report the count
of valid unique options and latency separately. No LLM judge or automatically
invented quality score is used. Human review must separately check semantic
anchors, voice/register, naturalness, strength monotonicity, and harmful
meaning flips. These cases remain synthetic/unvalidated until that review.

## Completion and archival

Score only with the lane-specific existing scorers and their answer files. Run
paired/robustness and official/native finalist lanes after the fixed screen;
keep Word Studio metrics separate from English Core dimensions. Save outputs
as private Kaggle working artifacts, inspect status and hashes, and only then
prepare a public-safe summary that contains results/provenance—not answer keys
or rehosted benchmark examples whose upstream license is unclear.
