# Pari English Studio v3 — benchmark and model map

This document answers two questions:

1. Which public benchmarks actually measure something relevant to Pari?
2. How should models be selected without rejecting a useful specialist because it is weak at an unrelated task?

## Core rule

**No global model leaderboard decides Pari.**

Each model gets a capability profile. A model may be promoted for one route while losing badly on another.

Hard semantic/safety failures are global vetoes. Everything else is route-specific.

---

# 1. Capability routes

## Route A — lexical / local span alternatives

Product job:

- click one word or short phrase;
- get many context-valid replacements;
- allow 1 word -> many words and many words -> 1 word;
- preserve surrounding sentence meaning and grammar;
- rank useful alternatives near the top.

Primary benchmarks:

- Microsoft Smart Word Suggestions (SWS);
- TSAR lexical simplification;
- Pari interactive span suite;
- local containment + meaning gates.

Useful training data:

- SWS distant training data as auxiliary only;
- human SWS test remains evaluation-only;
- localized human revision spans extracted from IteraTeR;
- selected WikiAtomicEdits patterns only after filtering and provenance checks;
- user click/revert data for preference reranking only after objective filters.

A model does **not** need to score well on long-form writing to win this route.

## Route B — grammar / fluency repair

Product job:

- fix malformed English;
- preserve good wording when it is already fine;
- avoid over-editing.

Primary benchmarks:

- JFLEG + official GLEU;
- optional ERRANT/M2 suite after licensing/access review;
- Pari grammar/adversarial regression.

Useful models:

- CoEdIT-large / XL as research references;
- compact GEC specialists;
- general model only if it beats the specialist enough to justify cost.

A model does **not** need creative-writing strength to win this route.

## Route C — sentence / paragraph paraphrasing

Product job:

- paste paragraph;
- get one natural rewrite;
- preserve facts, logical relations and approximate register;
- rewrite more at higher strength without becoming more academic by default.

Primary benchmarks:

- IteraTeR held-out revisions;
- EditEval paraphrase/cohesion tasks;
- Pari paraphrase-v2;
- Pari QuillBot hard-tail suite;
- strength-calibration suite;
- meaning/safety gates.

Secondary diagnostics:

- ASSET for compression/reordering/splitting behavior;
- PAWS for adversarial meaning traps.

This is the main general-generator route.

## Route D — simplification / compression / expansion

Product job:

- 5 words -> 1 word;
- 1 word -> phrase;
- shorter / clearer expression;
- expand wording without inventing facts.

Primary benchmarks:

- ASSET + SARI;
- TSAR for lexical simplification;
- Pari interactive phrase-length cases.

A model can win this route even if it is not the main paragraph generator.

## Route E — style/register preservation

Product job:

- keep ordinary student/casual/professional language at approximately the same level;
- avoid automatic professor/corporate inflation;
- produce natural English rather than stock LLM phrasing.

Primary signals:

- IteraTeR human revisions;
- Pari register/vocabulary-ceiling suite;
- lexical frequency/readability drift;
- repeated-stock-phrase rate;
- accepted human-reference alternatives where available.

Secondary benchmarks:

- WritingBench style-requirement subset;
- Arena Creative Writing / Writing-Literature-Language as teacher-selection priors only.

Do not optimize against AI-detector scores.

## Route F — personalization ranker

Product job:

- among already-valid alternatives, predict which wording this user will prefer;
- learn which words/phrases they tend to keep, expand, compress or replace.

Primary benchmark:

- held-out user interactions only.

Metrics:

- pairwise chosen-vs-rejected accuracy;
- MRR/NDCG of chosen option;
- revert rate;
- zero objective-quality regression.

The user is a style-preference labeler here, not an English correctness labeler.

---

# 2. External benchmark relevance

## Highest relevance

### EditEval

Why:

- benchmark specifically targets iterative text improvements;
- includes modular editing capabilities such as cohesion and paraphrasing;
- closer to Pari than generic chat benchmarks.

Use:

- add as a first-class external suite;
- report per task rather than only average.

Reference:

- https://aclanthology.org/2024.conll-1.7/

### Smart Word Suggestions

Why:

- explicitly models writing-assistance substitution rather than thesaurus lookup;
- identifies words/phrases needing improvement and ranks replacements in context;
- human test set is directly relevant to Pari's click-to-change UX.

Use:

- first-class lexical/span benchmark.

Reference:

- https://github.com/microsoft/SmartWordSuggestions

### IteraTeR

Why:

- human revision history;
- multi-granularity edit behavior;
- directly relevant to iterative editing rather than generation from scratch.

Use:

- training on train split;
- official dev/test frozen for evaluation;
- extract local span examples only through a validated alignment pipeline.

### JFLEG

Why:

- four human corrections per source;
- measures fluent correction, not merely minimal error repair.

Use:

- objective grammar/fluency reference.

### ASSET

Why:

- ten human simplifications per source;
- contains paraphrase, compression, sentence splitting/reordering behavior.

Use:

- phrase-length change and simplification route.

### TSAR

Why:

- ranked lexical alternatives with metrics such as MAP, Potential and Accuracy;
- directly useful for suggestion ranking.

Use:

- lexical route.

---

# 3. Useful but secondary writing benchmarks

## WritingBench

What it measures well:

- broad generative writing across six domains / 100 subdomains;
- per-query criteria for style, format and length;
- current release has 1,000 writing queries;
- provides a specialized Qwen-7B critic model;
- shows that task-specific writing training can substantially improve a 7B model.

Why it is not a Pari promotion gate:

- mostly generation from instructions/materials, not local editing of existing prose;
- scores depend on a critic/LLM judge;
- fixed public prompt set has contamination risk;
- a model may be a good author but poor conservative editor.

Use:

- teacher/model screening;
- style requirement subset as a secondary diagnostic;
- study its writing-specialization recipe.

Reference:

- https://github.com/X-PLUG/WritingBench

## Arena Creative Writing / Writing, Literature & Language

What it measures:

- real user pairwise preference at large scale;
- useful current signal about which proprietary/general models humans prefer for writing.

Current 2026 observation:

- Anthropic models lead the creative-writing and writing/language categories;
- Meta Muse is strong overall but is not the creative-writing leader;
- open-weight/available families can rank much lower or differently than their general capability rank.

Why it is not a Pari gate:

- prompts are open-ended and heterogeneous;
- pairwise preference includes style preferences unrelated to conservative rewriting;
- model size/API availability may make leaders unusable as local targets;
- route-specific editing quality is not isolated.

Use:

- choose proprietary teacher/reference models for spot checks;
- calibrate whether a local model's prose feels broadly competitive;
- never use Arena rank as automatic promotion.

## Arena-Hard Creative Writing v2

Useful because:

- provides a reproducible creative-writing subset derived from Arena-style prompts;
- can help compare writer specialization before expensive human preference collection.

Caution:

- automatic LLM judges can exhibit style/verbosity bias;
- use only as a secondary screen.

## LongBench-Write / LongWriter benchmarks

Useful for:

- long-output stability;
- paragraph/document coherence stress testing.

Not central because:

- Pari usually edits existing paragraphs rather than generating 10k-word documents.

Use:

- optional stress test for larger pasted inputs and coherence.

## LitBench

Useful lesson:

- even strong off-the-shelf LLM judges only partially agree with human creative-writing preference;
- a specialized preference model can outperform general judges.

Use:

- evidence that Pari should train a small preference ranker rather than blindly trust one giant LLM judge.

---

# 4. Current model-screening implications

## Proprietary teacher/reference set

Use only for evaluation/data generation where terms and privacy permit:

- current top Anthropic writing model(s);
- a current Gemini writing-capable model;
- a current OpenAI model;
- Meta Muse as a comparison because its overall rank is high but writing rank differs.

Purpose:

- establish a quality ceiling;
- identify which kinds of edits proprietary models do better;
- create candidate pools only for residual gaps after verified human data is used.

Do not copy one proprietary model's style into the whole dataset.

## Open/local candidates

Test classes rather than assuming one family:

### General current models

- Qwen 3.5/3.8 family;
- GLM/Z.ai family;
- MiniCPM;
- Ling sparse models;
- other <=16-GB realistic candidates as they appear.

### Writing-specialized models

- Writing-Model-Qwen-7B (Apache-2.0) as a writing-specialization reference;
- Writing-RL descendants where released/licensed;
- LongWriter 8B/9B as long-writing references, not presumed editors.

### Editing-specialized models

- CoEdIT-large (770M), XL (3B), XXL (11B) as research references;
- CoEdIT checkpoints are CC-BY-NC-4.0, so do not make them shipping dependencies;
- use their architecture/data recipe as evidence that small editing specialists can be competitive.

### Paragraph paraphrase specialists

- DIPPER/PAR3 as research references for controllable lexical/order diversity;
- do not optimize for detector evasion;
- PAR3 is based on multiple human translations of public-domain novels, so its register/domain differs sharply from normal student prose.

---

# 5. Human-sounding operational definition

Do not use `AI detector probability` as the target.

For Pari, "human sounding" means a bundle of measurable properties:

1. grammatical in context;
2. preserves source meaning and logical relations;
3. approximate register/readability stays near source unless requested otherwise;
4. common/natural collocations instead of rare thesaurus replacements;
5. avoids repeated generic transition/filler patterns across unrelated inputs;
6. preserves useful contractions/informal constructions when appropriate;
7. sentence-length and clause structure do not inflate gratuitously;
8. alternative sets include multiple natural ways to express the same meaning;
9. outputs resemble patterns found in real human revisions, not only teacher-generated rewrites;
10. personalized ranker increasingly predicts the user's choices among valid options.

These signals can be measured without asking the user to grade English correctness.

---

# 6. Model promotion rules by route

A model is **not rejected globally** because it loses one unrelated benchmark.

For each route record:

- hard safety pass/fail;
- route-specific external metrics;
- Pari internal metrics;
- latency/RAM;
- model/runtime reliability.

Examples:

- a 770M grammar model can win grammar repair and never be considered for paragraph generation;
- a 27B low-bit model can win paragraph rewriting but lose word suggestions to a tiny masked-LM route;
- a 7B writing-specialized model can be a teacher/reference even if it is worse than a 4B editor on local span containment;
- a general model can be kept only for difficult sentence/paragraph cases while specialists handle cheaper operations.

Selection output is a **routing table + Pareto frontier**, not a single `best model`.
