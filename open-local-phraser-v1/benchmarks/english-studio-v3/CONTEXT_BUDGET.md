# Context-budget contract (P0, issue #45)

Scope: `run-english-core-vllm.py`, `run-english-core-llamacpp.py`,
`run-kaggle-vllm-streaming-latency.py`, and the shared module
`kaggle_context_budget.py`.

The point of this contract is narrow and mechanical: **a frozen prompt plus its
declared generation budget must be proven to fit the configuration that is about
to run it, before any generation request is sent.** Without it, one runtime
rejects an oversized request and another silently crops it, and the difference
shows up later as an apparent difference in English quality.

## What gets recorded

Every run writes `<result>.context-budget.json` and binds its SHA-256 into the
run receipt under `contextBudget`. The receipt holds, per task:

- raw task id;
- prompt mode and template identity (plus the template hash when the tokenizer
  exposes one);
- exact prompt token count **after** every system/user/template wrapper;
- the requested `maxNewTokens` actually sent for that task;
- the effective context limit and which source it came from;
- remaining headroom, fit verdict, and a structured violation on overflow;
- the run's per-candidate summary: max, p50/p95 prompt tokens, minimum headroom,
  violation count, and the violating task ids.

## Where the exact counts come from

| runner | counter | why it is exact |
| --- | --- | --- |
| `run-english-core-vllm.py` | pinned `transformers.AutoTokenizer` at the resolved commit | `tokenizer.encode(text, add_special_tokens=True)`, matching vLLM's encoding of a string prompt; the chat count is taken after `apply_chat_template(..., add_generation_prompt=True)` |
| `run-english-core-llamacpp.py` | the live server's `POST /tokenize` with `add_special=true, parse_special=true` | same arguments the llama.cpp inference path uses (`tokenize_input_prompts(vocab, mctx, prompt, true, true, ...)`); chat prompts are rendered by the server's own `POST /apply-template`, which shares `oaicompat_chat_params_parse` with `/v1/chat/completions` |
| `run-kaggle-vllm-streaming-latency.py` | the live vLLM server's `POST /tokenize` on `messages` | the server renders the same chat template with the same `--default-chat-template-kwargs`, so template overhead is inside the count rather than assumed away |

No path estimates with character counts, byte counts, or a different tokenizer.
If the exact counter cannot be obtained, the runner exits `context_unqualified`
before generating anything.

## Effective context limit

The limit is the **minimum** of every applicable limit, each with provenance,
not the most optimistic number:

- vLLM: the `--max-model-len` override, plus `tokenizer.model_max_length` and
  `config.max_position_embeddings` when the pinned `config.json` yields a
  plausible finite value, plus a `rope_scaling` limit when rope scaling is
  enabled.
- llama.cpp: `--ctx-size` when the caller knows it, `n_ctx` from `GET /props`,
  and `n_ctx / total_slots` when `--parallel` splits the context, since a single
  request can only use its own slot.

HF's "unknown" sentinel (`model_max_length = 1000000000000000000`) is not treated
as an advertised limit. An empty candidate set fails closed rather than
assuming a default.

## Thinking / template capability is reported, not assumed

A requested flag is never treated as proof. The receipt carries one of:

| state | meaning |
| --- | --- |
| `applied` | the call was accepted and the counted prompt is the rendered output of that call |
| `verified_default` | something other than a request proved the behavior |
| `not_applicable` | plain mode; no template and no thinking flag |
| `unsupported` | the template/path has no thinking concept at all |
| `unverified` | the kwarg was requested but nothing proved it took effect |

The vLLM runner reaches `applied` only when `apply_chat_template` accepted
`enable_thinking=false`; when the template rejects that kwarg the state is
`unverified`, because no verified default is claimed. Reasoning markers that
still appear in raw output remain a benchmark observation and are already
classified downstream (`unclosed_thinking_block`).

## No silent truncation

- Preflight overflow raises before generation. The runner exits with the
  violating task ids instead of running a request it knows will not fit.
- llama.cpp rows compare the server's `tokens_evaluated` against the preflight
  count and check the server's `truncated` flag; either disagreement fails the
  run.
- vLLM rows compare the runtime's prompt token count against preflight; a
  mismatch fails the run.
- `maxNewTokens` is taken from the frozen task when it declares one, so a
  product task is not silently given a smaller global default and then reported
  as producing few candidates.
- A generation that ends at the cap is recorded as `output_budget_truncation`,
  which is a different observation from a model voluntarily returning too few
  candidates.

## Checks

`test_kaggle_context_budget.py` covers the nine cases from the issue: exact
boundary fits, one-token overflow rejects, chat-template overhead overflows
though the raw text fits, different tokenizers give different counts for the
same text, a runtime override below the advertised max wins, `max_new_tokens`
pushes a valid prompt over budget, output-cap exhaustion is classified as
truncation, silent left truncation is detected, and Unicode is counted by the
tokenizer rather than bytes or characters. It also pins the thinking-state
vocabulary and the receipt hash behavior.

Run it with the benchmark self-check (`self-check-kaggle-runtime.sh`) or
directly:

```bash
python3 test_kaggle_context_budget.py
```

The test module is CPU-only: no torch, no transformers, no network, no GPU.

### Effective prompt mode (#58)

`test_kaggle_thinking_capability.py` is the separate evidence gate for the
`thinkingCapability` block itself, across all three runtime producers
(`run-english-core-vllm.py`, `run-english-core-llamacpp.py`,
`run-kaggle-vllm-streaming-latency.py`). It covers:

- the real vLLM `prompt_for_task` against a template that accepts
  `enable_thinking=False` (`applied`) and one that rejects the kwarg
  (`unverified`, never `applied`);
- plain mode reporting `not_applicable` with no requested flag;
- the real streaming-latency `probe_context_budget` driven against a fake server
  counter, asserting the receipt and every task row agree;
- the llama.cpp and streaming paths importing the same shared
  `ThinkingCapability`, so the reported state cannot be a local variant;
- every emitted `contextBudget` block passing the real
  `validate-english-core-run.py` schema, including a negative case proving a
  top-level `thinkingCapability` is rejected by the strict result schema;
- a static guard refusing any `applied` claim whose proof names no verification
  mechanism (`apply_chat_template`, `/apply-template`, `/tokenize`, and so on).

```bash
python3 test_kaggle_thinking_capability.py
```

What CPU tests cannot prove is a real runtime's answer to a real template:
whether a specific pinned model's chat template on Kaggle actually honours
`enable_thinking=false`, or whether a specific llama.cpp / vLLM server build
strips the thinking block. The CPU gate proves the *reporting* is honest and
cannot be laundered from request intent. The per-model proof is the recorded
`thinkingCapability` in a real candidate result.

## What this does not claim

- It does not assert that any pinned runtime accepts a given thinking flag. It
  records what was provable on the machine that ran the check and otherwise
  reports `unverified`.
- It does not decide benchmark quality. A context-incompatible configuration is
  reported as `context_unqualified`, never as a zero for the candidate.
- It does not bind itself into candidate-matrix or roster provenance. That
  binding is the separate #33/#59 integration step.

## Integration note

`kaggle-runbook-contract.json` keeps a `mandatoryContracts` registry, and
`test_kaggle_runbook_consistency.py` requires every landed contract module to
appear there. The context-budget contract has not been added to that registry;
the owner of that file should register it with gate `kaggle-runtime` and command
`python3 test_kaggle_context_budget.py` so the runbook check stays complete.
