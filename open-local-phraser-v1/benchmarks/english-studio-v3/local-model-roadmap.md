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

## Why additional research compute is justified

The cloud/GPU budget is not being used because Pari is intended to remain a cloud application. It is being used to make the eventual local application better.

The expensive part of this project is **discovery, data generation, compression, and training**, not the final inference target.

### 1. We need to know the quality ceiling before choosing what to compress

If development starts by requiring every contender to fit inside the final Mac RAM budget, Pari can only compare small models against other small models. That does not answer the important question:

> How much English quality, candidate diversity, and preference-following are we giving up to fit locally?

A larger temporary teacher establishes a quality ceiling. Once that ceiling is measured, smaller and quantized models can be compared against it and the actual quality loss becomes visible.

This prevents premature optimization around a weak local baseline.

### 2. The benchmark multiplies inference work very quickly

English Studio v3 is intentionally much broader than a single paragraph-rewrite benchmark. The composite matrix is roughly 3k+ scored task instances before large-scale interactive expansion.

Even a modest research sweep such as:

```text
3,000 task instances
x 6 model/checkpoint contenders
x 3 generation seeds or candidate settings
= 54,000 generations
```

is already much larger than an ordinary local spot-check.

Interactive editing is even more generation-heavy because Pari wants deep candidate pools rather than one answer. For only 100 interactive benchmark selections:

```text
100 selected spans
x up to 40 displayed alternatives
= up to 4,000 candidate alternatives per model configuration
```

Raw generation may need substantially more than 40 candidates because duplicates, unsafe candidates, register mismatches, and grammatical failures are filtered before display.

This is a legitimate batch-GPU workload. It should not be forced through the shipping Mac one serial generation at a time.

### 3. Quantization itself requires a reference and repeated evaluation

Quantization is not a one-time file conversion followed by an assumption that quality survived.

For a promising model, Pari may need to compare:

- reference precision;
- INT8;
- ~6-bit;
- 4-bit;
- 3-bit;
- ternary / ~1.5-bit;
- experimental binary paths.

Each build must be rerun on the safety, naturalness, candidate-diversity, and personalization-sensitive subsets.

The extra compute therefore buys evidence about the **lowest safe bit-rate**, not just faster experimentation.

### 4. Personalization creates a training/data-generation workload

The final product is intended to learn from human choices:

- which wording is kept;
- which alternatives are chosen;
- which alternatives are ignored or reverted;
- which phrases are manually shortened, expanded, or restructured;
- final approved paragraphs.

That creates useful supervision for:

- preference rankers;
- pairwise preference models;
- LoRA/adapters;
- distillation;
- personalized students.

A larger teacher can cheaply generate broad candidate sets on external GPUs. The human then supplies the expensive signal by choosing/editing. Training can happen periodically off-device, while the resulting small ranker/adapter/student is what eventually ships locally.

### 5. Distillation needs a stronger teacher than the intended student

If a 1-4B local student is trained only from its own outputs, it mostly reinforces its existing limitations.

External compute allows Pari to test stronger temporary teachers and retain only human-approved or safety-filtered examples. The useful pipeline is:

```text
strong teacher / ensemble
  -> broad candidate pool
  -> safety filters
  -> human selection/edit
  -> approved preference dataset
  -> smaller student/ranker
  -> quantize
  -> local evaluation
```

The goal is not to ship the teacher. The goal is to transfer as much of the useful behavior as possible into a much cheaper local system.

### 6. Larger candidate pools are central to the product, not wasted sampling

Pari is deliberately becoming a studio where the human can inspect many legitimate ways to express the same idea.

That means quality cannot be measured only by top-1 generation. We need to test:

- top-10 precision;
- top-40 coverage;
- semantic diversity;
- duplicate rate;
- phrase expansion/compression variety;
- sentence restructuring variety;
- how often the human actually selects a candidate.

Generating and evaluating this breadth is compute intensive during development even if the final local application uses caching, routing, smaller specialists, and progressive generation to make it fast.

### 7. Extra compute helps discover which parts do not need an LLM

The research phase also exists to remove unnecessary compute from the final product.

Large-scale benchmarking can show that some tasks are already solved by:

- deterministic grammar rules;
- masked-language models;
- lexical substitution models;
- compact grammar specialists;
- a small preference ranker.

Every task successfully moved away from the general generator reduces final latency and RAM. Spending batch compute to measure routing decisions can therefore make the local application **smaller**, not larger.

### 8. The external-compute budget is bounded and should have stopping rules

Do not burn GPU hours merely because they are available.

Every substantial run should answer at least one concrete question, for example:

- Does model A materially beat model B on interactive English quality?
- Does Best-of-8 improve usable candidate diversity enough over Best-of-4?
- Does a 3-bit build preserve the 4-bit model's human preference rate?
- Does a personalized ranker recover most of the benefit of generator fine-tuning?
- Does LoRA materially improve held-out choice prediction?
- Does MTP reduce candidate latency without unacceptable memory/runtime complexity?

Reuse cached raw outputs whenever the experiment only changes ranking or evaluation. Do not regenerate model outputs for a ranker/scorer change when replay is possible.

Stop increasing model size, candidate count, training steps, or precision once the measured quality gain becomes negligible for the additional compute.

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

This is the primary batch discovery tier because candidate sweeps, teacher generation, quantization comparisons, and distillation can consume far more compute than final inference.

Good uses:

- larger teacher model generation;
- Best-of-N candidate sweeps;
- quantization comparisons that fit T4 memory;
- preference-pair generation for later human approval;
- distillation experiments;
- difficult-case mining;
- repeated benchmark runs across model/quantization variants.

### Modal

Available monthly credits can cover bursty jobs that are inconvenient on Kaggle:

- alternate GPU architectures;
- conversion/quantization jobs;
- LoRA training;
- batch evaluation;
- short high-memory experiments;
- experiments whose setup/runtime does not fit Kaggle well.

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
