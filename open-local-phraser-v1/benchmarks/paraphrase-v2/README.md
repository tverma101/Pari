# Pari Paraphrase Quality Benchmark v2

This benchmark replaces the idea that a high pass rate on the old 64-case adversarial suite is equivalent to high human paraphrase quality.

The old suite remains useful as a **safety torture test**. This v2 corpus is the product-quality benchmark for choosing a local paragraph-rewrite model.

## Product question

> Given ordinary or imperfect English, which model produces the clearest, most natural paragraph while preserving the writer's meaning, facts, relationships, uncertainty, and voice?

The benchmark intentionally separates constructs that the old scorer mixed together:

1. **meaning adequacy / propositional precision**;
2. **coherence and cohesion across sentences**;
3. **grammatical correctness and fluency**;
4. **lexical appropriateness / collocation**;
5. **edit discipline** — improve what needs improvement without gratuitous rewriting;
6. **factual and logical safety** — no invention, contradiction, anchor loss, role reversal, or modality flip.

## Standards and research trace

Every case in `corpus.json` includes `standardRefs`. Those IDs resolve through `sources.json` to the source, authority, construct, and exact claim used when designing the case.

The corpus is **not copied from those sources**. All benchmark prose is original. The sources define the writing construct; the test items were written specifically for Pari.

### Core standards used

- **Council of Europe CEFR Companion Volume (2020)** — coherence/cohesion and propositional precision. The benchmark uses these as construct definitions, especially clear relationships between ideas and preservation of degrees of certainty. This is not a claim that Pari or any model is formally CEFR-certified.
- **IELTS official Writing Band Descriptors / Cambridge English IELTS guidance** — coherence/cohesion, lexical appropriateness and collocation, grammatical range/accuracy, logical progression, and task-relevant content.
- **ETS TOEFL iBT Writing** — clear/effective communication, organization, accurate grammar/vocabulary, purpose and tone.
- **George Mason University Writing Center** — known→new information flow and explicit cohesion between sentences.
- **University of Wisconsin–Madison Writing Center** — paragraph unity, transitions/logical relationships, fragments, sentence sprawl, modifier attachment, concision and verb clarity.

### Evaluation-research receipts used

- Paraphrase evaluation literature separates **adequacy (meaning preservation)** from **fluency** and from **paraphrase difference**.
- ReproHum 2024 reproduces human paraphrase evaluation using meaning preservation, fluency and dissimilarity as separate dimensions.
- BEA 2025 minimal-edit GEC work is included because Pari should not reward overcorrection.
- CLEME2.0 (ACL 2025) explicitly separates correct edits, wrong edits, under-correction and over-correction.
- ACL 2025 work on GEC evaluation warns that corpus-level automatic rankings can diverge from human pairwise preferences; this benchmark therefore requires blinded pairwise human comparison for model promotion.

See `sources.json` for exact URLs and the claims used.

## Corpus structure

`corpus.json` contains **72 original paragraph-level cases** across 12 categories (6 each):

| Category | Main failure being tested |
| --- | --- |
| `meaning_equivalence` | natural paraphrase without changing claims |
| `cohesion_known_new` | sentence-to-sentence information flow |
| `logical_relations` | cause, contrast, condition, chronology, concession |
| `reference_coreference` | pronouns, referents, actor/patient identity |
| `modality_negation_precision` | may/might/must, uncertainty, negation, qualification |
| `factual_anchors` | names, dates, quantities, currency, quoted wording |
| `grammar_minimal_edit` | repair real grammar errors without needless rewriting |
| `sentence_structure` | fragments, run-ons, modifier attachment, parallel structure |
| `lexical_collocation` | context-appropriate word choice and natural collocations |
| `register_tone` | clean prose while preserving intended level of formality/voice |
| `paragraph_unity_redundancy` | one coherent point, no repetition or topic drift |
| `ambiguity_non_invention` | clarify only what the source supports; do not invent missing facts |

## Required evaluation protocol

### 1. Hard safety veto

A candidate is ineligible to win a case if it introduces any of the following:

- contradiction of the source;
- negation reversal;
- modality/certainty inflation or weakening that changes the claim;
- quantity/date/name/currency/quoted-text corruption;
- actor↔patient or referent reversal;
- invented event, reason, identity, outcome, or evidence;
- loss of a required causal/contrast/conditional relationship.

These are binary failures, not style penalties.

### 2. Human rating dimensions

For candidates that survive the safety veto, rate each dimension from 1–5:

| Dimension | Weight | 5 means |
| --- | ---: | --- |
| Meaning adequacy / precision | 30% | all recoverable meaning and qualification preserved |
| Coherence / cohesion | 25% | paragraph flows logically; relationships are immediately understandable |
| Grammar / fluency | 20% | natural, well-formed English with no distracting grammar/punctuation defects |
| Lexical / collocation quality | 15% | words fit their exact context; no thesaurus-like awkwardness |
| Edit discipline | 10% | enough rewriting to improve the text without needless semantic/style churn |

**Paraphrase distance is not a quality dimension.** It may be reported descriptively, but a more different output does not outrank a better conservative output.

### 3. Pairwise model selection

Primary selection is **blinded pairwise preference** on the same source paragraphs. Aggregate model wins/ties/losses by category and overall. Do not crown a model from one scalar automatic metric.

Automatic measurements (MiniLM similarity, grammar diagnostics, edit distance, anchor checks, latency and memory) are supporting diagnostics. They are not substitutes for human judgment of natural English.

### 4. Prompt parity

Use the same product intent for every model:

> Rewrite the paragraph so it is clear, natural, and grammatically correct. Preserve the writer's meaning, facts, uncertainty, relationships between ideas, and overall voice. Do not invent details. Return only the rewritten paragraph.

Specialist models may require their documented task syntax (for example CoEdIT edit instructions or DIPPER control tokens), but the requested behavior must remain equivalent. Record every model-specific prompt/template in the result metadata.

### 5. Local deployment measurements

For every contender record:

- exact checkpoint/revision;
- quantization and runtime;
- model file size;
- peak unified memory;
- first-token latency where applicable;
- end-to-end paragraph latency;
- output tokens/sec where applicable;
- warm/cold behavior;
- failure rate;
- target hardware and macOS version.

## Promotion gates

A model cannot become Pari's local default unless:

1. it has **zero hard-safety regressions** versus the incumbent on the v2 safety-sensitive cases and the old canary suite;
2. it wins or ties the incumbent on **meaning adequacy**;
3. it improves the weighted human quality score or achieves comparable quality with a material RAM/latency advantage;
4. no category shows a severe regression hidden by the overall average;
5. installed-app/native-runtime operation is proven on the target M4/16-GB Mac.

## Relationship to the old benchmark

Keep `benchmarks/eval/corpus.json` as an adversarial regression suite. Its historical automatic score is not a human-quality percentage. Run both:

- **old suite:** safety/regression torture test;
- **v2 suite:** actual paraphrase/editing model selection.
