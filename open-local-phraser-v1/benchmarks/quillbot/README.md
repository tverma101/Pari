# QuillBot-killer benchmark (Issue #8)

## Goal

Prove Pari beats QuillBot on the product task:

> broken / vague / awkward English → clear, natural, maximally grammatical English, while preserving recoverable meaning and inventing nothing.

## Corpus

- `corpus.seed.json` — 120 seed cases across: broken grammar, vagueness, run-ons/clause-attachment, word salad, ambiguity traps (no invention), canaries/negation, register.
- This is a **seed**. Before any "beats QuillBot" claim, expand to a **frozen held-out set of 300–500+ cases** emphasizing the hard tail (typos/shorthand, fragments, run-ons, vague recoverable prose, clause attachment, modality/negation/quantity, sentences that should split/join, pronoun ambiguity, hedges).
- Keep the existing 64-case `benchmarks/eval/corpus.json` as the **fast smoke/regression** suite (now hardened per #7 — `ro-04` no longer passes and the old 61/64 must not be called "95% human quality").

## Scoring

Run every case through `benchmarks/eval/metrics.mjs:scoreCase` — it now returns separate dimensions:

- `meaningSafe` — `meaningFloor && anchorSafe && negationSafe && rolePreserved`
- `englishQuality` — `noNewErrors && clauseWellFormed && bandFit`
- `failedChecks` — `meaningFloor | anchorSafe | negationSafe | clauseWellFormed | rolePreserved | noNewErrors | bandFit`
- `missingAnchors`, `clauseWellFormedIssues`

Report by category and overall:

```
grammar hard-failure rate (clauseWellFormed / noNewErrors)
meaning-drift rate (meaningFloor / negationSafe / rolePreserved + anchor)
invention rate (trap cases where output invents specifics)
win/tie/loss vs each competitor on blind pairwise preference (optional human judge)
```

Invention: ambiguous inputs in `ambiguity_invention_trap` must not add facts (e.g. "soon" → "by Friday"). This is a human-judged dimension; the automatic judge enforces the other hard gates.

## Competitors

Capture outputs for each case from:

1. Pari local production path
2. QuillBot Fluency
3. QuillBot Standard
4. incumbent generator alone (Qwen3.5-4B)
5. leading replacement (Ling-3.0-tiny via `benchmarks/llm-shootout/run_openai_compatible.py`)
6. optional frontier editor (quality ceiling)

**Do not automate access to any service in violation of its ToS.** Manual/exports are acceptable for the frozen benchmark — store as `benchmarks/quillbot/captures/<engine>.jsonl` with `{id, output}` lines.

## Running the comparison

```bash
# 1. Collect Pari outputs for the QuillBot corpus (reuse shootout runner or eval directly)
node benchmarks/eval/run-eval.mjs --corpus benchmarks/quillbot/corpus.seed.json --outputs benchmarks/quillbot/captures/pari.jsonl
node benchmarks/eval/run-eval.mjs --corpus benchmarks/quillbot/corpus.seed.json --outputs benchmarks/quillbot/captures/quillbot-fluency.jsonl
node benchmarks/eval/run-eval.mjs --corpus benchmarks/quillbot/corpus.seed.json --outputs benchmarks/quillbot/captures/quillbot-standard.jsonl

# 2. Pairwise report (after captures exist)
node benchmarks/quillbot/report.mjs
```

`--corpus` flag is not yet wired in `run-eval.mjs` — temporary workaround: copy `corpus.seed.json` over `benchmarks/eval/corpus.json` in a temp checkout, or adapt `run-eval.mjs` to accept `--corpus`. The canonical comparison will be scripted in `report.mjs`.

## Acceptance (from #8)

Do not claim "beats QuillBot" until Pari has a **statistically convincing win rate on the frozen held-out set** and does **not** trade that win for higher meaning/invention failures. Keep canaries at 100%.

## Sources

- Ling-3.0-tiny: https://huggingface.co/inclusionAI/Ling-3.0-tiny — 7.9B total / 1.3B active, ~86–90 tok/s on M4 Pro (FP8), Mitchell licensed.
- Ling MLX 4-bit via rapid-mlx: https://huggingface.co/rapid-mlx/Ling-3.0-tiny-MLX-4bit (~4.2GB, `bailing_hybrid` uses `rapid-mlx` until `mlx-lm` upstream lands).
