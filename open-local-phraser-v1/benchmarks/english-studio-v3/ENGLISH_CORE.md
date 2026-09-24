# Pari English Core — base-LLM English selection

English Core is a **model-selection benchmark for Pari's editing workload**, not a universal test of intelligence and not a claim to measure one latent quantity called “English ability.”

Its narrower question is:

> Which candidate model provides the strongest evidence, across several research-backed English-language capabilities, for Pari's rewriting/editing workload?

The benchmark deliberately excludes coding, mathematics, factual breadth, tool use and agent performance. Those capabilities can improve general LLM leaderboards while saying little about contextual lexical choice, collocation, natural phrasing or register.

Read together:

- `english-core-config.json` — machine-readable construct/weight/protocol contract;
- `ENGLISH_CORE_RESEARCH_BASIS.md` — primary research evidence and limitations;
- `RESEARCH_GROUNDING_POLICY.md` — standing evidence rules;
- `ENGLISH_CORE_ROBUSTNESS.md` — prompt/statistical/distribution/claim-tier protocol;
- `ENGLISH_CORE_HUMAN_EVAL.md` — independent shadow-label and generative human-evaluation protocol;
- `ENGLISH_CORE_RUN.md` — execution order.

The current fresh shadow seed contains **68 Pari-authored cases** and is explicitly `author_labeled_unvalidated`. It is useful as a contamination-resistant internal diagnostic, but it is not an independently validated public benchmark until issue #16's annotation/adjudication gate is completed.

---

## 1. What is research-backed and what is Pari-specific

### Research-backed constructs

English Core separates capabilities that have established NLP/linguistic evaluation traditions:

1. contextual lexical meaning / lexical substitution;
2. collocation and natural lexical choice;
3. grammar / syntactic acceptability;
4. paraphrase semantics;
5. fluency / register;
6. controlled editing and generative expression;
7. discourse relations and coherence.

The public anchors for those constructs come from peer-reviewed benchmarks such as SWORDS, WiC, BLiMP, CoLA, PAWS, JFLEG, GYAFC, EditEval and discourse-focused evaluations.

### Pari-specific engineering choices

The following are **not** literature-derived constants:

- the exact weights `25/20/15/15/10/10/5`;
- the number and wording of shadow cases;
- the public-fast sampling budgets;
- the decision to emphasize lexical/contextual editing more heavily than open-ended writing.

Those choices encode Pari's product workload. Always report the seven dimensions, the product-weighted composite, and the equal-weight dimension mean. If candidate rankings change materially under reasonable weighting schemes, describe a capability tradeoff rather than a universal winner.

---

## 2. English Core dimensions

| Dimension | Pari weight | Primary research role |
| --- | ---: | --- |
| contextual lexical meaning / word association | 25 | sense-in-context + lexical substitution |
| collocation / natural lexical choice | 20 | idiomatic lexical compatibility |
| grammar / syntax | 15 | acceptability and targeted grammatical phenomena |
| paraphrase semantics | 15 | meaning preservation under structural/surface similarity |
| fluency / register | 10 | native-like fluency + register/formality control |
| controlled editing / generative expression | 10 | revision, paraphrasing, restructuring |
| discourse relations | 5 | condition, cause, concession, temporal/coherence relations |

The weighted composite is allowed **only as a Pari candidate-selection aid**. It does not replace the product route benchmark and is not a psychometric scale of universal English competence.

---

## 3. Contextual lexical meaning / word association — 25%

This is Pari's highest-priority linguistic dimension because the core interaction is selecting a word or phrase and asking for context-valid alternatives.

Primary anchors:

- **SWORDS** — high-coverage contextual lexical substitution with human appropriateness judgments: https://aclanthology.org/2021.naacl-main.345/
- **WiC** — same/different word sense in context: https://aclanthology.org/N19-1128/
- CoInCo / SemEval lexical substitution as complementary historical anchors where reproducible.

SWORDS is especially construct-aligned with Pari: its paper explicitly motivates lexical substitution for writing assistance and argues that human judgment of proposed substitutes can provide better coverage than relying only on human recall.

Measure separately:

- word-sense discrimination;
- context-valid substitution;
- target-meaning preservation;
- human-reference/candidate coverage;
- ranking quality;
- usable alternatives deep into the candidate list.

A model does not receive credit merely because a replacement is a dictionary synonym under some other sense.

---

## 4. Collocation / natural lexical choice — 20%

Semantic relatedness is insufficient for natural rewriting. English allows combinations such as `heavy rain`, `make a decision`, `deeply concerned` and `draw a conclusion`, while semantically related alternatives can sound unnatural.

Primary anchor:

- EACL 2021 lexical-collocation retrieval/categorization benchmark: https://aclanthology.org/2021.eacl-main.120/

Pari shadow coverage includes adjective+noun, verb+noun, adverb+adjective and preposition compatibility.

This remains separate from generic embedding similarity because a system can preserve topic/meaning while choosing a non-native collocation.

---

## 5. Grammar / syntax — 15%

Primary anchors:

- **BLiMP** — controlled minimal pairs over 67 linguistic phenomena: https://aclanthology.org/2020.tacl-1.25/
- **CoLA** — acceptability judgments drawn from linguistics literature: https://aclanthology.org/Q19-1040/

The common Pari prompt lane uses direct forced choice for cross-runtime comparability. That is **not identical to every benchmark's native scoring protocol**, so native/official scores must be reported separately when making research-level claims.

The shadow set includes agreement, argument structure, determiner/word-order phenomena, negative-polarity licensing, binding agreement, morphology and do-support.

Do not ask for explanations or chain-of-thought; the diagnostic is the linguistic choice itself.

---

## 6. Paraphrase semantics — 15%

Primary anchor:

- **PAWS** — adversarial sentence pairs with high lexical overlap but potentially different meaning: https://aclanthology.org/N19-1131/

Pari cares about errors that surface-overlap or embedding metrics can miss:

- actor/patient reversal;
- causal reversal;
- negation;
- modality/certainty;
- quantity;
- temporal order;
- comparison;
- focus/scope.

Meaning preservation is therefore evaluated independently from naturalness.

---

## 7. Fluency / register — 10%

Primary anchors:

- **JFLEG** — human fluency corrections, evaluated with the official multi-reference GLEU workflow: https://aclanthology.org/E17-2037/
- **GYAFC** — formality/style transfer and register distinctions: https://aclanthology.org/N18-1012/

The goal is not to reward formality. Pari should preserve ordinary/casual wording when that is what the source uses.

A grammatical rewrite can still be wrong for Pari if it gratuitously becomes academic, corporate, abstract, intense, or verbose.

---

## 8. Controlled editing / generative expression — 10%

This dimension is intentionally smaller than lexical/contextual competence.

Primary anchors should emphasize **editing**, not blank-page essay writing:

- **EditEval** — modular text improvement/editing: https://aclanthology.org/2024.conll-1.7/
- **IteraTeR** — human iterative revision histories: https://aclanthology.org/2022.acl-long.250/
- fresh Pari span/sentence/paragraph editing cases, scored only with approved independent provenance.

Secondary diagnostics only:

- WritingBench selected style/language tasks;
- EQ-Bench creative-writing/slop diagnostics.

Open-ended writing benchmarks mix English competence with planning, knowledge, instruction following and judge preferences, so they must not dominate Pari model selection.

Generative shadow cases preserve raw outputs and require structured `metricProvenance`. A candidate model cannot grade its own official score, and an unvalidated general LLM judge cannot by itself populate the official composite.

---

## 9. Discourse relations — 5%

Primary external direction:

- BeDiscovER focused English tasks: https://aclanthology.org/2026.eacl-long.207/

Pari-specific discourse probes target relations that rewrites often damage even when individual sentences remain fluent:

- `if` versus `when`;
- cause versus contrast;
- concession;
- purpose;
- temporal order;
- sentence ordering/coherence.

---

## 10. Three evidence lanes must stay separate

Do not collapse these into one opaque number:

### A. Public/native anchors

Established benchmark data and official/native metrics where available. Examples: official SWORDS evaluation and JFLEG GLEU.

### B. Common prompted public screen

The deterministic BLiMP/WiC/CoLA/PAWS screen provides apples-to-apples prompted triage across chat/instruct models. It is useful, but it is not an official benchmark score and intentionally changes some source distributions through balanced sampling.

### C. Fresh Pari shadow set

Fresh surface forms test whether public-benchmark strength transfers to Pari-relevant examples. The current labels are author-written and remain internal evidence until independent annotation/adjudication is complete.

Public and shadow results are always reported separately because modern public benchmarks may be present in model pretraining corpora.

---

## 11. Robustness is part of the benchmark, not optional polish

Research on LLM evaluation shows that prompt wording, answer ordering, data distribution and aggregation choices can alter absolute scores and relative rankings.

Before a close candidate-selection claim:

- run multiple intent-preserving prompt variants;
- report answer consistency and worst-prompt performance;
- report uncertainty conditional on the current item set;
- compare models on the same items with paired analysis;
- inspect product-weighted and equal-weight views;
- preserve per-source, per-dimension and per-phenomenon results;
- record exact model/runtime/task/scorer provenance.

See `ENGLISH_CORE_ROBUSTNESS.md` for the required protocol and claim tiers.

---

## 12. Interpretation language

Preferred claims are scoped to the evidence.

Good:

- `Model A scored higher on the Pari product-weighted English Core under this protocol.`
- `Model A showed stronger lexical-substitution evidence on official SWORDS and the fresh Pari lexical probes.`
- `A and B are statistically inconclusive on the current shadow set.`
- `Model A's lead is weight-sensitive.`

Avoid:

- `Model A objectively has the best English.`
- `Model A is better because its raw average is 0.8 points higher.`
- treating the prompted public-fast screen as an official BLiMP/CoLA/SWORDS/JFLEG score.

The evidence standard increases with claim strength. Tier-3-style claims additionally require independently validated shadow labels, official primary anchors, protocol robustness, reproducibility and paired/statistical support.

---

## 13. Selection flow

1. Audit the shadow dataset (`audit-english-core-shadow.mjs`).
2. Build/run/score the canonical shadow profile.
3. Quantify uncertainty.
4. Run multi-prompt robustness.
5. Run the public-fast prompted screen.
6. Run primary official/native anchors, especially SWORDS for Pari's lexical role and JFLEG/EditEval where applicable.
7. Use paired comparisons for close contenders.
8. Inspect weight/protocol sensitivity and reproducibility metadata.
9. Only then compare quantization, RAM, latency and runtime stability.
10. Run the separate Pari V1 route/product acceptance suite.

English Core narrows the candidate field. The final shipping decision remains a product Pareto decision across linguistic quality, semantic safety, latency, memory and specialist routing.