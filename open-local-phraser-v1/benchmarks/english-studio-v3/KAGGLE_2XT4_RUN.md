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
