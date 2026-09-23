# Pari English Core — research basis and validity notes

This document records the evidence behind the English Core benchmark design. It distinguishes **published evidence for the capability being measured** from **Pari-specific engineering choices** such as weights, sample budgets, and shadow-case wording.

The benchmark follows the spirit of Evidence-Centered Benchmark Design (ECBD): define the capability of interest, specify what model behavior counts as evidence for that capability, and document assumptions and threats to validity. It also follows HELM's multi-dimensional reporting principle: no single metric should hide important trade-offs.

## 1. Benchmark-design evidence

### Evidence-Centered Benchmark Design (ACL 2024)

Liu et al. argue that benchmark validity depends on explicitly connecting intended capabilities, tasks, response evidence, and scoring decisions rather than relying on implicit assumptions.

Reference: https://aclanthology.org/2024.acl-long.861/

English Core therefore records, for every dimension:

- the intended linguistic capability;
- public benchmark anchors;
- fresh Pari shadow families testing the same construct;
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
- human appropriateness judgments provide a stronger lexical gold signal than an LLM judge.

### WiC — NAACL 2019

WiC tests whether the same target word carries the same sense in two different contexts. It is specifically designed to evaluate context-sensitive meaning representations.

Reference: https://aclanthology.org/N19-1128/

Why it supports Pari:

A system should not suggest replacements for one sense of a word merely because they are synonyms under another sense. WiC isolates that prerequisite ability.

### LS07 / CoInCo

Older lexical-substitution benchmarks remain useful as complementary lexical tests. SWORDS is preferred when possible because it was designed to improve substitute coverage and contextual appropriateness.

## 3. Collocation and natural lexical choice

Espinosa Anke, Codina-Filba, and Wanner (EACL 2021) evaluate language models on lexical collocations such as `heavy rain` and `take a step`, including retrieval and contextual categorization across 17 semantic categories. They show that models can still struggle with fine-grained collocational restrictions.

Reference: https://aclanthology.org/2021.eacl-main.120/

Why it supports Pari:

Semantic relatedness is insufficient for natural rewriting. A model may know that `strong` and `heavy` are related in intensity while still producing the unnatural `strong rain`. Collocation therefore deserves its own dimension rather than being folded into generic semantic similarity.

## 4. Grammar and syntax

### BLiMP — TACL 2020

BLiMP contains 67 datasets of 1,000 minimal pairs, each isolating a grammatical phenomenon in English syntax, morphology, or semantics. The original paper reports 96.4% aggregate human agreement on labels.

Reference: https://aclanthology.org/2020.tacl-1.25/

Why it supports Pari:

Minimal pairs reduce topical and lexical confounds and test whether a model distinguishes grammatical from minimally altered ungrammatical forms.

### CoLA — TACL 2019

CoLA contains 10,657 English acceptability judgments drawn from linguistics literature and was designed to evaluate whether neural models acquire grammatical concepts used in linguistic analysis.

Reference: https://aclanthology.org/Q19-1040/

Caveat:

Acceptability is not identical to all of "English quality". CoLA and BLiMP are therefore one dimension, not the full benchmark.

### Forced-choice protocol

A 2026 ACL study of linguistically informed forced-choice acceptability judgments found that LLM performance varied by linguistic phenomenon but generally approximated human judgments, with prompt strategies having relatively small effects in that study.

Reference: https://aclanthology.org/2026.acl-srw.103/

This supports using minimal forced-choice prompts as a practical diagnostic, while retaining the caveat that prompted chat-model behavior is not identical to the original probability-based BLiMP protocol.

## 5. Paraphrase semantics

PAWS was constructed specifically to challenge models with sentence pairs that have high lexical overlap but differ in meaning because of word order and structural relations. The original paper shows that models lacking non-local contextual understanding fail badly on this setting.

Reference: https://aclanthology.org/N19-1131/

Why it supports Pari:

Paraphrasing can preserve almost every word while reversing roles, causality, or temporal order. PAWS therefore complements embedding similarity and surface-overlap metrics.

Pari shadow cases extend this construct to product-specific failure modes:

- actor/patient reversal;
- causal reversal;
- negation;
- modality;
- quantity;
- temporal order;
- comparison and scope.

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

This strongly supports keeping generative editing separate from lexical/grammar tests and avoiding one automatic metric as the sole quality signal.

### IteraTeR — ACL 2022

IteraTeR is a large-scale, multi-domain corpus of iteratively revised human-written text across edit intentions, revision depths, and granularities.

Reference: https://aclanthology.org/2022.acl-long.250/

Why it supports Pari:

Pari is an interactive revision tool rather than a blank-page content generator. Human revision histories are therefore more construct-valid than purely open-ended creative-writing prompts.

### WritingBench — 2025

WritingBench covers broad generative writing across six domains and 100 subdomains.

Reference: https://arxiv.org/abs/2503.05244

Use in English Core:

secondary evidence only. Open-ended writing mixes English competence with planning, instruction following, domain knowledge, and judge preferences.

## 8. Discourse relations

BeDiscovER (EACL 2026) aggregates 52 datasets across discourse lexicon, multi-sentence, and document-level discourse tasks and reports that modern LLMs still struggle with subtle rhetorical relations and long dependencies.

Reference: https://aclanthology.org/2026.eacl-long.207/

Why it supports Pari:

A locally fluent rewrite can still break `if` versus `when`, cause versus contrast, concession, purpose, or temporal order. Those relations therefore receive an explicit discourse diagnostic.

## 9. Contamination and fresh shadow cases

Public static benchmarks can be present in modern pretraining corpora. Deng et al. (NAACL 2024) provide evidence that benchmark contamination can inflate apparent performance, and a 2025 EMNLP survey describes the field's move from purely static toward dynamic evaluation in response to contamination risk.

References:

- https://aclanthology.org/2024.naacl-long.482/
- https://aclanthology.org/2025.emnlp-main.511/

English Core therefore reports public-anchor and Pari shadow performance separately.

The shadow set is **not** claimed to be an independently validated public benchmark. Its role is contamination-resistant transfer testing: reproduce the same linguistic phenomena with new surface forms. Repeated optimization against the shadow file itself would eventually contaminate it, so cases must be rotated over time.

## 10. Option-order and multiple-choice artifacts

Pezeshkpour and Hruschka (Findings of NAACL 2024) found large performance changes when LLM answer choices were reordered. Other 2024 work likewise shows that leaderboard rankings can change under small multiple-choice evaluation perturbations.

References:

- https://aclanthology.org/2024.findings-naacl.130/
- https://aclanthology.org/2024.acl-long.744/

English Core mitigation:

- every forced-choice shadow item is deterministically option-permuted;
- the public fast screen also permutes choices;
- WiC, CoLA, and PAWS fast-screen subsets are label-balanced;
- public-fast results are explicitly screening results, not official benchmark scores.

For official research reporting, use each benchmark's standard protocol in addition to the common prompted screen.

## 11. Text answers versus first-token logits

Wang et al. (Findings of ACL 2024) show that first-token multiple-choice probabilities can disagree substantially with the text answer produced by instruction-tuned LLMs.

Reference: https://aclanthology.org/2024.findings-acl.441/

English Core policy:

- text-answer accuracy is the common cross-runtime measure;
- token/logit margins may be recorded as an additional diagnostic when the runtime exposes them reliably;
- logit scoring must not silently replace actual text-output behavior.

## 12. LLM-as-a-judge limitations

Multiple studies report biases and vulnerabilities in LLM judges, including position bias and disagreement with human judgments.

References:

- https://aclanthology.org/2024.emnlp-main.474/
- https://aclanthology.org/2025.ijcnlp-long.18/
- https://aclanthology.org/2025.gem-1.33/

English Core therefore prefers, in order:

1. gold labels;
2. human reference sets;
3. deterministic linguistic/semantic checks;
4. independently validated specialist classifiers/rankers;
5. blinded human evaluation;
6. general LLM judges only as secondary diagnostics.

A candidate model is never allowed to grade its own generative output for the official score.

## 13. What is research-backed versus Pari-specific

### Research-backed constructs

- contextual word sense;
- lexical substitution;
- collocational knowledge;
- grammatical acceptability;
- high-overlap paraphrase semantics;
- fluency;
- formality/register distinction;
- iterative text editing/revision;
- discourse relations;
- contamination controls;
- option-order controls;
- multidimensional reporting.

### Pari-specific engineering choices

- the exact weights `25/20/15/15/10/10/5`;
- the 50-case shadow-set size;
- the 1,570-case public-fast budget;
- the exact wording of shadow items;
- which dimensions receive the most product emphasis.

These choices are justified by Pari's use case, not presented as scientific constants.

To expose dependence on the weights, the scorer reports both:

- the product-weighted `English Core` composite;
- an equal-weight mean across all seven dimensions;
- every individual dimension score.

If two models exchange rank under reasonable weighting schemes, report them as **weight-sensitive / capability-tradeoff candidates** rather than claiming a universal English winner.
