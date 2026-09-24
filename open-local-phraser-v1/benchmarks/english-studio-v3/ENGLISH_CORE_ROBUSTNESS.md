# Pari English Core — robustness and statistical protocol

This document defines the robustness checks required before English Core results are used to make increasingly strong model-selection claims. It complements `ENGLISH_CORE_RESEARCH_BASIS.md` and `RESEARCH_GROUNDING_POLICY.md`.

The central rule is simple:

> a one-prompt, one-order, one-sample, one-number result is not sufficient evidence for a close model-selection decision.

## 1. Multi-prompt robustness

Mizrahi et al. (TACL 2024) evaluated 20 LLMs over 39 tasks and 6.5M instances using paraphrased instructions and found that instruction templates can materially change both absolute performance and relative model rankings.

Primary reference:

- https://aclanthology.org/2024.tacl-1.52/

Related prompt-sensitivity evidence:

- ProSA, Findings EMNLP 2024: https://aclanthology.org/2024.findings-emnlp.108/
- POSIX, Findings EMNLP 2024: https://aclanthology.org/2024.findings-emnlp.852/
- Benchmarking Knowledge Boundary, ACL 2024: https://aclanthology.org/2024.acl-long.124/

English Core implementation:

- `build-english-core-prompt-robustness.mjs` creates three intent-preserving instruction variants per shadow case;
- item content, candidate options, and deterministic option order remain fixed within a case;
- only task wording changes;
- `score-english-core-prompt-robustness.mjs` reports mean prompt accuracy, worst-prompt accuracy, best/worst spread, all-prompts-correct rate, majority-prompt accuracy, and answer consistency;
- the best prompt must **not** be selected after observing model results.

A model with high canonical accuracy but poor worst-prompt performance or low answer consistency is marked prompt-sensitive.

## 2. Answer-order and selection-bias robustness

Published 2024 work directly shows that option order and answer-selection details can change LLM decisions and even leaderboard rankings.

Primary references:

- Wei et al., *Unveiling Selection Biases: Exploring Order and Token Sensitivity in Large Language Models*: https://aclanthology.org/2024.findings-acl.333/
- Pezeshkpour & Hruschka, *Large Language Models Sensitivity to The Order of Options in Multiple-Choice Questions*: https://aclanthology.org/2024.findings-naacl.130/
- Alzahrani et al., *When Benchmarks are Targets: Revealing the Sensitivity of Large Language Model Leaderboards*: https://aclanthology.org/2024.acl-long.744/

English Core therefore uses two controls:

1. every normal forced-choice item is deterministically permuted instead of placing hand-authored gold answers in a fixed position;
2. close contenders also run `build-english-core-choice-order-robustness.mjs` and `score-english-core-choice-order-robustness.mjs`, which present each forced-choice shadow item in two different option orders.

Report at least:

- average presentation accuracy;
- `bothOrdersCorrectRate`;
- `semanticAnswerConsistencyRate` (underlying option identity, not displayed letter);
- `oneCorrectOneWrongRate`.

The order-robustness lane is a **diagnostic gate**, not another weighted English Core component. A material order effect weakens a single-order prompted result and must be reported rather than averaged away.

The shared parsers `english-core-choice-parser.mjs` and `english_core_choice_parser.py` accept only narrowly defined unambiguous answer wrappers such as `A`, `A.`, `Answer: A`, or `The answer is A`. They reject free-form/multi-answer outputs so format tolerance does not become answer inference.

## 3. Statistical uncertainty and dependence sensitivity

Small score differences are not treated as exact facts.

BooStSa provides bootstrap-based significance/evaluation tooling for NLP and motivates uncertainty analysis beyond slightly higher point estimates:

- https://aclanthology.org/2022.acl-demo.12/

English Core reports two different uncertainty views:

1. **item bootstrap** — resamples current shadow items within each dimension;
2. **phenomenon hierarchical-bootstrap sensitivity** — resamples phenomenon groups and then resamples items inside each selected group.

The second lane exists because shadow items sharing a linguistic phenomenon/template may be dependent. Relevant methodology includes:

- Burchill & Jaeger, *How reliable are standard reading time analyses? Hierarchical bootstrap reveals substantial power over-optimism and scale-dependent Type I error inflation*, Journal of Memory and Language 136 (2024): https://doi.org/10.1016/j.jml.2023.104494
- Anglin, *Estimating Uncertainty in Classifier Performance with Applications to Large Language Models and Nested Data* (2026 preprint): https://arxiv.org/abs/2606.26422

Important scope limitation:

- those papers motivate respecting hierarchical/nested dependence;
- they **do not validate Pari's phenomenon tags as a random-effects population**;
- grouping Pari items by `phenomenon` is therefore an application-specific sensitivity analysis, not a literature-derived inferential model;
- no universal minimum phenomenon count is asserted;
- neither interval implies that the handcrafted shadow set is an i.i.d. sample from a universal population of English usage.

Material disagreement between item-level and hierarchical intervals is evidence against a fine-grained winner claim.

## 4. Paired model comparison

Peyrard et al. (ACL 2021) show that NLP systems evaluated on the same instances should preserve that pairing rather than be compared only through independent averages.

Primary reference:

- https://aclanthology.org/2021.acl-long.179/

Additional evidence:

- Confidence and Stability of Global and Pairwise Scores in NLP Evaluation, ACL SRW 2025: https://aclanthology.org/2025.acl-srw.3/

English Core implementation:

- `compare-english-core-models.mjs` verifies matching benchmark input hashes and matching model-visible task-file hashes;
- it requires complete aligned scoring instead of silently comparing only the overlap between incomplete runs;
- reports wins/ties/losses and paired bootstrap intervals per dimension;
- performs paired bootstrap comparison for product-weighted and equal-weight composites;
- if the interval contains zero, the result is reported as **inconclusive**, not a forced winner.

Do not infer pairwise significance merely because two separately calculated confidence intervals do or do not overlap.

## 5. Distributional validity

Siska et al. (ACL 2024) show that benchmark prompts need not behave like independent random samples from one use-case distribution; accounting for prompt correlations can change model rankings.

- https://aclanthology.org/2024.acl-long.560/

Kovatchev & Lease (NAACL 2024) show that benchmark data characteristics/distributions can materially affect absolute scores and relative rankings.

- https://aclanthology.org/2024.naacl-long.86/

English Core therefore does not claim its shadow mix estimates a universal English distribution.

Target interpretation:

- public-native anchors estimate performance under their published/native task protocols;
- full-distribution prompted public runs estimate zero-shot instruction behavior on the public validation distribution;
- balanced public-fast runs are engineering screens only;
- the shadow suite probes transfer to fresh Pari-relevant linguistic phenomena;
- Pari product weights encode the application distribution we care about;
- per-dimension and per-phenomenon results remain visible.

A universal-English claim requires broader independent evidence than the Pari shadow distribution.

## 6. Native protocol versus prompted adaptation

A common prompted A/B task is useful for comparing chat/instruct models under one interface, but it must not silently replace a benchmark's native scoring protocol.

Examples:

- BLiMP grammar evidence includes its native sentence-likelihood/minimal-pair protocol; the chat-style BLiMP subset remains a prompted screen.
- CoLA headline reporting uses Matthews correlation coefficient on its native distribution where supported; balanced-screen accuracy is not called the official CoLA metric.
- SWORDS and JFLEG use their official evaluators rather than Pari redefinitions.

See `ENGLISH_CORE_NATIVE_PROTOCOLS.md` and `english-core-public-anchors.json`.

## 7. Contamination

PaCoST is direct evidence that public benchmark exposure can distort apparent model performance:

- Zhang et al., Findings EMNLP 2024: https://aclanthology.org/2024.findings-emnlp.97/

English Core response:

- public anchors and fresh shadow results are always separate;
- shadow cases are never training/prompt-optimization data;
- repeated optimization against one frozen shadow file eventually compromises its freshness too, so cases must rotate;
- unexpectedly large public-anchor versus shadow gaps are investigated rather than averaged away.

Freshness alone is not proof of validity: the current shadow set remains author-labeled until independent annotation/adjudication.

## 8. Metric-model uncertainty

Hu, Goyal, and Gupta (EMNLP 2023) show that when a learned metric model is used for evaluation, ignoring metric-model error can change significance conclusions.

- https://aclanthology.org/2023.emnlp-main.464/

Consequences for English Core:

- gold/human-reference/deterministic scores are preferred;
- scores from learned judges preserve judge identity, version, validation evidence, protocol, and raw sub-scores;
- a judge-based metric is not treated as noise-free ground truth;
- general LLM judges remain secondary unless specifically validated against humans for the exact criterion;
- generative metric directionality is declared in `english-core-generative-metric-contract.json` so failure rates such as `stock_phrase_rate` and `length_inflation` are not accidentally rewarded.

## 9. Source pinning and reproducibility

Promotion-quality public runs pin immutable dataset revisions where the source supports it and preserve resolved dataset fingerprints plus library versions. Mutable defaults are exploratory only.

Every promotion-quality result records:

- model repository/name and exact revision;
- model artifact/build SHA-256;
- quantization;
- runtime and version/commit;
- checkpoint type and explicit prompt adaptation mode;
- tokenizer identity and chat-template hash where available;
- hardware and OS;
- benchmark source/config/split/revision;
- model-visible task-file hash and count;
- decoding parameters (`temperature`, `top_p`, `top_k`, token limits) and seed;
- scorer/metric-contract revision;
- metric/judge provenance;
- raw-output hash.

`--prompt-mode auto`, unknown model revision, or unknown quantization may be acceptable for exploration, but they are not sufficient metadata for a promotion-quality comparison. Use `validate-english-core-run.py --promotion` and the frozen reproducibility manifest before promotion claims.

## 10. Claim tiers

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
- choice-order robustness for close contenders;
- item-bootstrap plus hierarchical dependence sensitivity;
- paired comparison for close contenders;
- weight sensitivity shown.

Allowed claim:

- `Model A is the stronger English Core candidate under Pari's current evaluation protocol.`

### Tier 2 — promotion-quality evidence

Add:

- primary official lexical anchors such as SWORDS;
- native BLiMP grammar evaluation where applicable;
- full-distribution prompted WiC/CoLA/PAWS lane;
- official JFLEG/EditEval or other relevant native protocols;
- pinned public-source provenance;
- quantization delta and product V1 route testing;
- reproducibility manifest and promotion-run validation.

Allowed claim:

- `Model A has stronger evidence for Pari's English workload across these specified benchmarks and fresh tests.`

### Tier 3 — strong research claim

Add:

- independently annotated/adjudicated shadow cases;
- reported human agreement/reliability appropriate to the annotation task;
- protocol sensitivity analysis;
- independent replication where practical;
- statistically supported paired differences;
- no material ranking flip under reasonable weighting/protocol choices.

Even here, prefer scoped claims over `objectively best English model`.
