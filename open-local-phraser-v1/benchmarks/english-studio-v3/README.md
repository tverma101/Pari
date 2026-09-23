# Pari English Studio Benchmark v3

This benchmark changes Pari's optimization target without deleting or invalidating the older work.

Existing suites remain first-class inputs:

- `benchmarks/eval/` — adversarial safety/regression torture tests;
- `benchmarks/quillbot/` — large broken-English / QuillBot comparison corpus;
- `benchmarks/paraphrase-v2/` — standards-traced paragraph rewrite quality benchmark.

`english-studio-v3` adds the missing product question:

> Can Pari act as a fast, highly controllable English rewriting studio where the system gives the user a strong starting draft and then lets the user rewrite any word, phrase, clause, sentence, or paragraph while preserving meaning and choosing the final wording themselves?

The target is not maximum edit distance and not professor-like prose. It is natural English at approximately the writer's existing register, with a large toolbox of context-safe alternatives.

## Product loop under test

```text
paste a large paragraph
  -> choose rewrite strength
  -> receive one natural editable draft
  -> select any word / phrase / clause / sentence
  -> generate many meaning-preserving alternatives
  -> user chooses, mixes, or edits
  -> approve final version
  -> personalization learns only from approved choices
```

The model proposes. Pari removes objectively bad candidates. The human remains the final stylistic ranker.

## Why composite instead of one fake giant corpus

Do not inflate case count by duplicating a handful of templates.

The v3 benchmark is a **composite task matrix**. It reuses the existing independently useful corpora and adds new interactive-edit cases. The same source may be tested under several distinct operations, but results must be reported by task family rather than collapsed into one misleading score.

Initial source inventory:

- old adversarial suite: ~64 source cases;
- frozen QuillBot suite: 320 source cases;
- standards-traced paragraph v2: 72 source cases;
- new interactive-edit seed: target 100+ original source/span cases;

That yields 550+ distinct source cases. Applying the relevant task matrix produces **thousands of scored task instances** without pretending repeated templates are independent prose.

## Capability matrix

### A. Meaning and factual safety

1. meaning equivalence
2. negation preservation
3. modality / certainty preservation
4. actor-patient / subject-object roles
5. quantities and numbers
6. names, dates, currency, URLs, quotations and code-like spans
7. causal relationships
8. contrast and concession
9. conditionals
10. chronology and temporal order
11. ambiguity without invention
12. scope and qualification
13. comparison direction
14. point of view / person

### B. Grammar and sentence mechanics

15. subject-verb agreement
16. tense and aspect
17. articles and determiners
18. prepositions
19. pronouns and coreference
20. fragments
21. run-ons and comma splices
22. punctuation
23. modifier attachment
24. parallel structure
25. coordination and lists
26. capitalization
27. spelling / typo repair
28. commonly confused words
29. verb frames and argument structure
30. noun number / countability

### C. Natural wording and lexical control

31. natural collocations
32. awkward thesaurus language
33. idioms and phrasal verbs
34. ordinary vocabulary preservation
35. register preservation
36. informal / conversational English
37. student academic English without professor inflation
38. professional English without corporate inflation
39. contractions and natural rhythm
40. concision
41. expansion without adding facts
42. redundancy removal
43. specificity preservation
44. hedging preservation

### D. Interactive rewrite studio

45. single word -> single word
46. single word -> multi-word phrase
47. multi-word phrase -> single word
48. phrase -> different-length phrase
49. clause -> clause
50. full sentence -> full sentence
51. sentence split
52. sentence join
53. local edit containment: selected span changes while unrelated text stays stable
54. alternative diversity without semantic drift
55. contextual ranking / naturalness
56. preserve grammatical inflection around replacements
57. replacement length freedom
58. phrase-boundary detection
59. protected-span interaction
60. undo / revert semantic integrity

### E. Whole-paragraph control

61. paragraph coherence and cohesion
62. logical flow between sentences
63. topic / paragraph unity
64. repetition control
65. rewrite-strength calibration
66. sentence-count preservation when appropriate
67. broken-prose reconstruction
68. large-paragraph stability
69. mixed-quality paragraphs: fix weak parts without rewriting good parts needlessly
70. style / voice preservation across the whole paragraph

## Operations

Every source is tagged with one or more applicable operations:

- `paragraph_rewrite`
- `grammar_repair`
- `strength_15`
- `strength_40`
- `strength_60`
- `strength_90`
- `word_alternatives`
- `span_alternatives`
- `clause_alternatives`
- `sentence_alternatives`
- `simplify`
- `condense`
- `expand_no_new_facts`
- `more_conversational`
- `more_formal_bounded`
- `register_preserve`
- `split_sentence`
- `join_sentences`

Do not run nonsensical operations on every source simply to increase the count.

## Rewrite strength contract

Strength controls **surface distance**, not intelligence, formality, or vocabulary sophistication.

| Level | Intended behavior |
| --- | --- |
| ~15% | grammar cleanup + tiny lexical changes; preserve most wording |
| ~40% | local phrase replacements and light sentence reshaping |
| ~60% | substantial phrase/clause rewriting while preserving voice |
| ~90% | large surface/syntax change while preserving facts, meaning, and register |

A high-strength rewrite that merely swaps ordinary words for harder synonyms is a failure.

## Vocabulary / register ceiling

The benchmark explicitly penalizes vocabulary inflation.

Failures include:

- ordinary student prose becoming professor-like;
- casual writing becoming corporate or academic jargon;
- a simple source word being replaced only to sound sophisticated;
- sentence length and abstraction increasing without a clarity benefit;
- a model's stock transition phrases appearing repeatedly across unrelated inputs.

A model may simplify awkward wording, but it should not systematically raise the source's sophistication unless that transformation is explicitly requested.

## Interactive alternative contract

Span length is not conserved.

Valid transformations include:

- 1 word -> 1 word;
- 1 word -> 2–6 words;
- 2–8 words -> 1 word;
- phrase -> different-length phrase;
- clause -> clause;
- sentence -> sentence;
- one sentence -> two sentences;
- two sentences -> one sentence when meaning and readability permit.

The existing contextual synonym stack remains useful for single-token work, but it is only one generator inside the larger studio.

### Candidate pool

For a selected span, generators may create a large internal pool (for example 40–100 raw candidates). Pari then removes:

- duplicates / trivial punctuation variants;
- contradictions and meaning drift;
- broken grammar or morphology;
- polarity / modality / role flips;
- protected-content corruption;
- register mismatches;
- obviously awkward or low-value options.

Measure both:

- **top-10 precision** — first visible suggestions are routinely useful;
- **top-40 coverage/diversity** — deeper exploration still contains materially different valid wording.

Do not optimize only for one of these.

## Personalization evaluation

Personalization is a core product task, not an afterthought.

Only approved human choices may become positive preference data. Automatic model outputs are not style truth.

Track whether preference learning improves:

- chosen vocabulary;
- contraction use;
- sentence-length preference;
- preferred phrase structures;
- disliked stock phrases;
- degree of formality;
- ranking of alternatives;
- paragraph-level voice.

Personalization must never override factual, grammatical, protected-span, contradiction, negation, modality, quantity or role safety gates.

Evaluate cold-start and personalized modes separately.

## Model architecture benchmark: studio, not one giant LLM

A whole writing studio should not require the biggest generator for every click.

Benchmark multiple routes:

1. deterministic/rule path for trivial edits;
2. masked-LM / lexical models for single-word substitutions;
3. compact editing or seq2seq models for grammar/simplification where they win;
4. small quantized instruction model for phrase/clause/sentence generation;
5. larger teacher/reference model for difficult cases and offline data generation;
6. local safety/referee stack for every route.

Routing is allowed only when it beats a simpler always-on path in measured quality/latency/RAM.

## Compute tiers

### Tier 0 — eventual local shipping target

Primary target: 16-GB Apple-Silicon Mac.

Required measurements:

- model bytes on disk;
- quantization type;
- peak unified memory;
- cold start;
- warm first useful result;
- candidates/second;
- end-to-end top-10 alternative latency;
- paragraph rewrite latency;
- energy/thermal behavior during repeated use;
- ability to coexist with the rest of the studio.

A local model does not win merely because it fits. It must be pleasant enough for interactive use.

### Tier 1 — Kaggle quality-search / teacher tier

Available research budget: up to ~30 hours/week on 2x NVIDIA T4.

Use this tier for:

- larger model shootouts;
- Best-of-N candidate generation;
- teacher/reference outputs;
- quantization experiments;
- synthetic preference/candidate generation that will later be human-filtered;
- distillation experiments;
- difficult-case mining.

A Kaggle-only winner is useful as a teacher/reference, not automatically a shipping backend.

### Tier 2 — overflow training / conversion compute

Modal credits and Colab compute may be used for jobs that are awkward on Kaggle, including:

- conversion / quantization sweeps;
- LoRA experiments;
- distillation runs;
- batch embedding / scoring;
- evaluation jobs requiring a different GPU/runtime.

Results must record actual provider, GPU, runtime, cost/credits consumed, wall time and artifacts produced.

## Quantization protocol

For every promising generator, compare at minimum when runtime support exists:

- reference precision / best practical server precision;
- 8-bit;
- 6-bit or equivalent medium quant;
- 4-bit;
- sub-4-bit only when quality remains credible.

Do not assume smaller quantization is free. Measure:

- meaning errors;
- grammar degradation;
- alternative diversity collapse;
- repetition;
- vocabulary/register drift;
- latency;
- memory;
- candidate ranking changes.

The desired endpoint is the **smallest quantization whose user-visible quality is statistically indistinguishable or acceptably close to the best practical teacher on Pari's task matrix**.

## Teacher -> local path

The research loop is allowed to use models that are too large to ship:

```text
large teacher / Kaggle ceiling
  -> generate diverse candidate sets + difficult cases
  -> human selects / edits / approves
  -> retain approved preference data
  -> distill / fine-tune smaller model or ranker
  -> quantize
  -> re-run full benchmark
  -> ship only if local UX and safety survive
```

This lets current compute optimize quality first while preserving the long-term local goal.

## Required metrics

### Safety / meaning

- contradiction rate
- negation/modality/quantity/role failures
- protected-span corruption
- unsupported invention rate
- bidirectional entailment / NLI diagnostics where useful

### English quality

- grammaticality
- naturalness
- collocation quality
- coherence
- register match
- vocabulary inflation rate
- unnecessary-edit rate

### Interactive utility

- valid alternatives among top 10
- valid alternatives among top 40
- semantic diversity among valid choices
- duplicate rate
- span containment violations
- average number of materially distinct usable options
- time to first 5 / 10 / 40 usable options

### Strength calibration

Measure edit distance / structural difference monotonically across 15/40/60/90 while keeping meaning and register stable.

Higher strength should reliably increase surface change without increasing professor-like wording.

### Runtime

- peak RAM / VRAM
- model size
- cold/warm latency
- candidates/sec
- tokens/sec where meaningful
- energy/thermal notes locally
- compute cost for training/evaluation

## Human evaluation

Automatic metrics are filters and diagnostics, not the final stylistic authority.

Use blinded pairwise comparison for paragraph rewrites and blinded candidate-set evaluation for alternatives.

For alternative sets, human raters answer:

1. Does this preserve the selected meaning in context?
2. Is it grammatical in the resulting full sentence?
3. Does it sound natural?
4. Does it preserve the writer's approximate register?
5. Is it materially different from the other surviving options?
6. Would I actually consider using it?

## Reporting

Never collapse all v3 results into one number.

Report at least:

- safety veto table;
- paragraph quality table;
- interactive alternatives table;
- strength-calibration table;
- personalization cold vs personalized table;
- latency/RAM table;
- quality-vs-memory Pareto frontier;
- Kaggle ceiling vs local-shippable comparison.

## Promotion rules

### A generator may become a production route only if

1. no new hard-safety regressions appear;
2. its task-family human preference is competitive with the best practical alternative;
3. its register/vocabulary behavior matches the studio goal;
4. latency is appropriate for the operation it serves;
5. the route provides a measured benefit over the simpler route it replaces.

### A model may become the local general generator only if

1. it fits the target Mac together with the rest of the studio;
2. quantization does not cause unacceptable quality loss;
3. interactive latency is acceptable;
4. it performs well across phrase, clause, sentence and paragraph tasks;
5. a specialist/router combination does not dominate it on quality and cost.

## Non-goals

- deleting old work;
- maximizing paraphrase distance;
- making text sound more academic by default;
- treating generic intelligence benchmarks as product quality;
- requiring one LLM to perform every English operation;
- learning style from unapproved model output;
- claiming detector evasion as a quality metric.
