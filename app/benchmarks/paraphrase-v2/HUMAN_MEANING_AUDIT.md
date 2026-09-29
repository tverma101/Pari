# Human meaning-preservation audit

Pari's v2 benchmark already separates fluent writing quality from meaning and factual safety. This companion audit makes the meaning check more granular by asking human reviewers to judge every case's existing `mustPreserve` items individually.

## Why this exists

A rewrite can sound natural and still omit one fact, qualification, actor relationship, or causal link. A single 1–5 adequacy score can hide that failure.

This audit follows several useful findings from text-rewriting research:

- Agrawal and Carpuat (TACL 2024) evaluate meaning preservation with reading-comprehension questions and show that apparently strong text-simplification systems can still make source information unrecoverable. This motivates checking recoverable information directly rather than relying on surface similarity alone.
- Context-aware lexical-substitution and simplification work repeatedly treats contextual appropriateness and preservation of sentence meaning as separate requirements. Pari should therefore prefer a conservative contextually valid substitute over a larger lexical change that weakens meaning.
- ReproHum studies in 2024–2025 show that semantic-preservation human evaluation can be reproducible at the system-ranking level while still showing meaningful annotator variability. Promotion-sensitive audits should therefore expose inter-rater agreement and adjudicate disagreements instead of treating one person's labels as unquestionable ground truth.
- PARAPHRASUS (COLING 2025) argues for a multi-dimensional view of paraphrase quality because trade-offs can disappear when paraphrase quality is reduced to one classification or aggregate number.

Grounding:

- Agrawal, S. and Carpuat, M. (2024), *Do Text Simplification Systems Preserve Meaning? A Human Evaluation via Reading Comprehension*: https://aclanthology.org/2024.tacl-1.24/
- Watson, L. N. and Gkatzia, D. (2024), *ReproHum #0712-01: Reproducing Human Evaluation of Meaning Preservation in Paraphrase Generation*: https://aclanthology.org/2024.humeval-1.19/
- Arvan, M. and Parde, N. (2025), *Investigating the Reproducibility of Semantic Preservation Human Evaluations*: https://aclanthology.org/2025.gem-1.54/
- Michail, A., Clematide, S., and Opitz, J. (2025), *PARAPHRASUS: A Comprehensive Benchmark for Evaluating Paraphrase Detection Models*: https://aclanthology.org/2025.coling-main.585/
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

## Use at least two raters for promotion-sensitive comparisons

Give each rater their own copy of the same blinded sheet. Do not reveal `meaning-audit-key.json` while they are rating.

After both copies are complete, measure agreement before adjudication:

```bash
npm run benchmark:v2:meaning-agreement -- \
  --ratings benchmarks/paraphrase-v2/results/meaning-audit-YYYYMMDD/rater-a.csv \
  --ratings benchmarks/paraphrase-v2/results/meaning-audit-YYYYMMDD/rater-b.csv \
  --key benchmarks/paraphrase-v2/results/meaning-audit-YYYYMMDD/meaning-audit-key.json \
  --out benchmarks/paraphrase-v2/results/meaning-audit-YYYYMMDD/agreement.json
```

The agreement command reports, for both `preserved` and `contradicted`:

- observed exact agreement;
- Cohen's kappa for each rater pair;
- macro agreement across pairs when more than two raters are supplied;
- a separate `*-disagreements.csv` containing the exact rows that need adjudication.

Do not convert kappa into an engine-quality score. It is a reliability diagnostic for the labels. Review disagreement rows explicitly; if the `mustPreserve` item itself is genuinely ambiguous, improve the benchmark item rather than forcing a confident label.

## Summarize completed ratings

After agreement review/adjudication, summarize the final completed sheet:

```bash
npm run benchmark:v2:meaning-audit -- \
  --scores benchmarks/paraphrase-v2/results/incumbent.scored.json \
  --scores benchmarks/paraphrase-v2/results/challenger.scored.json \
  --ratings benchmarks/paraphrase-v2/results/meaning-audit-YYYYMMDD/adjudicated.csv \
  --out-dir benchmarks/paraphrase-v2/results/meaning-audit-YYYYMMDD
```

This adds:

- `meaning-audit-summary.json`;
- `meaning-audit-summary.md`.

The summary reports three diagnostics per engine:

1. **preservation rate** — fraction of rated `mustPreserve` items explicitly retained;
2. **contradiction rate** — fraction of rated items contradicted by the rewrite;
3. **full-preservation case rate** — fraction of completely rated cases where every required item is retained and none is contradicted.

The summarizer also counts malformed, duplicate, or out-of-range rating rows as ignored rather than silently allowing them to inflate a system's totals.

## Promotion use

Do not turn this into another single-number model contest. Use it alongside:

- the hard deterministic safety vetoes;
- the existing blinded pairwise preference sheet;
- grammar, fluency, lexical/collocation, and edit-discipline ratings;
- the inter-rater reliability report and adjudicated disagreement set;
- installed-runtime evidence on the target Mac.

A challenger that sounds better but repeatedly loses `mustPreserve` items should not replace the incumbent. Likewise, a perfectly conservative system that preserves everything but produces poor English should not win on this audit alone.
