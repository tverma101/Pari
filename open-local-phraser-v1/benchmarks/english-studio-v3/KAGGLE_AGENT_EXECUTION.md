# Kaggle agent execution — literal instructions, no improvisation

This file exists so an execution agent does **not** decide how to run the benchmark.
Follow these commands literally. Do not redesign, optimize, repair, or substitute
components during the run.

The machine-readable authority for this file is `kaggle-runbook-contract.json`, and
`test_kaggle_runbook_consistency.py` fails the mandatory self-check if the two
disagree. If this prose and that contract ever conflict, stop and report the drift
instead of choosing a reading.

## Hard rules

1. Do not change benchmark prompts, weights, task files, parsers, model revisions, quantization, dtype semantics, or candidate identity after seeing results.
2. Do not compile C++, CUDA, Rust, vLLM, llama.cpp, FlashAttention, Triton extensions, or model-specific kernels.
3. Never run `cmake`, `ninja`, `make`, `nvcc`, `cargo build`, `setup.py build`, `pip install -e`, `--no-binary`, or a source-distribution fallback.
4. Use only the pinned prebuilts in `kaggle-prebuilt-runtimes.json`. The dispatcher installs/verifies them automatically.
5. If a compatible pinned binary/model configuration fails, preserve the artifact and move on. Do not invent a workaround.
6. Wrong, malformed, verbose, refusal, truncated, or low-quality model answers are benchmark observations. Do not retry them for a prettier answer.
7. Runtime failure is never English score = 0. Keep it as `runtime_unqualified`.
8. Never merge from this execution task.
9. Product suites run only for the frozen finalist set. Every roster candidate is screened; only finalists do product work.

## Canonical entry points

- `prepare-kaggle-benchmark.py` — CPU/data preparation before GPU time.
- `verify-kaggle-benchmark-preparation.py` — proves generated tasks still match their preparation receipt.
- `run-kaggle-roster.py` — run the frozen roster mechanically.
- `run-kaggle-candidate.py` — one candidate/stage; normally called by the roster runner.
- `run-kaggle-vllm-streaming-latency.py` — finalist interactive latency only.
- `build-kaggle-candidate-matrix.py` — explicit completed/failed/not-run matrix.
- `KAGGLE_BENCHMARK_HARDENING.md` — failure and evidence contract.
- `kaggle-runbook-contract.json` — machine-readable stage/applicability/test registry.
- `test_kaggle_runbook_consistency.py` — proves this runbook matches that contract.

The runners themselves handle:

- the Q0→Q4 qualification ladder and its receipt ordering;
- product-suite generation and exact case-count validation;
- exact model revisions;
- vLLM vs Prism runtime routing;
- pinned-binary install/receipt verification;
- Prism CUDA 12.8 → 12.4 **prebuilt-only** selection, each rung gated by an actual-binary compatibility probe;
- Hub artifact/disk preflight;
- allowed OOM batch fallback;
- raw output preservation;
- protocol diagnostics;
- candidate matrix updates.

Do not duplicate those decisions manually.

## Pinned runtime builds

### vLLM 0.30.0 CUDA 12.9 x86_64

Registry artifact id: `vllm-0.30.0-cu129-linux-x86_64`

Release: `https://github.com/vllm-project/vllm/releases/tag/v0.30.0`

Wheel: `https://github.com/vllm-project/vllm/releases/download/v0.30.0/vllm-0.30.0%2Bcu129-cp38-abi3-manylinux_2_28_x86_64.whl`

SHA-256: `e98cb69659bfcfc849cf11ce0781a7161d40b02b51a6c3636924a5909f2aabcc`

### Prism llama.cpp pinned commit `842b1880415d6f508f03b789e5ce70194def7bfd`

CUDA 12.8 registry artifact id: `prism-llamacpp-b10735-cuda12.8-linux-x86_64`

CUDA 12.8 binary:
`https://github.com/PrismML-Eng/llama.cpp/releases/download/prism-b10735-842b188/llama-prism-b10735-842b188-bin-linux-cuda-12.8-x64.tar.gz`

SHA-256: `5cbac5269804e4eb63676aeaec1ee7d4cff6e22b87da91de9b05795bf635998e`

CUDA 12.4 registry artifact id: `prism-llamacpp-b10735-cuda12.4-linux-x86_64`

CUDA 12.4 fallback binary:
`https://github.com/PrismML-Eng/llama.cpp/releases/download/prism-b10735-842b188/llama-prism-b10735-842b188-bin-linux-cuda-12.4-x64.tar.gz`

SHA-256: `b58caa10e38ea2d3af419bc1c908f785b5f8756b07c98cb1752d50e1e985d4c6`

Both Prism binaries are vendor prebuilts from the same pinned source commit. No source build is permitted.

### Prism selection is an actual-binary probe

The selector prefers CUDA 12.8 and falls back to CUDA 12.4. Metadata verification is
necessary but not sufficient: each rung must pass a bounded probe of the actual pinned
binary (`--version`, `--list-devices`, CUDA/T4 evidence, clean exit within a timeout)
before it can be selected. Compatibility is never inferred from version-number
ordering, and a binary that is present but will not start on this driver is a real
fallback rather than a metadata mismatch. Every rung attempted is preserved, and
`fallbackEligible` distinguishes a genuine binary-compatibility step-down from any
other failure.

## Known blocker: the vLLM dependency closure is not locked

`kaggle-prebuilt-runtimes.json` requires the full serving dependency closure to be
version+hash bound before the pinned vLLM wheel may be installed. That lock is
**not** resolved yet, and no `kaggle-runtime-locks/` lock file exists in the tree.

Until it lands:

- installing the vLLM runtime records `runtime_unqualified` with classification
  `dependency_lock_pending` and stops;
- vLLM candidates therefore cannot be qualified, and no vLLM screen, product, or
  latency result may be reported from that runtime;
- there is no fallback to unpinned `pip` resolution, and no silent upgrade or
  reinstall to make an import pass.

Do not attempt to work around this. It is a real blocker, and resolving it is a
separately authorized runtime-development task, not part of a benchmark run. The
Prism path is unaffected: it has no dependency lock to resolve.

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

### Data preparation is a locked, ABI-specific lane

`prepare-kaggle-benchmark.py` installs the public-data stack from a committed
hash-pinned lock, not from floating resolution. Qualified profiles:

- CPython **3.10** on Kaggle Linux x86_64 — `locks/kaggle-data-prep-cp310-linux-x86_64.txt`
- CPython **3.11** on Kaggle Linux x86_64 — `locks/kaggle-data-prep-cp311-linux-x86_64.txt`

Everything else **fails closed** before any install: CPython 3.12/3.13, any non-CPython
implementation, and any non-Linux/non-x86_64 platform. Those profiles have no
verified ABI-specific wheel lock, so they are unsupported rather than approximated.

For a supported profile the preparation step verifies the committed lock's SHA-256
pin against the lock bytes before installing, installs with
`--require-hashes --only-binary=:all: --no-deps` into an isolated venv, and then
verifies the installed set against the lock and runs `pip check`. The preparation
receipt records `dependencyLock` state `verified` with the lock file, its SHA-256,
the package count, the resolver provenance, and the install flags, alongside the
interpreter implementation, version, cache tag, machine, and system.

One caveat stays open: the actual Kaggle image ABI has not yet been confirmed by the
private preparation kernel. Treat a qualified profile as *lock-verified*, not
image-ABI-proven, until that kernel run reports the same profile.

If any S1 command fails, STOP. That is a benchmark/data-preparation failure, not a
model result. Do not turn the GPU on to debug it.

`self-check-english-core.sh` is the aggregation gate for the landed P0 hardening
contracts. It fails closed, still at accelerator-off, when:

- a contract module listed in `kaggle-runbook-contract.json` is missing or renamed;
- a landed contract's test command is not actually invoked by the self-check;
- this runbook disagrees with the contract, the CLI stage model, the pinned runtime
  registry, or the frozen generation ladder;
- tracked source identity is not clean and verified.

## Q0 — enable T4×2 and prove the environment

Only after S1 succeeds, enable Kaggle `GPU T4 x2`, then run:

```bash
python kaggle-preflight.py --output /kaggle/working/results/preflight.json
```

If this fails, STOP. Do not download a model. The environment is unqualified.

The preflight records real Kaggle markers, exactly two T4s, compute capability 7.5,
VRAM/free VRAM, existing GPU processes, CUDA/driver, disk, libc, topology and P2P.
P2P warnings alone do not disqualify independent one-GPU replicas.

This is a real Kaggle 2×T4 requirement. A result without real Kaggle T4 evidence is
`environment_unqualified` and cannot enter the quality comparison; local CUDA, Colab,
A10/A100/L4, Apple Silicon, and CPU runs are development evidence only.

## Q1–Q4 — screen every roster candidate

Run the screening phase only. Every roster candidate walks the qualification ladder;
no product work happens here.

```bash
python run-kaggle-roster.py \
  --phase english \
  --probe-mtp-smoke \
  --benchmark-revision "$BENCHMARK_REVISION"
```

`--phase english` schedules the screening chain and nothing else. The broader
`--phase all` choice stays available in the CLI for debugging, but it is not part of
the canonical sequence because it schedules product suites for every candidate rather
than for the frozen finalists.

For each candidate the runner walks these gates in order, stopping that candidate when
a gate fails:

| gate | what it proves | runner stage |
| --- | --- | --- |
| Q0 | environment preflight: topology, VRAM, runtime availability | — |
| Q1 | exact model/tokenizer/runtime load, GPU placement, no silent CPU fallback, one trivial generation, runtime still alive | — |
| Q2 | frozen response-protocol smoke | `smoke` |
| Q3 | bounded frozen English benchmark smoke | `benchmark-smoke` |
| Q4 | complete 1,943-case English Core screen | `full` |

Q2 is protocol evidence only and is never added to an English quality score. Q3 is a
registered frozen prefix subset of the canonical screen, not an ad-hoc task limit, and
the full screen does not start until Q3 succeeds.

### Requested is not applied

Every candidate result carries a `thinkingCapability` block recording whether the
non-thinking request was actually in effect. A requested flag is never evidence:

- `applied` / `verified_default` require a proof naming the mechanism that verified
  the template — the transformers `apply_chat_template` render, the llama.cpp server
  `/apply-template` output, or the vLLM server's own `/tokenize` count;
- a template that rejects `enable_thinking=false` reports `unverified`, never
  `applied`;
- a plain-prompt run reports `not_applicable` and carries no requested flag.

The block is part of the context-budget receipt and therefore inside the receipt
hash. `test_kaggle_thinking_capability.py` validates every emitted payload and fails
if any producer claims `applied` without a verification mechanism.

The roster runner first re-verifies the preparation receipt, task hashes/counts,
current Git revision, and T4 preflight. It refuses to start a model if any of those
are stale or incomplete. If a candidate fails a gate, later stages for that candidate
are skipped and the next candidate is attempted. Failure evidence stays on disk.

### GPU resource cleanliness between candidates

Around every candidate the roster runs the fail-closed resource gate from
`kaggle_gpu_resource_gate.py`, in addition to the exclusive GPU lease:

1. before each candidate, the required GPUs must show no foreign compute workload
   above the documented baseline and enough free VRAM to load;
2. after each candidate, quarantine verifies owned processes exited, waits a bounded
   cooldown, resnapshots, and compares against that candidate's pre-run baseline.

A blocked gate is recorded as `infrastructure_blocked_resource_contamination`. That is
infrastructure, not candidate capacity: the roster dispatches no stage for a blocked
candidate, permits no linguistic or runtime-feasibility conclusion about it, and never
records the condition as a model `cuda_oom_*`. An OOM that happens after a clean
pre-run gate remains ordinary candidate/runtime capacity evidence. Sleeping longer
does not clear a contaminated handoff, because the comparison is against the baseline
rather than the newest reading.

Ownership is proven, never assumed. Only PIDs this run launched — the Q1 probe's
server-identity process tree — are eligible for cleanup. Foreign and unknown GPU
processes are recorded and block the stage; they are never signalled, because killing
someone else's workload to make a benchmark pass is never a valid cleanup. For a
tensor-parallel-1 candidate only GPU0 is required, so contamination on the unused
second GPU is recorded as a warning rather than a block; a tensor-parallel-2 candidate
must satisfy the gate on both GPUs.

The same `kaggle-protocol-smoke.jsonl` is used for both vLLM and Prism/Bonsai. It
covers forced choice, JSON alternatives, Unicode, negation, conditions, protected
names/numbers, longer context, repeated warm request, casual register, word↔phrase
behavior and sentence→1–3-word compression. Smoke is not an English score.

`--probe-mtp-smoke` runs only MTP methods explicitly listed for that candidate and
only after ordinary smoke succeeds. MTP failure does not invalidate ordinary decode.

## F — freeze the finalist set as an explicit artifact

Product work is finalist-only, so finalist membership must be an explicit, hashed
decision made after the Q4 screens exist — never inferred from whichever candidate
happened to screen best. Build `finalist-set.json` from the screened
`candidate-matrix.json`, then validate it with:

```bash
python build-kaggle-candidate-matrix.py \
  --results-dir /kaggle/working/results \
  --finalist-set /kaggle/working/results/finalist-set.json \
  --benchmark-revision "$BENCHMARK_REVISION"
```

Every finalist entry carries the candidate id, its `candidateConfigSha256`, its
candidate revision, and the path plus SHA-256 of the screen result it was frozen from.
The validator fails closed on an unknown candidate, a config/revision drift, or an
unresolvable or mismatched screen hash. A non-finalist is a screening result, not a
product candidate.

## Q5/Q6 — finalist-only product qualification

Only after the finalist set is frozen and validated:

```bash
python run-kaggle-roster.py \
  --phase product \
  --benchmark-revision "$BENCHMARK_REVISION" \
  --finalist-set /kaggle/working/results/finalist-set.json
```

This runs, for finalists only:

1. 112-case strength/rewrite Word Studio suite (`word-studio`, gate Q5);
2. 100-case cross-granularity Word Studio transform suite (`transform`, gate Q6).

Product stages use a single frozen batch of 1 and never walk the English generation
ladder. In the matrix, a non-finalist's product cells read `not_run_non_finalist`,
which is a real decision rather than a blank cell or a zero.

## Inspect completeness, not vibes

The roster runner regenerates these after attempts:

```text
/kaggle/working/results/candidate-matrix.json
/kaggle/working/results/candidate-matrix.md
/kaggle/working/results/roster-orchestration.json
```

Every roster model must remain visible as completed, failed, skipped after a prior
failure, or `not_run`. Do not delete failed candidates from the report.

## Q7 — finalist interactive latency and supported MTP

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

## Robustness and official evidence, as applicable

After the screen, the applicable prompt/order robustness, official SWORDS / JFLEG /
SemanticQA, and reproducibility-manifest steps run per `ENGLISH_CORE_ROBUSTNESS.md`
and the official-evaluator runners. These lanes stay separate from the common screen
and are never averaged into one pseudo-official score.

## Z — cleanup

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

## Frozen generation ladder

For canonical English-screen stages the frozen generation ladder is:

`32 -> 16 -> 8 -> 4 -> 1`

This is the runnable constant `CANONICAL_GENERATION_LADDER` in
`run-kaggle-vllm-candidate.py`. `test_kaggle_batch_policy.py` asserts that this
runbook, `KAGGLE_BENCHMARK_HARDENING.md`, and that constant all agree. 64 is
deliberately omitted; see `KAGGLE_BENCHMARK_HARDENING.md` for the reasoning.

A load OOM stops that exact configuration without walking the ladder. A generation
OOM walks it. `word-studio` and `transform` use the separate frozen single-batch
product policy and are never reported as having stepped down.
