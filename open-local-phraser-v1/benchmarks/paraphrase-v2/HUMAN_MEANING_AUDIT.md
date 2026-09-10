# Human meaning-preservation audit

Pari's v2 benchmark already separates fluent writing quality from meaning and factual safety. This companion audit makes the meaning check more granular by asking a human reviewer to judge every case's existing `mustPreserve` items individually.

## Why this exists

A rewrite can sound natural and still omit one fact, qualification, actor relationship, or causal link. A single 1–5 adequacy score can hide that failure.

This audit follows two useful findings from text-rewriting research:

- Agrawal and Carpuat (TACL 2024) evaluate meaning preservation with reading-comprehension questions and show that apparently strong text-simplification systems can still make source information unrecoverable. This motivates checking recoverable information directly rather than relying on surface similarity alone.
- Context-aware lexical-substitution and simplification work repeatedly treats contextual appropriateness and preservation of sentence meaning as separate requirements. Pari should therefore prefer a conservative contextually valid substitute over a larger lexical change that weakens meaning.

Grounding:

- Agrawal, S. and Carpuat, M. (2024), *Do Text Simplification Systems Preserve Meaning? A Human Evaluation via Reading Comprehension*: https://aclanthology.org/2024.tacl-1.24/
- Kriz, R. et al. (2018), *Simplification Using Paraphrases and Context-Based Lexical Substitution*: https://aclanthology.org/N18-1019/
- Gooding, S. and Kochmar, E. (2019), *Recursive Context-Aware Lexical Simplification*: https://aclanthology.org/D19-1491/
- Qiang, J. et al. (2023), *ParaLS: Lexical Substitution via Pretrained Paraphraser*: https://aclanthology.org/2023.acl-long.206/

## Generate the blinded audit

Pass one or more completed v2 score bundles:

```bash
npm run benchmark:v2:meaning-audit -- \
  --scores benchmarks/paraphrase-v2/results/incumbent.scored.json \
  --scores benchmarks/paraphrase-v2/results/challenger.scored.json \
  --out-dir benchmarks/paraphrase-v2/results/meaning-audit-YYYYMMDD
```

The command writes:

- `meaning-audit-blinded.csv` — review sheet with source, anonymous candidate, and one row for each `mustPreserve` item;
- `meaning-audit-key.json` — engine identity mapping; keep this separate until ratings are complete.

For each row, fill:

- `preserved`: `Y`, `N`, or `UNCLEAR`;
- `contradicted`: `Y` or `N`;
- `notes`: optional short explanation.

Judge whether the information is recoverable from the candidate, not whether the candidate repeats the exact source words. A valid paraphrase may express the same item differently.

## Summarize completed ratings

```bash
npm run benchmark:v2:meaning-audit -- \
  --scores benchmarks/paraphrase-v2/results/incumbent.scored.json \
  --scores benchmarks/paraphrase-v2/results/challenger.scored.json \
  --ratings benchmarks/paraphrase-v2/results/meaning-audit-YYYYMMDD/meaning-audit-blinded.csv \
  --out-dir benchmarks/paraphrase-v2/results/meaning-audit-YYYYMMDD
```

This adds:

- `meaning-audit-summary.json`;
- `meaning-audit-summary.md`.

The summary reports three diagnostics per engine:

1. **preservation rate** — fraction of rated `mustPreserve` items explicitly retained;
2. **contradiction rate** — fraction of rated items contradicted by the rewrite;
3. **full-preservation case rate** — fraction of completely rated cases where every required item is retained and none is contradicted.

## Promotion use

Do not turn this into another single-number model contest. Use it alongside:

- the hard deterministic safety vetoes;
- the existing blinded pairwise preference sheet;
- grammar, fluency, lexical/collocation, and edit-discipline ratings;
- installed-runtime evidence on the target Mac.

A challenger that sounds better but repeatedly loses `mustPreserve` items should not replace the incumbent. Likewise, a perfectly conservative system that preserves everything but produces poor English should not win on this audit alone.
