# Pari Engine Upgrade Plan — historical note

> **Superseded for execution tracking.** The canonical current plan is [`docs/remaining-work.md`](remaining-work.md).

This file records the August 2026 "SOTA push" that moved Pari away from treating the deterministic safe engine as a sufficient paraphraser. Its architectural conclusions remain useful, but its model-selection step is no longer current.

## What remains valid

- The deterministic `local-safe-engine` is a guardrail/fallback, not the quality ceiling.
- Generate -> verify -> repair remains the correct high-level shape.
- Protected spans, sentence relationships, negation/modality/quantity, grammar and semantic preservation remain hard constraints.
- Best-of-N candidate generation and replayable ranking are preferable to trusting one stochastic draft.
- Broken-input normalization/category-aware prompting are reasonable only when they improve the frozen Pari corpus.
- "Changed more" is not a quality metric.
- Fine-tuning should wait until enough clean, explicitly approved examples exist.

## Model-selection correction

The old plan treated **Qwen3.5-4B** as the next production upgrade. That decision is now intentionally reopened:

- **Qwen3-4B MLX 4-bit** remains the current production local backend.
- **Qwen3.5-4B** is the current general-model benchmark control.
- **MiniCPM5-2B** is a new must-test challenger because of its small footprint and strong September 2026 independent small-model results.
- MiniCPM testing is tracked in [issue #10](https://github.com/tverma101/Pari/issues/10).

No model should be promoted from generic benchmark scores alone. The winner must beat the controls on Pari's own coherence, grammar, reconstruction, meaning-preservation, safety, latency and target-Mac memory tests.

## Historical execution ideas still worth evaluating

These remain candidates, but their order is governed by `docs/remaining-work.md`:

1. pre-repair / deterministic normalization for malformed input;
2. category-aware prompts and multi-candidate ranking;
3. compact NLI/entailment veto for contradiction/negation failures that cosine can miss;
4. grammar-specialist + general-rewriter cascades;
5. CI quality floors;
6. approval-derived style tuning only after a sufficiently large clean approval bank.

For research rationale see [`research/quality-roadmap.md`](../research/quality-roadmap.md). For the current model harness and promotion rules see [`benchmarks/llm-shootout/README.md`](../benchmarks/llm-shootout/README.md).
