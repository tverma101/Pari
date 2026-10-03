# Runtime-neutral decoding and prompt-adaptation semantics

One versioned registry, `english_core_runtime_semantics.py`, decides what a
recorded decoding or prompt-adaptation value *means*. It is consumed by
`validate-english-core-run.py`, by the #60 schema self-check's promotion path,
and by the cross-runtime parity tests in
`test_english_core_runtime_semantics.py`. Registry version: **1**.

The rule the registry exists to enforce: **comparison happens on logical
behaviour, never on raw integers or backend-specific strings, and the raw value
is never rewritten.** A runner does not have to report a value it did not
actually send in order to satisfy a shared schema.

## Top-k disabled sentinels

| Runtime | `model.runtime` | Disabled sentinel(s) | Active floor | Why the raws differ |
| --- | --- | --- | --- | --- |
| vLLM | `vllm` | `0`, `-1` | 1 | `top_k` defaults to 0; only `top_k < -1` raises; `-1` is accepted as disabled with an in-source note preferring 0 |
| llama.cpp | `llama.cpp-server` | `0` | 1 | `--top-k` is documented "default: 40, 0 = disabled" |
| MLX | `mlx-lm` | `0` | 1 | `make_sampler` applies top-k only under `top_k > 0` |

So a canonical vLLM `topK: -1` and a canonical llama.cpp `topK: 0` are the same
logical request — top-k disabled — while their raw values stay `-1` and `0`
respectively. `topK: 40` is an *active* top-k on both runtimes and stays
distinct from disabled; on llama.cpp, 40 is in fact the server's own default.

Anything else fails closed:

- `topK: -2` on vLLM (upstream raises for anything below -1).
- `topK: -1` on llama.cpp or MLX. Their registered sentinel is `0` only; -1 is
  not silently borrowed from vLLM.
- A non-integer, boolean, or null top-k.
- A negative top-k on a runtime absent from the registry, because the disabled
  meaning cannot be established. A well-formed top-k on an unregistered
  runtime is reported as unpinned rather than rejected.

## Schema interaction (#60)

`english-core-result-schema.json` closes `decoding.topK` at `minimum: 0`, which
is the rule #63 corrects: that bound rejects vLLM's own frozen default. The
schema is owned by the #60 work, so the validator does not edit it. Instead
`schema_validation_errors()` defers exactly one diagnostic shape
(`$.decoding.topK: number below minimum`) and hands the decision to the
registry. Every other schema violation is unchanged. When the registry accepts
the value as a registered sentinel, the deferred diagnostic is dropped; when it
rejects the value, the registry's own fail-closed error stands and the schema
diagnostic is restored alongside it. The override it applied is recorded in the
report at `runtimeSemantics.schemaOverrides`.

## Prompt adaptation

Logical classes are `plain` and `chat_template`. Registered concrete adapters:

| Adapter string | Logical class | Runtime |
| --- | --- | --- |
| `transformers_apply_chat_template` | `chat_template` | `vllm`, `mlx-lm` |
| `llama.cpp_embedded_chat_template` | `chat_template` | `llama.cpp-server` |
| `llama_cpp_embedded_chat_template` | `chat_template` | `llama.cpp-server` |
| `chat_template` | `chat_template` | `vllm`, `mlx-lm` |
| `plain` | `plain` | all three |
| `plain_fallback` | `plain` | `vllm` |

`chat_template` is registered as a concrete adapter because the vLLM and MLX
runners record that bare string for the `tokenizer.apply_chat_template` path,
so the concrete identity stays recoverable from the raw value. The dotted and
underscore llama.cpp spellings are both registered because the runner writes
the dotted form (`run-english-core-llamacpp.py:632`) and #63 names the
underscore form; each keeps its own registry identity rather than being a
silent alias.

Promotion now accepts *any registered implementation* of the requested logical
class, so Prism's embedded chat-template path satisfies the same contract vLLM
satisfies with `tokenizer.apply_chat_template`. Both masquerade directions fail
closed:

- a `chat` run satisfied by `plain` (plain cannot pose as chat-template);
- a `plain` run satisfied by a `chat_template` adapter;
- a per-row `promptAdaptation` whose logical class disagrees with the run-level
  observed set;
- any unregistered adapter string, at run level or per row.

Unknown adaptation values are hard errors in both exploratory and promotion
mode. An unknown string is a contract violation, not a warning.

## Requested vs effective

The canonical runners all default to `temperature: 0.0`, i.e. greedy. vLLM
collapses `top_p` to 1.0 and `top_k` to 0 under greedy, so a recorded vLLM
top-k is inert in that configuration. The registry reports the **requested**
reading (`topK=40` stays distinct from disabled, per #63) and annotates it with
the **effective** greedy value, so an inert value is never mistaken for proof
that a filter ran.

## What the current result schema cannot express

These are reported as `unrecorded` with the runner field that would be
required. They are not normalized from values the outputs do not prove:

- `stopSequences` — needs `decoding.stop` / `decoding.stopTokenIds` plus the
  ignore-EOS flag.
- `eosTokenId` — needs `decoding.eosTokenId` for per-runtime EOS identity.
- `speculativeDecoding` on llama.cpp and MLX — only vLLM records
  `decoding.speculativeConfig`. A vLLM run with `speculativeConfig: null` and a
  llama.cpp run with no such field both normalize to logical *disabled*; a
  populated config is *enabled*; a vLLM run that omits the field is
  *unrecorded*, because the capability exists and the result does not state
  whether it was used.

## Report shape

Every validator run emits `runtimeSemantics` containing the registry version,
the resolved runtime, the full normalized `decoding` view (each entry keeping
its exact `raw` value next to its logical `mode`), the prompt-adaptation
resolutions with raw strings preserved, the `schemaOverrides` actually applied,
and the registry summary itself — so a report records the registry identity it
was judged against rather than a bare version integer.

## Checks

```bash
python3 test_english_core_runtime_semantics.py
bash self-check-english-core.sh
```

The parity fixtures are **fabricated**. They reproduce only the field shapes the
in-tree runners write and involve no model, GPU, Kaggle session, or real result
file. The end-to-end cases run the real validator CLI over those fabricated
results.
