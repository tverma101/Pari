# Native BLiMP likelihood lane (Issue #68)

This lane produces **minimal-pair causal likelihood** evidence for the Kaggle
2xT4 finalist roster, through the exact runtime formats those finalists
actually use: `vllm` and `gguf`/llama.cpp.

It is a separate evidence lane from Pari's prompted BLiMP screen
(`english-core-public-fast`, 670 prompted A/B cases). Prompted acceptability
and minimal-pair likelihood are different constructs, they are reported side
by side, and they are **never averaged**. A ranking flip between the two lanes
is a protocol-sensitivity diagnostic, not an error to be smoothed away.

Nothing in this directory reads, writes, or depends on the prompted BLiMP
artifacts. A test enforces exactly that.

## What is pinned, and where the pin came from

Every identity below was read out of a clean checkout of
`EleutherAI/lm-evaluation-harness` at commit
`d6de81643928d653435c431bae19945d41d32520` (2026-09-14T10:51:05Z) and out of
the pinned `nyu-mll/blimp` dataset revision. The full manifest, including every
sha256, lives in [`native-blimp-protocol.json`](native-blimp-protocol.json). The
manifest's own sha256 is recorded in every receipt, so a changed pin invalidates
old receipts rather than silently reinterpreting them.

| Identity | Value |
| --- | --- |
| harness commit | `d6de81643928d653435c431bae19945d41d32520` |
| harness package version | `lm_eval` `0.4.14.dev0` (from `pyproject.toml` at that commit) |
| BLiMP task group | `lm_eval/tasks/blimp/_blimp.yaml` (67 subtasks, `aggregate_metric_list: acc / mean / weight_by_size: false`) |
| shared task template | `lm_eval/tasks/blimp/_template_yaml` (`output_type: multiple_choice`, `validation_split: train`, `doc_to_target: 0`, `doc_to_choice: {{[sentence_good, sentence_bad]}}`, `num_fewshot: 0`) |
| dataset | `nyu-mll/blimp` revision `877fba0801ffb7cbd8c39c1ff314a46f053f6036`, 67 configs x 1000 rows = 67,000, license `cc-by-4.0` |
| vLLM backend | `lm_eval/models/vllm_causallms.py`, `@register_model("vllm")` |
| GGUF backend | `lm_eval/models/gguf.py`, `@register_model("gguf", "ggml")`, class `GGUFLM` |
| llama.cpp minimum | the modern `logprobs.content` shape introduced by ggml-org/llama.cpp PR 10783, merged 2024-12-19, merge commit `57bb2c40cd94c5a09f5210ed8264cc93b21c4b7e` |

### Two corrections worth knowing before reading results

**The BLiMP task's `output_type` is `multiple_choice`, not `loglikelihood`.**
The published construct is still minimal-pair likelihood:
`ConfigurableTask.construct_requests` turns each BLiMP item into two
`Instance(request_type="loglikelihood")` requests, one per sentence in
`[sentence_good, sentence_bad]`, and `doc_to_target: 0` makes the acceptable
sentence the target. The lane follows the pinned implementation and invents no
Pari-specific rule.

**The pinned harness BLiMP YAML carries no dataset revision.** Upstream
therefore resolves `nyu-mll/blimp` at whatever `main` points to. This lane binds
the revision out-of-band and blocks promotion when the resolved revision is not
the pinned one.

### What each backend actually does

`vllm` scores through `SamplingParams(temperature=0, prompt_logprobs=1,
max_tokens=1, detokenize=False)`. `_loglikelihood_tokens` sums
`outputs.prompt_logprobs` over the continuation span and derives `is_greedy`
from the per-position argmax. No `echo`, no chat template.

`gguf` scores by **exact teacher forcing, one HTTP request per continuation
token**: the natural prefix is sent as a token-id array with
`logit_bias=[[target_id, 100]]`, the server is forced to sample that token, and
the pre-sampling logprob is read back from `choices[0].logprobs.content[0]`. It
requires `/v1/completions`, `/tokenize` (always called with `add_special=True`,
so BOS is unavoidably on), and optionally reads `/props` for the slot count.

## Fail-closed rules

These are enforced in code, not by convention, and each has a test.

| Rule | What happens when it is violated |
| --- | --- |
| Harness identity drift | `harness_identity` gate fails; the run never starts. Commit SHA, per-file sha256 and the two BLiMP directory tree hashes must all match. |
| Dataset revision drift | `dataset_revision` gate fails. Unresolvable counts as a mismatch, never a pass. |
| Chat-template drift | `chat_template_off` gate fails. `--apply_chat_template`, `--fewshot_as_multiturn`, `--system_instruction` and `enable_thinking` are all rejected, and a harness-recorded `apply_chat_template` in the output is rejected on the way back in. |
| A subset offered as full | `no_subset` gate fails. `mode: smoke` with `promotable: true` is refused; `--limit`/`--samples` are forbidden flags; `n-samples[*].effective` must equal 1000 for all 67 subtasks. |
| Missing logprobs | `logprobs_present` gate fails. A GGUF server without `logprobs.content`, without `top_logprobs`, or that will not sample the forced token is `native_likelihood_unavailable`. There is no fallback to generation or to prompted accuracy. |
| Hidden truncation | `no_truncation` gate fails. The pinned vLLM backend only *warns* when it left-truncates, so the runner scans the harness log for that warning and rejects the run. |
| Runtime error as a zero | A non-zero harness exit, a traceback, a CUDA OOM, missing logprobs or exhausted retries are recorded in `runtimeErrors`, and the receipt is demoted to `promotable: false`. A genuinely low accuracy is still a score; only a failed run is a failure. |
| Aggregate mismatch | `aggregate_recomputed` gate fails. The group `acc` must reproduce as the **unweighted** mean of the 67 per-subtask accuracies, recomputed independently. A subset presented as full cannot satisfy this. |
| Coverage gap | `task_identity` gate fails. The result must carry exactly the 67 pinned subtask names. |
| Unbound context length | `no_truncation` gate fails. The vLLM backend must be given exactly one of `max_model_len` or `max_length`; with neither, it resolves the limit from the model config and the no-hidden-truncation guarantee is not bound. |

## Cross-backend comparability

Before ranking different candidate formats against each other, prove the two
backends implement the same intended scoring semantics:

```bash
python3 run_native_blimp.py parity \
  --fixture parity-fixture.example.json \
  --output /kaggle/working/results/native-blimp/parity.json
```

The comparator checks item identity/order, preferred-sentence decision,
per-item loglikelihood where the receipts expose it, and per-subtask accuracy,
against tolerances the fixture pins. It refuses a same-backend "comparison", it
refuses to mix two different model artifacts (a quantized-versus-unquantized
difference is model evidence, not evaluator parity), and it refuses incomplete
runs.

## Exact T4 commands

There is no Kaggle job in this change. These are the commands to run when one
is authorized, and they are the commands the runner was built around.

### Phase A, accelerator OFF, no GPU

```bash
git clone https://github.com/EleutherAI/lm-evaluation-harness.git \
  /kaggle/working/lm-evaluation-harness
git -C /kaggle/working/lm-evaluation-harness checkout d6de81643928d653435c431bae19945d41d32520
pip install -e "/kaggle/working/lm-evaluation-harness[gguf]"

cd /kaggle/working
python3 native-blimp/native_blimp_protocol.py check-harness \
  --checkout /kaggle/working/lm-evaluation-harness
python3 native-blimp/native_blimp_protocol.py check-dataset
python3 native-blimp/test_native_blimp.py
python3 native-blimp/run_native_blimp.py preflight \
  --config native-blimp/configs/vllm-t4-smoke.example.json \
  --checkout /kaggle/working/lm-evaluation-harness
```

`check-harness` and `preflight` must both exit 0 before any T4 time is spent.

### Phase B, T4 enabled, one notebook, vLLM smoke then full

```bash
# smoke: proves the lane executes and logprobs are usable. Never promotion evidence.
python3 native-blimp/run_native_blimp.py execute \
  --config native-blimp/configs/vllm-t4-smoke.example.json \
  --checkout /kaggle/working/lm-evaluation-harness \
  --results-dir /kaggle/working/results/native-blimp/qwen35-2b-smoke

# full: the 67-subtask promotion lane.
python3 native-blimp/run_native_blimp.py execute \
  --config native-blimp/configs/vllm-t4-full.example.json \
  --checkout /kaggle/working/lm-evaluation-harness \
  --results-dir /kaggle/working/results/native-blimp/qwen35-2b-full

python3 native-blimp/run_native_blimp.py verify \
  --receipt /kaggle/working/results/native-blimp/qwen35-2b-full/native-blimp-receipt.json
```

### Phase B, T4 enabled, one notebook, GGUF lane

Start the owned llama-server first, with a real `--parallel` slot count and
CUDA offload, then prove it can score before spending a full run on it:

```bash
python3 native-blimp/native_blimp_protocol.py probe-gguf \
  --base-url http://127.0.0.1:8080 --timeout 60

python3 native-blimp/run_native_blimp.py execute \
  --config native-blimp/configs/gguf-llamacpp-t4-full.example.json \
  --checkout /kaggle/working/lm-evaluation-harness \
  --results-dir /kaggle/working/results/native-blimp/bonsai-27b-q1_0-full \
  --timeout 120
```

`probe-gguf` must exit 0 before `execute`. If it does not, the runtime is
`protocol_unavailable` for the native lane; do not substitute the Word Studio
prompted screen.

### Cleanup

After each notebook, stop the llama-server and confirm the Kaggle control plane
reports the accelerator off. An idle server or zero GPU utilization is not
proof of shutdown.

## Remaining qualification requirement

**One notebook per backend, before this lane touches the roster.** The
qualification bar is: on exactly one Kaggle T4 notebook, `execute` in `mode:
full` produces a receipt with `promotable: true`, `outcome: pass`, all gates
green, 67/67 subtask coverage at 1000 rows each, and a `verify --receipt` run
that re-validates clean. That must hold once for the vLLM backend and once for
the GGUF/llama.cpp backend.

Each finalist that gets promoted then needs both:

1. a real full 67-subtask native run on T4 with a complete receipt, and
2. a parity fixture whose two sides describe the **same model artifact**, so
   cross-format ranking is not silently comparing two different models.

This lane is finalist evidence. Do not add 67,000 native likelihood evaluations
to the six-model first-pass screen; the issue explicitly scopes it to finalists,
and the runtime economics of the screen do not justify it.

## Files

| File | Role |
| --- | --- |
| `native-blimp-protocol.json` | The frozen pin manifest. Every identity, hash, forbidden flag and promotion gate. |
| `native-blimp-config.schema.json` | Frozen run-config schema. |
| `native-blimp-receipt.schema.json` | Provenance-bound receipt schema. |
| `native_blimp_protocol.py` | The contract: identity verification, argv construction, server probe, output scanning, result validation, parity, plus a small inspection CLI. |
| `run_native_blimp.py` | `plan` / `preflight` / `execute` / `verify` / `parity`. |
| `test_native_blimp.py` | 68 CPU/synthetic tests. No GPU, no model, no network, no harness execution. |
| `configs/*.example.json` | Worked vLLM smoke, vLLM full and GGUF full configs. Replace the `REPLACE_WITH_...` placeholders before use. |
| `parity-fixture.example.json` | Cross-backend parity fixture template. |

## Tests

```bash
cd native-blimp && python3 test_native_blimp.py
```

The tests cover the ten claims the issue asks for, including one that loads the
**real pinned `gguf.py`** with stubbed imports and replays its actual scoring
loop against an in-process fake llama-server, so the teacher-forcing and
`add_special` behaviour under test is upstream's code, not a copy of it. Two
more drive the runner and validator CLIs end to end: one proves a failed run
still writes a schema-valid non-promotable receipt, and one proves `verify`
catches a harness output file that drifted after the run.

Tests that need the real pinned harness checkout look for it at
`/tmp/lmeval-pin-68` and print a skip line when it is absent, so the file is
still runnable on a machine that has not cloned it. Run
`native_blimp_protocol.py check-harness --checkout <path>` after cloning to
confirm the checkout is byte-identical to the pin.

## Known limits

- The GGUF backend scores one HTTP request per continuation token. That is the
  pinned upstream implementation, and it is slow. The `--parallel` slot count
  is the throughput lever, and it is recorded in the receipt.
- `loglikelihood_rolling` is not implemented by the pinned GGUF backend, so
  this lane cannot produce perplexity through that path. BLiMP does not need it.
- The pinned harness's own `README.md` still labels the backend "Llama.cpp (via
  llama-cpp-python)". That is stale: `gguf.py` imports only `requests` and talks
  HTTP to `llama-server`. The lane pins the code hash, not the prose.
- An open upstream issue (#4158) reported the GGUF backend non-functional
  against a live server, but its quoted code matches the pre-rewrite
  implementation and no longer exists at the pinned commit. The
  `logit_bias`-forced-sampling approach this lane depends on is therefore
  code-verified but **not yet runtime-verified**, which is exactly what the
  one-notebook GGUF qualification above is for.
