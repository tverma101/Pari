# QuillBot-killer benchmark (Issue #8) — frozen 320

## Goal

Prove Pari beats QuillBot on the product task:

> broken / vague / awkward English → clear, natural, maximally grammatical English, while preserving recoverable meaning and inventing nothing.

## Corpus

- `corpus.seed.json` / `corpus.frozen.json` — **320 cases** (frozen, version 2) across: broken_grammar 105, vague 52, run_on 51, ambiguity_invention_trap 40, canary 38, word_salad 34. All inputs ≤600 chars so the QuillBot free-tier (~600 chars / ~125 words) chunker is a convenience, not a requirement per case.
- Seed history: 100 seed → +106 expansion (206) → +114 expansion (320). Corpus is now at the 300+ frozen threshold required before any "beats QuillBot" claim; further expansion still toward 500+ is welcome but not blocking.
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

Manual/exports are acceptable for the frozen benchmark — store as `benchmarks/quillbot/captures/<engine>.jsonl` with `{id, output}` lines.

## QuillBot free-tier chunking

QuillBot free tier caps at ~600 chars / ~125 words. All 320 frozen inputs fit per-case, but if you paste longer drafts use:

```bash
node scripts/quillbot-chunker.mjs --corpus benchmarks/quillbot/corpus.frozen.json --out /tmp/quillbot-chunks.jsonl
# paste each chunk into QuillBot Fluency/Standard, collect {id, chunkIndex, output} as JSONL, then:
node scripts/quillbot-chunker.mjs --assemble /tmp/quillbot-chunks.jsonl --responses /tmp/my-pastes.jsonl --out benchmarks/quillbot/captures/quillbot-fluency.jsonl
```

manual paste + stitch is the supported path.

## Running the comparison

```bash
# 1. Collect outputs for the frozen corpus (Pari local-safe-engine runs without --outputs; shootout runners take --corpus)
node benchmarks/eval/run-eval.mjs --corpus benchmarks/quillbot/corpus.frozen.json
# or score existing captures:
node benchmarks/eval/run-eval.mjs --corpus benchmarks/quillbot/corpus.frozen.json --outputs benchmarks/quillbot/captures/pari.jsonl
node benchmarks/eval/run-eval.mjs --corpus benchmarks/quillbot/corpus.seed.json --outputs benchmarks/quillbot/captures/quillbot-fluency.jsonl
node benchmarks/eval/run-eval.mjs --corpus benchmarks/quillbot/corpus.seed.json --outputs benchmarks/quillbot/captures/quillbot-standard.jsonl

# 2. Pairwise report (after captures exist)
node benchmarks/quillbot/report.mjs
```

`--corpus` is wired in `benchmarks/eval/run-eval.mjs` and both shootout runners (`run_model.py`, `run_openai_compatible.py`); use `benchmarks/quillbot/corpus.frozen.json` directly. Report is `benchmarks/quillbot/report.mjs`.

## Acceptance (from #8)

Do not claim "beats QuillBot" until Pari has a **statistically convincing win rate on the frozen held-out set** and does **not** trade that win for higher meaning/invention failures. Keep canaries at 100%.

## Sources

- Ling-3.0-tiny: https://huggingface.co/inclusionAI/Ling-3.0-tiny — 7.9B total / 1.3B active, ~86–90 tok/s on M4 Pro (FP8), Mitchell licensed.
- Ling MLX 4-bit via rapid-mlx: https://huggingface.co/rapid-mlx/Ling-3.0-tiny-MLX-4bit (~4.2GB, `bailing_hybrid` uses `rapid-mlx` until `mlx-lm` upstream lands).
