# Pari English Core — robustness and statistical protocol

This document defines the robustness checks required before English Core results are used to make increasingly strong model-selection claims. It complements `ENGLISH_CORE_RESEARCH_BASIS.md` and `RESEARCH_GROUNDING_POLICY.md`.

The central rule is simple:

> a one-prompt, one-sample, one-number result is not sufficient evidence for a close model-selection decision.

## 1. Multi-prompt robustness

Mizrahi et al. (TACL 2024) evaluate 20 LLMs over 39 tasks and 6.5M instances using paraphrased instructions and show that instruction templates can materially change both absolute performance and relative model rankings.

Reference: https://aclanthology.org/2024.tacl-1.52/

Related prompt-sensitivity evidence:

- ProSA, Findings EMNLP 2024: https://aclanthology.org/2024.findings-emnlp.108/
- POSIX, Findings EMNLP 2024: https://aclanthology.org/2024.findings-emnlp.852/
- Benchmarking Knowledge Boundary, ACL 2024: https://aclanthology.org/2024.acl-long.124/

English Core implementation:

- `build-english-core-prompt-robustness.mjs` creates three intent-preserving instruction variants per shadow case;
- item content, candidate options, and deterministic option order remain fixed within a case;
- only the task wording changes;
- `score-english-core-prompt-robustness.mjs` reports mean prompt accuracy, worst-prompt accuracy, best/worst spread, all-prompts-correct rate, majority-prompt accuracy, and answer consistency;
- the best prompt must **not** be selected after observing model results.

A model with high canonical accuracy but poor worst-prompt performance or low answer consistency is marked prompt-sensitive.

## 2. Benchmark perturbation sensitivity

Alzahrani et al. (ACL 2024) show that seemingly minor benchmark choices, including answer ordering and answer-selection method, can move popular LLM leaderboard rankings by as many as eight positions in their experiments.

Reference: https://aclanthology.org/2024.acl-long.744/

English Core therefore:

- deterministically permutes forced-choice option positions;
- balances binary labels in the public-fast screening subsets where sampling permits;
- accepts harmless output forms such as `A` and `Answer: A` rather than conflating English competence with one formatting convention;
- keeps prompted-screen results distinct from benchmark-native/official protocols.

## 3. Statistical uncertainty

Small score differences are not treated as exact facts.

BooStSa describes bootstrap significance testing for NLP model evaluation and emphasizes that slightly higher observed scores alone are insufficient evidence that an advantage will generalize.

Reference: https://aclanthology.org/2022.acl-demo.12/

English Core implementation:

- `analyze-english-core-statistics.mjs` performs deterministic stratified item bootstrap resampling;
- it reports 95% intervals for each English dimension and for both product-weighted and equal-weight composites;
- intervals are labeled as **conditional on the current shadow item set**.

Important limitation:

These intervals quantify item-resampling uncertainty under the current benchmark construction. They do **not** imply that Pari's handcrafted items are an i.i.d. random sample from a universal population of English usage.

## 4. Paired model comparison

Peyrard et al. (ACL 2021) show that NLP systems evaluated on the same instances should be compared using the pairing rather than only independent averages; they found that aggregation choices could change state-of-the-art conclusions in a substantial fraction of the evaluation setups they reanalyzed.

Reference: https://aclanthology.org/2021.acl-long.179/

Additional evidence:

- Confidence and Stability of Global and Pairwise Scores in NLP Evaluation, ACL SRW 2025: https://aclanthology.org/2025.acl-srw.3/

English Core implementation:

- `compare-english-core-models.mjs` aligns the exact same scored items for Model A and Model B;
- reports wins/ties/losses;
- computes paired bootstrap intervals for each dimension;
- performs stratified paired bootstrap comparison for product-weighted and equal-weight composites;
- if the interval contains zero, the result is reported as **inconclusive**, not a forced winner.

Do not infer pairwise significance merely because two separately calculated confidence intervals do or do not overlap.

## 5. Distributional validity

Siska et al. (ACL 2024) challenge the assumption that benchmark test prompts are a random sample from a single real-world distribution and show that correlations and distribution assumptions can change model rankings.

Reference: https://aclanthology.org/2024.acl-long.560/

Kovatchev and Lease (NAACL 2024) likewise show that dataset characteristics and sampling distributions can significantly affect absolute performance and relative rankings.

Reference: https://aclanthology.org/2024.naacl-long.86/

English Core therefore does not claim its shadow mix estimates a universal English distribution.

Target interpretation:

- public anchors estimate performance on their published task distributions;
- the shadow suite probes transfer to fresh Pari-relevant linguistic phenomena;
- Pari product weights encode the application distribution we care about;
- per-dimension and, where possible, per-phenomenon results remain visible.

A universal-English claim requires broader independent evidence than the Pari shadow distribution.

## 6. Contamination

PaCoST and other contamination research show that public benchmark exposure can distort apparent model performance.

Reference: https://aclanthology.org/2024.findings-emnlp.97/

English Core response:

- public anchors and fresh shadow results are always separate;
- shadow cases are never training/prompt-optimization data;
- repeated optimization against one frozen shadow file eventually contaminates it too, so cases must rotate;
- unexpectedly large public-anchor versus shadow gaps are investigated rather than averaged away.

## 7. Metric-model uncertainty

Hu, Goyal, and Gupta (EMNLP 2023) show that when a learned metric model is used for evaluation, ignoring metric-model error can change significance conclusions.

Reference: https://aclanthology.org/2023.emnlp-main.464/

Consequences for English Core:

- gold/human-reference/deterministic scores are preferred;
- scores from learned judges must preserve judge identity, version, validation evidence, and raw sub-scores;
- a judge-based metric is not treated as noise-free ground truth;
- general LLM judges remain secondary unless specifically validated against humans for the exact criterion.

## 8. Claim tiers

These tiers are Pari governance categories, not literature-derived universal thresholds.

### Tier 0 — smoke test

Evidence:

- one local run or partial shadow/public-fast screen.

Allowed claim:

- `Model A appears promising on this screen.`

Not allowed:

- `Model A has better English.`

### Tier 1 — internal candidate selection

Minimum evidence:

- complete English Core shadow profile;
- public-fast anchors;
- multi-prompt forced-choice robustness;
- uncertainty reporting;
- paired comparison for close contenders;
- weight sensitivity shown.

Allowed claim:

- `Model A is the stronger English Core candidate under Pari's current evaluation protocol.`

### Tier 2 — promotion-quality evidence

Add:

- primary official lexical anchors such as SWORDS;
- official JFLEG/EditEval or other relevant native protocols;
- full public-anchor runs where practical;
- quantization delta and product V1 route testing;
- reproducibility manifest.

Allowed claim:

- `Model A has stronger evidence for Pari's English workload across these specified benchmarks and fresh tests.`

### Tier 3 — strong research claim

Add:

- independently annotated/adjudicated shadow cases;
- adequate human agreement;
- protocol sensitivity analysis;
- independent replication where practical;
- statistically supported paired differences;
- no material ranking flip under reasonable weighting schemes.

Even here, prefer scoped claims over `objectively best English model`.

## 9. Reproducibility

Every promotion-quality result should record:

- model repository/name and exact revision;
- model artifact hash where available;
- quantization;
- runtime and version/commit;
- chat template/adaptation mode;
- hardware and OS;
- benchmark source/config/split/revision;
- prompt-suite version/hash;
- decoding parameters and seed;
- scorer version/commit;
- metric/judge provenance;
- raw-output location/hash.

Without enough metadata to reproduce a result, treat it as exploratory evidence rather than a promotion result.
