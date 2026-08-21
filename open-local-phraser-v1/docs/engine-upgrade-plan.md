# Pari Engine Upgrade Plan — v3 "SOTA push"

Synthesis of: adversarial baseline measurement (13%), LLM landscape research
(Aug 2026), architecture brainstorm, and quality-systems design. Sources:
- `benchmarks/eval/` — 64-case corpus + reference-free metrics
- `~/.hermes/research/small-llm-paraphrasing-aug2026.md` — model shootout receipts
- subagent design docs (quality systems: ~/pari-quality-system.md)

## Where we are

| engine | overall | broken | frag | vague | run-on | salad | tense | register | canary |
|---|---|---|---|---|---|---|---|---|---|
| local-safe-engine (baseline) | 13% | 0% | 13% | 0% | 0% | 0% | 0% | 0% | 88% |

The safe engine is an excellent *guardrail* and a poor *paraphraser*: it
changes ~5% of words and leaves degenerate input untouched. The native MLX
path (Qwen3-4B) fixes mechanics but keeps vagueness, fragments, and informal
register (see benchmarks/llm-shootout/qwen3-4b-probe-results.json).

## Decisions (evidence-backed)

1. **Model**: upgrade bundled generator Qwen3-4B → **Qwen3.5-4B MLX 4bit**
   (same ~2GB footprint; IFEval 89.8 vs 83.4; Apache-2.0; thinking off by
   default). Runner-up Gemma 4 E2B-it stays on the bench for prose-style A/B.
   Receipts in the research report above.
2. **Pipeline shape**: keep generate→verify→repair, but add a **pre-repair
   stage** (degenerate-input normalization feeding the LLM a cleaner prompt)
   and **N+1 candidate generation** (two sampled candidates + one greedy,
   ranked by existing semantic ranker + harper error count).
3. **Meaning gate**: add NLI entailment check (DeBERTA-v3-xsmall ONNX,
   ~90MB q8) as a second gate beside MiniLM cosine floor. Kills negation
   flips that cosine cannot see.
4. **Prompting**: task-specific prompt tracks per detected input category
   (broken words / vague / fragment / run-on / register), chosen by cheap
   heuristics — the probe showed generic prompts under-fix vagueness.
5. **Style tuning (later)**: few-shot exemplar bank from approval memory
   (already partially built via buildNativeStyleContext); LoRA only after
   bank >200 approvals.

## Execution order (each its own PR, each must move the eval number)

- PR#2 llm-shootout: score Qwen3.5-4B vs Qwen3-4B vs safe-engine on the
  identical corpus; wire winner as default native model. Gate: overall ≥ 60%
  with zero guard violations.
- PR#3 pre-repair stage: deterministic normalization (spacing, apostrophes,
  common typo map via existing lexicon) before the LLM sees text. Gate:
  broken_words ≥ 75%.
- PR#4 category-aware prompts + N-candidate ranking. Gate: vague ≥ 50%,
  register_shift ≥ 50%, no canary regressions.
- PR#5 NLI entailment gate in app pipeline (not just eval). Gate: canary 100%,
  zero negation flips across corpus.
- PR#6 CI wiring: run-eval.mjs --outputs as GitHub Action on every PR to
  main, failing below committed floors.

## Non-negotiables (from AGENTS.md + roadmap)

- local-safe fallback stays bounded and deterministic; never remote.
- Protected spans, sentence-count stability, anchor preservation remain hard gates.
- "Changed more" is not a quality metric; the eval composite is.
