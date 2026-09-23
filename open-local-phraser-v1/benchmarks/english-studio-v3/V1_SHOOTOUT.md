# Pari V1 local-model shootout

This is the executable model-selection plan for V1.

V1 is a **human-controlled rewriting tool**, not an autonomous paraphraser. The model is valuable when it can quickly produce context-valid alternatives and a decent first-pass paragraph rewrite. The user remains responsible for the final wording.

## V1 decision target

Find the simplest local stack that satisfies all of the following on a 16-GB Apple-Silicon Mac:

- fast word/phrase alternatives;
- usable sentence alternatives;
- a decent paragraph first draft;
- no systematic vocabulary/formality inflation;
- meaning/fact preservation;
- 1-word -> many-word and many-word -> 1-word replacements;
- enough candidate diversity for the user to mix and choose;
- room in memory for the editor, filters, rankers and caches.

Do **not** select by one global benchmark score.

---

# 1. Candidates to benchmark first

## A. Existing Pari route

Keep the current production Qwen path and existing contextual synonym stack as the incumbent.

Purpose:

- measure whether new work actually improves the product;
- retain the cheap lexical route even if a new general generator wins.

## B. MiniCPM5-2B 4-bit

Why it is in the first sweep:

- very small local footprint;
- official Apple-Silicon MLX path exists;
- current independent LiteRT measurements show very high decode throughput on M4-class hardware;
- if its English is merely decent, it may be ideal for interactive phrase/sentence generation.

Question:

> Is 2B already good enough when the user is manually choosing and editing the result?

If yes, prefer it for the fast route even if a larger model wins paragraph quality.

## C. Qwen3.5-4B 4-bit

Why:

- Apache-2.0;
- current strong 4B baseline;
- already close to Pari's existing model family/runtime assumptions;
- large enough to test whether a modest size increase materially improves rewriting over 2B.

Question:

> Does 4B materially improve contextual suggestions and sentence rewrites enough to justify the extra latency/RAM?

## D. One non-Qwen 4–9B control

At least one non-Qwen family should be included so the project does not accidentally optimize around one family's prose habits.

Selection requirements:

- stable Mac runtime;
- <=16-GB realistic total application footprint at the tested quantization;
- permissive enough license for the intended local application;
- current general English capability.

This slot may change as the open-weight landscape changes. A candidate is a control, not a permanent dependency.

## E. Ternary Bonsai 2 27B

Why:

- based on Qwen3.8-27B;
- ~5.9-GB ternary model footprint;
- large-model capability at a local-sized weight footprint;
- direct test of whether aggressive model compression gives V1 noticeably better English without training.

Important:

- generic benchmark retention is **not** proof of writing quality;
- current Bonsai runtime is specialized;
- measure real Mac throughput, first-token latency, and whole-app memory;
- use it only if the actual rewriting advantage is visible.

Question:

> Does a compressed 27B produce sufficiently better alternatives than 2–9B models to justify its runtime complexity and latency?

---

# 2. MTP / speculative lane

MTP is tested as a runtime feature, not assumed as a model requirement.

Current landscape changes quickly:

- Qwen3.8 has a native MTP head;
- current llama.cpp/community runtimes can use Qwen3.8 MTP;
- a current Apple-Silicon runtime reports material speedups for supported Qwen MTP models, including a reported ~1.6x decode gain on a 16-GB M4;
- Bonsai 2's compact published pack does not include the original Qwen3.8 MTP block, although community work has demonstrated grafting the head back for speculative decoding on CUDA.

V1 procedure:

1. benchmark ordinary decoding;
2. benchmark an **existing** MTP/speculative implementation when available;
3. compare end-to-end candidate latency, not only tokens/sec;
4. record extra memory/runtime fragility;
5. drop MTP if the UX gain is small.

**Do not train a new MTP head for V1.**

Only revisit MTP training if:

- the chosen V1 model misses the latency target;
- no stable existing drafter/head works;
- profiling shows decode rather than candidate filtering/UI is the bottleneck;
- a small, bounded training experiment has a clear expected payoff.

---

# 3. Prompt modes to benchmark

Every general model must run the same product behaviors.

## Paragraph draft

Input: ordinary paragraph.

Output: one rewritten paragraph.

Rules:

- preserve facts and meaning;
- preserve approximate register;
- do not make simple prose academic by default;
- obey requested rewrite strength.

## Selected-span alternatives

Input:

- full surrounding sentence/paragraph;
- exact selected span;
- requested operation/strength.

Output:

- candidate replacements only;
- candidates may be shorter or longer than the selected span;
- unrelated text is not regenerated.

## Sentence alternatives

Input:

- selected sentence + local paragraph context.

Output:

- several structurally different sentence rewrites;
- preserve facts, polarity, modality and register.

The model must not receive a prompt that rewards sophistication or maximum lexical difference.

---

# 4. Fast acceptance suite

Use ~200 unique source cases for day-to-day model/runtime iteration.

Target composition:

| Route | Unique cases | Why |
| --- | ---: | --- |
| word/phrase alternatives | 60 | highest-priority V1 interaction |
| sentence alternatives | 35 | common manual rewrite unit |
| paragraph first draft | 35 | useful starting point, not final authority |
| safety/meaning traps | 30 | hard global gate |
| strength/register control | 25 | prevents professor/corporate drift |
| protected/edit-containment | 15 | verifies local-control contract |

Some cases may overlap routes, but report **unique source count separately** from task-instance count.

Use the expanded `interactive.seed.json` plus stratified cases from the existing Pari suites.

---

# 5. Release validation suite

Before changing the default route, run the broader suite:

## Existing Pari

- adversarial safety/regression corpus;
- frozen QuillBot hard-tail corpus;
- standards-traced paraphrase-v2;
- English Studio interactive cases.

## Independent external references

- Smart Word Suggestions human test set for contextual substitutions;
- TSAR for lexical suggestion ranking;
- JFLEG for grammar/fluency;
- IteraTeR held-out revisions for human-edit behavior;
- EditEval relevant editing tasks;
- PAWS meaning/order traps;
- ASSET only for simplification/compression/split-join routes where relevant.

## Writing screens only

WritingBench/Arena/creative-writing boards may identify interesting model families or teachers, but they are **not V1 pass/fail gates**.

---

# 6. Route-specific metrics

## Word/phrase alternatives — highest weight

Record:

- valid top-3/top-5/top-10 coverage when references exist;
- top-10 grammaticality in full context;
- meaning preservation;
- candidate duplicate rate;
- materially different valid candidate count;
- shorter/same/longer replacement distribution;
- time to first 3 suggestions;
- time to first 10 suggestions;
- peak memory.

For V1 the first **5 useful options** matter more than producing 40 mediocre ones immediately. Deeper candidates may stream progressively.

## Sentence alternatives

Record:

- meaning preservation;
- grammar/naturalness;
- register drift;
- structural diversity;
- sentence-length inflation;
- latency to first usable batch.

## Paragraph draft

Record:

- factual/semantic safety;
- coherence;
- vocabulary/formality inflation;
- strength response;
- unnecessary edit rate;
- latency.

## Runtime

Record on the target Mac:

- model size on disk;
- resident/peak unified memory;
- cold load time;
- prefill;
- decode;
- first useful result;
- top-10 candidate latency;
- paragraph latency;
- stability after repeated interactions.

---

# 7. Hard vetoes

A candidate cannot be used for a route if it frequently:

- changes names, dates, quantities, links or quoted text;
- flips negation/modality;
- reverses subject/object roles;
- invents reasons/evidence/events;
- changes unrelated text outside the selected span;
- produces grammatically broken replacements after insertion.

A model can lose one route and still win another.

---

# 8. V1 routing decisions

Possible valid final stacks include:

## Small-first

```text
contextual lexical route
+ MiniCPM5-2B or 4B generator
+ safety/grammar filters
```

Choose if 2–4B output is already good enough.

## Split fast / hard

```text
lexical + small model for most clicks
+ Bonsai 2 only for sentence/paragraph or retry
```

Choose only if the larger low-bit model gives a clear quality gain on hard operations.

## Large-low-bit general route

```text
lexical specialist
+ Bonsai 2 for phrase/sentence/paragraph generation
```

Choose only if it remains interactive and leaves adequate whole-app RAM.

Do not add routing complexity unless the benchmark shows a real benefit.

---

# 9. V1 stopping rule

Stop model hunting when a stack satisfies all of these:

- the first paragraph draft is consistently usable as a starting point;
- word/phrase clicks produce several sensible choices quickly;
- sentence alternatives are usable;
- the user can make 1->many and many->1 edits naturally;
- no systematic academic vocabulary inflation;
- safety gates are stable;
- the whole app fits 16 GB;
- another model's quality gain is too small to justify its latency/RAM/runtime complexity.

At that point, spend effort on **interaction UX and preference logging**, not another general-model benchmark.

---

# 10. Post-V1

Only after V1 is used enough to collect real preference events should Pari consider training.

First train a small **ranking/personalization layer** on the user's choices among objectively valid candidates.

Generator fine-tuning/distillation remains optional and requires evidence that ranking alone cannot capture the preference gap.
