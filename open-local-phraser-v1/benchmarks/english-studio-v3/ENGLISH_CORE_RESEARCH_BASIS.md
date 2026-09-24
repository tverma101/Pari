# Pari English Core — research basis and validity notes

This document records the evidence behind the English Core benchmark design. It distinguishes **published evidence for the capability being measured** from **Pari-specific engineering choices** such as weights, sample budgets, shadow-case wording, grouping decisions, and promotion gates.

The benchmark follows the spirit of Evidence-Centered Benchmark Design (ECBD): define the capability of interest, specify what model behavior counts as evidence for that capability, and document assumptions and threats to validity. It also follows HELM's multi-dimensional reporting principle: no single metric should hide important trade-offs.

The standing change-control rule is in [`RESEARCH_GROUNDING_POLICY.md`](./RESEARCH_GROUNDING_POLICY.md). Future benchmark changes must satisfy that policy before being treated as part of English Core.

## 1. Benchmark-design evidence

### Evidence-Centered Benchmark Design — ACL 2024

Liu et al. argue that benchmark validity depends on explicitly connecting intended capabilities, tasks, response evidence, and scoring decisions rather than relying on implicit assumptions.

Reference: https://aclanthology.org/2024.acl-long.861/

English Core therefore records, for every dimension:

- the intended linguistic capability;
- public benchmark anchors;
- fresh Pari shadow families probing related constructs;
- the metric used to turn responses into evidence;
- known threats to validity.

### HELM / multidimensional evaluation

HELM argues for broad scenario coverage, standardized adaptation, and multi-metric reporting rather than treating one leaderboard number as a complete model description.

Reference: https://arxiv.org/abs/2211.09110

English Core therefore always reports the seven dimension scores. The product-weighted composite is only a model-selection aid.

## 2. Contextual lexical meaning / word association

### SWORDS — NAACL 2021

SWORDS directly evaluates lexical substitution: finding replacements for a target word that are appropriate in a particular context. The paper explicitly motivates lexical substitution as writing assistance and improves coverage by generating broad candidate sets and asking humans to judge contextual appropriateness.

Reference: https://aclanthology.org/2021.naacl-main.345/

Why it supports Pari:

- Pari needs contextual alternatives rather than context-free thesaurus synonyms;
- high-coverage candidate judgments are closer to a 10–40 suggestion UI than one-reference paraphrase scoring;
- human appropriateness judgments provide a stronger lexical gold signal than a general LLM judge.

### WiC — NAACL 2019

WiC tests whether the same target word carries the same sense in two different contexts. It is specifically designed to evaluate context-sensitive meaning representations.

Reference: https://aclanthology.org/N19-1128/

Why it supports Pari:

A system should not suggest replacements for one sense of a word merely because they are synonyms under another sense. WiC isolates that prerequisite ability.

### LS07 / CoInCo

Older lexical-substitution benchmarks remain useful complementary lexical tests. SWORDS is preferred when possible because it was designed to improve substitute coverage and contextual appropriateness.

## 3. Collocation and natural lexical choice

Espinosa Anke, Codina-Filba, and Wanner (EACL 2021) evaluate language models on lexical collocations such as `heavy rain` and `take a step`, including retrieval and contextual categorization across 17 semantic categories.

Reference: https://aclanthology.org/2021.eacl-main.120/

Why it supports Pari:

Semantic relatedness is insufficient for natural rewriting. A model may know that `strong` and `heavy` are related in intensity while still producing the unnatural `strong rain`. Collocation therefore deserves its own dimension rather than being folded into generic semantic similarity.

## 4. Grammar and syntax

### BLiMP — TACL 2020

BLiMP contains 67 datasets of 1,000 minimal pairs, each isolating a grammatical phenomenon in English syntax, morphology, or semantics. The original paper reports 96.4% aggregate human agreement on labels.

Reference: https://aclanthology.org/2020.tacl-1.25/

Why it supports Pari:

Minimal pairs reduce topical and lexical confounds and test whether a model distinguishes grammatical from minimally altered ungrammatical forms.

### CoLA — linguistic acceptability

CoLA contains 10,657 English acceptability judgments drawn from linguistics literature and was designed to evaluate whether neural models acquire grammatical concepts used in linguistic analysis.

Reference: https://aclanthology.org/Q19-1040/

Caveat:

Acceptability is not identical to all of "English quality". CoLA and BLiMP are therefore one dimension, not the full benchmark.

### Forced-choice acceptability evidence — ACL SRW 2026

Liu & Reiter evaluate LLMs on 150 linguistically categorized minimal sentence pairs in a forced-choice acceptability paradigm and report variation by model and linguistic phenomenon, with models generally approximating human judgments.

Reference: https://aclanthology.org/2026.acl-srw.103/

This supports forced-choice acceptability as a useful diagnostic while retaining the caveat that prompted chat-model behavior is not identical to BLiMP's probability/likelihood protocol.

## 5. Paraphrase semantics

PAWS was constructed specifically to challenge models with sentence pairs that have high lexical overlap but differ in meaning because of word order and structural relations.

Reference: https://aclanthology.org/N19-1131/

Why it supports Pari:

Paraphrasing can preserve almost every word while reversing roles, causality, or temporal order. PAWS therefore complements embedding similarity and surface-overlap metrics.

Pari shadow cases extend this construct to product-specific failure modes including actor/patient reversal, causal reversal, negation, modality, quantity, temporal order, focus/scope, and syntactic-equivalence traps.

## 6. Fluency and register

### JFLEG — EACL 2017

JFLEG evaluates grammatical error correction with holistic fluency edits intended not only to repair errors but also to make text more native-sounding.

Reference: https://aclanthology.org/E17-2037/

Why it supports Pari:

Pari needs natural English after editing, not merely syntactic correctness.

### GYAFC — NAACL 2018

GYAFC is a large formality style-transfer corpus and benchmark.

Reference: https://aclanthology.org/N18-1012/

Why it supports Pari:

Pari normally wants to preserve the source register rather than automatically formalize it. GYAFC gives an external anchor for whether a model can discriminate and control formality.

Caveat:

Formality is only one aspect of register. Pari's shadow set also covers casual intensity, contractions, student-like wording, and vocabulary inflation.

## 7. Generative expression and editing

### EditEval — CoNLL 2024

EditEval argues that writing is iterative and incremental and evaluates modular text-improvement abilities including paraphrasing and cohesion. It also reports that commonly used editing metrics do not always correlate well and that prompt choices do not transfer uniformly across models.

Reference: https://aclanthology.org/2024.conll-1.7/

This supports keeping generative editing separate from lexical/grammar tests and avoiding one automatic metric as the sole quality signal.

### IteraTeR — ACL 2022

IteraTeR is a large-scale, multi-domain corpus of iteratively revised human-written text across edit intentions, revision depths, and granularities.

Reference: https://aclanthology.org/2022.acl-long.250/

Why it supports Pari:

Pari is an interactive revision tool rather than a blank-page content generator. Human revision histories are therefore more construct-valid than purely open-ended creative-writing prompts.

### WritingBench — secondary only

WritingBench covers broad generative writing across six domains and 100 subdomains.

Reference: https://arxiv.org/abs/2503.05244

Use in English Core: secondary evidence only. Open-ended writing mixes English competence with planning, instruction following, domain knowledge, and judge preferences.

## 8. Discourse relations

BeDiscovER (EACL 2026) aggregates 52 datasets across discourse lexicon, multi-sentence, and document-level discourse tasks and reports that modern LLMs still struggle with subtle rhetorical relations and long dependencies.

Reference: https://aclanthology.org/2026.eacl-long.207/

Why it supports Pari:

A locally fluent rewrite can still break `if` versus `when`, cause versus contrast, concession, purpose, or temporal order. Those relations therefore receive an explicit discourse diagnostic.

## 9. Public-benchmark contamination and fresh shadow cases

Public static benchmarks can be present in modern pretraining corpora. Deng et al. (NAACL 2024) investigate contamination in modern LLM benchmarks; PaCoST (Findings EMNLP 2024) proposes paired confidence testing for contamination detection.

References:

- https://aclanthology.org/2024.naacl-long.482/
- https://aclanthology.org/2024.findings-emnlp.97/
- broader dynamic-evaluation survey: https://aclanthology.org/2025.emnlp-main.511/

English Core therefore reports public-anchor and Pari shadow performance separately.

The shadow set is **not** claimed to be an independently validated public benchmark. Its role is fresh-surface transfer testing: reproduce relevant linguistic phenomena using newly authored surface forms. Repeated optimization against the shadow file itself would eventually compromise that freshness, so cases must rotate over time.

The current seed contains **68 author-labeled cases** and remains `author_labeled_unvalidated` until the independent procedure in `ENGLISH_CORE_HUMAN_EVAL.md` is completed.

Freshness does not equal validity.

## 10. Prompt sensitivity

Mizrahi et al. (TACL 2024) evaluate 20 LLMs over 39 tasks and 6.5M instances using instruction paraphrases and show that different prompt templates can materially change both absolute scores and relative model rankings.

Reference: https://aclanthology.org/2024.tacl-1.52/

English Core mitigation:

- canonical prompts remain fixed for the main run;
- close contenders receive three intent-preserving prompt variants;
- report mean, worst-prompt, spread, all-prompts-correct, and answer-consistency diagnostics;
- never choose the best prompt after observing model results and report only that prompt.

## 11. Option-order and multiple-choice artifacts

2024 work shows that LLM choices and leaderboard ordering can change under option-order and answer-selection perturbations.

References:

- Wei et al., order/token selection bias: https://aclanthology.org/2024.findings-acl.333/
- Pezeshkpour & Hruschka, option-order sensitivity: https://aclanthology.org/2024.findings-naacl.130/
- Alzahrani et al., leaderboard perturbation sensitivity: https://aclanthology.org/2024.acl-long.744/

English Core mitigation:

- every canonical forced-choice shadow item is deterministically option-permuted;
- public prompted screens also permute choices;
- WiC, CoLA, and PAWS fast-screen subsets are label-balanced;
- close contenders receive a second counterbalanced presentation of each forced-choice shadow item;
- order robustness is reported separately rather than folded into the English score.

## 12. Text answers versus first-token logits

Wang et al. (Findings of ACL 2024) show that first-token multiple-choice probabilities can disagree substantially with the text answer produced by instruction-tuned LLMs.

Reference: https://aclanthology.org/2024.findings-acl.441/

English Core policy:

- text-answer accuracy is the common cross-runtime prompted measure;
- token/logit margins may be recorded as an additional diagnostic when the runtime exposes them reliably;
- logit scoring must not silently replace actual text-output behavior.

For benchmark-native likelihood tasks such as BLiMP, native likelihood scoring remains a separate evidence lane rather than being relabeled as prompted text accuracy.

## 13. LLM-as-a-judge and learned-metric limitations

LLM judges can exhibit position/format bias and disagreement with humans, and learned metric models introduce their own error into significance estimates.

References:

- LLM judge limitations: https://aclanthology.org/2024.emnlp-main.474/
- model-based metric uncertainty: https://aclanthology.org/2023.emnlp-main.464/

English Core therefore:

- prefers gold labels, human references, official deterministic metrics, and blinded human evaluation;
- requires explicit identity/version/protocol/validation evidence for specialist learned evaluators;
- treats general LLM judges as secondary diagnostics;
- never allows a candidate model to grade its own generative output for the official score;
- preserves metric direction through `english-core-generative-metric-contract.json` so failure rates are not accidentally rewarded.

## 14. Distributional validity

Siska et al. (ACL 2024) show that benchmark test prompts need not behave like independent random draws from a single use-case distribution; accounting for prompt correlations can change rankings. Kovatchev & Lease (NAACL 2024) show that benchmark data distributions can materially affect absolute and relative performance.

References:

- https://aclanthology.org/2024.acl-long.560/
- https://aclanthology.org/2024.naacl-long.86/

English Core therefore reports public-native, public-prompted, shadow, and application-weighted evidence separately. It does not claim that the 68 shadow cases estimate a universal English population.

## 15. Statistical uncertainty and paired comparison

Bootstrap and paired-evaluation research supports reporting uncertainty and respecting the fact that competing models are tested on the same items.

References:

- BooStSa: https://aclanthology.org/2022.acl-demo.12/
- Better than Average / paired NLP evaluation: https://aclanthology.org/2021.acl-long.179/

English Core therefore:

- reports item-bootstrap uncertainty only for completely scored dimensions;
- adds a **phenomenon/item hierarchical-bootstrap sensitivity analysis** because author-written cases sharing a phenomenon/template may be dependent;
- treats the hierarchical lane as exploratory rather than a population-confidence interval;
- performs aligned paired model comparison on identical items and identical benchmark/task hashes;
- withholds headline paired conclusions when coverage is incomplete;
- reports close differences as inconclusive when paired intervals cross zero.

Nested-data methodology motivating the sensitivity lane:

- Burchill & Jaeger 2024: https://doi.org/10.1016/j.jml.2023.104494
- Anglin 2026 preprint: https://arxiv.org/abs/2606.26422

Critical caveat: no cited paper validates Pari's `phenomenon` tags as a randomly sampled statistical hierarchy. Using those tags for hierarchical resampling is a disclosed engineering sensitivity analysis.

## 16. Native versus prompted protocols

A common prompted interface is useful for model comparison, but benchmark-native evidence remains separate.

Examples:

- BLiMP: native sentence/minimal-pair likelihood is primary grammar evidence; chat A/B is a prompted screen.
- CoLA: full-distribution MCC is reported separately from balanced fast-screen accuracy.
- SWORDS and JFLEG: use official evaluators rather than inventing Pari replacements.

See `ENGLISH_CORE_NATIVE_PROTOCOLS.md` and `english-core-public-anchors.json`.

## 17. Source pinning and reproducibility

Promotion-quality public runs pin immutable source revisions where supported and record resolved dataset fingerprints and library versions. Model runs record exact checkpoint revision/build hash, quantization, runtime, tokenizer/chat-template identity, task hash/count, decoding, hardware, and raw-output hash.

`validate-english-core-run.py --promotion` and `build-english-core-repro-manifest.py --require-promotion-ready` turn these into reproducibility gates rather than optional notes.

## 18. What is research-backed versus Pari-specific

### Research-backed constructs / validity concerns

- contextual word sense;
- lexical substitution;
- collocational knowledge;
- grammatical acceptability;
- high-overlap paraphrase semantics;
- fluency;
- formality/register distinction;
- iterative text editing/revision;
- discourse relations;
- public-benchmark contamination risk;
- prompt sensitivity;
- option-order sensitivity;
- multidimensional reporting;
- data-distribution effects;
- paired evaluation and uncertainty reporting;
- learned-metric uncertainty.

### Pari-specific engineering choices

- the exact weights `25/20/15/15/10/10/5`;
- the current **68-case** shadow-set size and exact case wording;
- the 1,570-case public-fast budget;
- three prompt variants for the robustness lane;
- two option-order presentations for the order lane;
- grouping shadow items by Pari `phenomenon` tags for hierarchical sensitivity;
- which dimensions receive the most product emphasis;
- claim-tier governance thresholds/workflow.

These choices are justified by Pari's use case or operational needs, not presented as scientific constants.

To expose dependence on the weights, the scorer reports both:

- the product-weighted `English Core` composite;
- an equal-weight mean across all seven dimensions;
- every individual dimension score.

If two models exchange rank under reasonable weighting or protocol choices, report them as **weight/protocol-sensitive capability tradeoffs** rather than claiming a universal English winner.

## 19. Standing research-grounding gate

English Core is not allowed to drift into a collection of plausible-looking tests. Before a substantive benchmark change is treated as valid, it must pass `RESEARCH_GROUNDING_POLICY.md`.

At minimum:

- the intended construct must have primary-source support or be labeled explicitly as a Pari-specific product heuristic;
- the benchmark's official protocol and metric must be checked before creating a local approximation;
- local approximations must be labeled as screens rather than official scores;
- threats to validity, contamination, prompt/answer-position effects, dependence, and judge error must be documented;
- model-selection claims must be no broader than the evidence supports;
- a benchmark should not be added or weighted simply because it favors a preferred candidate model;
- new research that conflicts with the present design triggers benchmark review rather than being ignored to preserve historical scores.
