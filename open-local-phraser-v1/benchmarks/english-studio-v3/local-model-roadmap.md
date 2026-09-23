# English Studio local-model roadmap

This note is deliberately downstream of the English Studio benchmark. It describes how a high-quality research system can eventually become a fast local product without forcing the research phase to use only tiny models.

## Principle

Do not confuse today's research ceiling with tomorrow's shipping footprint.

Pari may temporarily use a larger GPU-hosted teacher if that teacher produces meaningfully better English candidates. The shipping goal remains a fast local system on a 16-GB Apple-Silicon Mac.

The intended path is:

```text
best practical teacher quality
  -> collect diverse candidate sets
  -> human chooses / edits / approves
  -> learn preference patterns
  -> distill / fine-tune smaller generator and/or ranker
  -> aggressive quantization
  -> speculative/MTP acceleration when supported
  -> re-run the complete benchmark
  -> local shipment only if quality survives
```

## Low-bit research track

Treat modern binary/ternary systems such as PrismML Bonsai as evidence that very low-bit deployment is a serious research direction, not as an automatic dependency.

Current public examples include:

- PrismML Bonsai 27B: 1-bit / 1.58-bit variants based on Qwen3.6 27B;
- PrismML Bonsai 2 27B: ternary model based on Qwen3.8 27B, announced at a 5.9-GB model footprint.

References:

- https://prismml.com/news/prismml-releases-bonsai-27b
- https://prismml.com/news/prismml-launches-bonsai-2-27b

Pari should not assume those exact models or runtimes are the final solution. Instead benchmark the general question:

> How far can the best English Studio generator/ranker be compressed before user-visible meaning, grammar, naturalness, candidate diversity, or personalization quality materially degrades?

### Compression ladder

Where runtime support exists, measure:

1. teacher/reference precision;
2. 8-bit;
3. 6-bit / medium-bit;
4. 4-bit;
5. 3-bit;
6. ternary / ~1.5-bit;
7. binary / ~1-bit experimental path.

A lower-bit build is only better when the whole quality/latency/RAM tradeoff is better.

## MTP / speculative decoding track

Multi-token prediction is primarily a speed optimization. It should be evaluated independently from quantization.

Modern runtimes now support MTP-style speculative decoding for models that retain compatible prediction heads. The target model verifies proposed tokens, so a correct speculative implementation is intended to preserve the target distribution while reducing decode work.

Useful references:

- vLLM Speculators MTP docs: https://docs.vllm.ai/projects/speculators/en/stable/user_guide/algorithms/mtp/
- llama.cpp / local MTP work should be tracked against the currently supported model formats rather than assumed from model-family marketing.

For every MTP-capable contender record:

- baseline tok/s and candidate latency;
- MTP tok/s and candidate latency;
- accepted tokens per verification step;
- extra memory;
- prefill impact;
- whether the converted/quantized checkpoint retained the required MTP tensors;
- exact-output or distribution-equivalence validation where the runtime makes that test possible.

Do not select an MTP model merely because it generates quickly. English Studio quality remains the primary criterion.

## Personal preference tuning

The most important long-term specialization signal is the user's own approved editing behavior.

Store structured training events such as:

```text
source paragraph
initial generated draft
selected span
candidate set shown
candidate chosen
candidate(s) rejected/reverted
manual edit after selection
final approved paragraph
rewrite strength
operation type
surrounding sentence/paragraph context
```

### What the system should learn

- words frequently kept unchanged;
- words frequently replaced;
- preferred replacement phrases;
- preferred expansion/compression patterns;
- contraction preference;
- sentence length and clause structure;
- typical level of formality;
- preferred transition words;
- disliked generic model phrases;
- preference for one-word vs multi-word replacements;
- ranking tendencies conditioned on context.

### Learning stages

Do not jump immediately to full-model fine-tuning.

1. **Preference-memory reranking** — cheapest and easiest to inspect.
2. **Learned candidate ranker** — train on chosen vs rejected alternatives.
3. **Small adapter / LoRA** — only after enough approved examples exist.
4. **Distilled personalized student** — use a larger teacher plus human-approved data.
5. **Quantized personalized model** — compress only after quality is stable.

A ranker may deliver most of the personalization benefit before the generator itself needs training.

## Compute plan

### Kaggle

Available research budget: roughly 30 hours/week on 2x T4.

Good uses:

- larger teacher model generation;
- Best-of-N candidate sweeps;
- quantization comparisons that fit T4 memory;
- preference-pair generation for later human approval;
- distillation experiments;
- difficult-case mining.

### Modal

Available monthly credits can cover bursty jobs that are inconvenient on Kaggle:

- alternate GPU architectures;
- conversion/quantization jobs;
- LoRA training;
- batch evaluation;
- short high-memory experiments.

### Colab

Use available compute as overflow/emergency capacity, especially when Kaggle runtime/session policy or GPU availability blocks an experiment.

Provider compute is research infrastructure, not a shipping dependency.

## Local end state

The local app should behave like a studio, not a chat model:

- fast first draft;
- nearly immediate word/phrase options;
- sentence alternatives fast enough to feel interactive;
- larger candidate pools may stream progressively;
- personalized ranking happens locally;
- no need to wake the largest model for trivial operations;
- RAM budget includes the entire app, judges, embeddings and caches, not merely model weights.

A realistic final architecture may therefore be heterogeneous:

```text
rules + lexical models
        +
small personalized ranker
        +
quantized general editor
        +
optional specialists
        +
local meaning / grammar gates
```

rather than one monolithic LLM.
