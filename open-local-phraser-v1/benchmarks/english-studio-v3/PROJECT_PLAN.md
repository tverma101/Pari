# Pari English Studio v3 — canonical project plan

## V1 decision

**V1 is a zero-training product.**

Do not fine-tune the paraphraser for V1. Do not distill a teacher for V1. Do not build a large synthetic training corpus for V1.

The only training-like experiments allowed before V1 are narrowly scoped runtime experiments such as an MTP/speculative drafter **if** they measurably improve latency on the target Mac. Quantization experiments are allowed because they directly affect whether a good model can run locally.

The reason is simple: Pari V1 is not trying to autonomously write the perfect paragraph. It is a **human-controlled rewriting tool**. The model only needs to be good enough to generate sensible, diverse options quickly while the user decides the final wording.

---

# 1. V1 product contract

```text
paste paragraph
  -> choose rewrite strength
  -> receive one decent editable draft
  -> click/select word / phrase / clause / sentence
  -> receive fast context-aware alternatives
  -> choose / mix / type / undo / revert
  -> continue until the wording feels right
```

Required V1 behavior:

- preserve meaning and protected facts;
- avoid automatically making the prose more academic or formal;
- allow low/high rewrite-strength modes;
- allow 1 word -> many words;
- allow many words -> 1 word;
- allow phrase -> phrase, clause -> clause, sentence -> sentence;
- allow sentence shortening, expansion, split and join;
- provide many alternatives, not one machine-selected answer;
- keep unrelated surrounding text stable;
- make word/phrase suggestions quickly enough to feel interactive;
- let the user remain the final stylistic authority.

The initial whole-paragraph rewrite only needs to be **decent**. The interactive toolbox is the actual product.

---

# 2. V1 architecture

Do not require one model to do everything.

```text
cheap lexical/contextual candidates -----------\
phrase/span generator --------------------------+\
sentence/paragraph generator -------------------+--> safety + grammar + meaning filters
retrieved human-edit patterns ------------------+/             |
                                                             dedupe/diversity
                                                                   |
                                                             ranking + UI
```

For trivial word substitutions, the existing contextual synonym stack remains useful.

For phrase/clause/sentence alternatives, use a small/medium local generative model.

For the paragraph rewrite, use the same model unless a larger low-bit model is clearly better and still fast enough.

The general model does not need to generate all 40 displayed options by itself. Candidate pools can combine:

- masked-LM/contextual lexical suggestions;
- phrase banks / human-edit retrieval;
- generative candidates;
- deterministic transformations;
- later, personalized ranking.

---

# 3. V1 model selection: speed + decent English + local fit

V1 should choose the model by the actual studio workload, not by general intelligence benchmarks.

## Candidate class A — very small / fast

Examples:

- MiniCPM5-2B 4-bit MLX (~1.4 GB);
- other current 2–4B local instruction models with stable MLX/GGUF support.

Role:

- fast phrase/sentence alternatives;
- potentially paragraph rewrite if quality is acceptable;
- excellent baseline because latency and memory are cheap.

## Candidate class B — 4–9B local models

Role:

- likely quality/speed sweet spot if 2B alternatives are too weak;
- benchmark 4-bit and, where useful, 3-bit builds;
- keep only if the improvement is noticeable on Pari tasks.

## Candidate class C — Bonsai / aggressive low-bit large models

Bonsai 2 27B is especially interesting because it compresses Qwen3.8-27B to roughly 5.9 GB in its ternary representation while retaining most generic benchmark capability.

For V1 this is a **direct inference experiment**, not a training target.

Question:

> Does Bonsai 2 produce materially better phrase/sentence/paragraph alternatives than the 2–9B candidates while still being interactive on the Mac?

If yes, use it for the harder generation route. If no, the smaller model wins.

Do not infer writing quality from Bonsai's math/coding/reasoning benchmark retention. Test writing directly.

---

# 4. MTP / speculative decoding decision

MTP is optional acceleration, not a V1 requirement.

Current evidence:

- Qwen3.8-27B has native MTP support in its original architecture/runtime ecosystem;
- Bonsai 2's published ternary pack does not simply expose that original MTP block in the same way;
- community work has grafted the Qwen3.8 MTP head back onto Bonsai 2 for lossless speculative decoding;
- PrismML's own documentation says speculative decoding helps much more on CUDA and can be a net slowdown for ordinary chat/reasoning on Apple Silicon.

Therefore:

1. benchmark normal decode first;
2. benchmark any existing MTP/speculative path second;
3. **do not train a new MTP head unless normal decode fails the latency target and the experiment has a plausible Mac payoff**;
4. if MTP adds complexity without clear Mac speedup, drop it for V1.

The V1 optimization priority is:

```text
better base model / quantization
    > candidate routing
    > caching / streaming
    > speculative/MTP training
```

---

# 5. Quantization policy

Quantization is a V1 priority because it can directly unlock a stronger model locally.

For ordinary models test:

```text
reference -> Q8 -> Q6 -> Q4 -> Q3
```

For specialized low-bit releases such as Bonsai, test the provided native format directly.

Do not assume an arbitrary model can be turned into a Bonsai-quality 1.5-bit model by ordinary post-training quantization.

Measure for each build:

- meaning failures;
- grammar/naturalness;
- word/phrase suggestion quality;
- candidate diversity;
- paragraph quality;
- time to first suggestion;
- time to top-10 suggestions;
- memory;
- app stability.

Choose the smallest format that keeps V1 quality acceptable.

---

# 6. V1 benchmark philosophy

V1 does **not** need a giant academic benchmark leaderboard. It needs a compact but versatile acceptance suite that reflects the actual UI.

Models receive capability profiles instead of one rank.

Core V1 routes:

1. **word/phrase alternatives** — highest priority;
2. **sentence alternatives** — high priority;
3. **paragraph first draft** — medium priority;
4. **grammar/meaning safety** — mandatory gate;
5. **rewrite-strength control** — mandatory UX behavior;
6. **runtime/latency** — mandatory local gate.

A model that is weak at an unrelated benchmark is not eliminated if it is excellent at its assigned route.

Detailed benchmark mapping lives in `BENCHMARK_MODEL_MAP.md`.

---

# 7. V1 acceptance suite

Use a **small, representative subset** for fast iteration, plus the larger suites for release validation.

## Fast development set

Target roughly 150–250 unique cases total:

- 40–60 word/phrase alternative cases;
- 30–40 sentence rewrite cases;
- 30–40 paragraph rewrite cases;
- 20–30 hard meaning/safety traps;
- 20–30 rewrite-strength/register cases.

Each case can produce several candidate/ranking measurements, but unique-source count is reported separately.

## Release validation

Run the relevant independent and existing suites:

- Smart Word Suggestions;
- TSAR lexical simplification;
- JFLEG;
- IteraTeR held-out subset;
- EditEval relevant tasks;
- PAWS semantic traps;
- existing Pari adversarial / QuillBot / paraphrase-v2 suites.

ASSET is useful for compression/simplification but is not a pass/fail gate for every model route.

WritingBench/Arena writing categories are only teacher/model-screening signals, not production gates.

---

# 8. V1 scoring

## Word/phrase route

Measure:

- top-3 / top-5 / top-10 useful alternative coverage where references exist;
- top-10 validity;
- duplicate rate;
- grammar after replacement;
- meaning preservation;
- replacement-length variety;
- time to first 5 / 10 suggestions.

This is the most important V1 score family.

## Sentence route

Measure:

- meaning preservation;
- naturalness/grammar;
- register drift;
- structural diversity;
- local containment;
- latency.

## Paragraph route

Measure:

- meaning/factual safety;
- coherence;
- vocabulary/formality inflation;
- rewrite-strength responsiveness;
- latency.

The paragraph generator does not need to beat every proprietary writing model. It needs to provide a useful starting point for the interactive editor.

---

# 9. Human-sounding definition for V1

Do not use AI-detector probability as the target.

For V1, "human sounding" means:

- normal/common English rather than unnecessary thesaurus words;
- grammar that fits the surrounding sentence;
- source register roughly preserved;
- no repeated generic transition/filler patterns;
- multiple plausible ways to express the same meaning;
- sentence structures that are not needlessly inflated;
- no automatic professor/corporate tone unless requested.

The user can then manually choose or mix options.

---

# 10. No-training rule for V1

Do not spend Kaggle/Modal/Colab time training the paraphrase model for V1.

Use compute for:

- model shootouts;
- quantization experiments;
- candidate-generation stress tests;
- MTP/speculative benchmark experiments;
- runtime profiling;
- large batch benchmark runs.

Training data research remains documented for post-V1, but it is not on the V1 critical path.

---

# 11. Post-V1 personalization

After V1 is genuinely useful, begin collecting interaction data:

```text
source context
selected span
candidate set shown
candidate chosen
candidate reverted/ignored
manual replacement
final approved paragraph
rewrite strength
```

The first personalization system should be a **small ranking layer**, not generator fine-tuning.

It learns:

- words the user frequently changes;
- words the user usually keeps;
- preferred expansions/compressions;
- sentence-length preferences;
- formality;
- contractions;
- favored phrases;
- disliked suggestions.

Only later, if ranking is insufficient and enough private data exists, consider LoRA/fine-tuning on the user's own behavior.

That is the point where training becomes justified because it optimizes for the actual user's preference rather than generic synthetic style.

---

# 12. V1 experiment order

## P0 — benchmark current local models

Benchmark at least:

- MiniCPM5-2B 4-bit MLX;
- current Pari Qwen path;
- a strong current 4B candidate;
- a 7–9B candidate if it fits comfortably;
- Bonsai 2 27B native low-bit path;
- existing lexical/contextual synonym route.

Output a route-by-route Pareto table: quality, memory, latency.

## P1 — build the actual interactive editor

- arbitrary span selection;
- word/phrase/clause/sentence actions;
- 1->many and many->1 replacement support;
- top suggestions + deeper alternatives;
- undo/revert;
- local edit containment;
- progressive candidate streaming.

## P2 — choose V1 model/router

Pick the simplest route that is good enough:

- small model only;
- small model + lexical specialist;
- small model + Bonsai for difficult cases;
- Bonsai as general generator + cheap lexical route.

## P3 — quantization/runtime polish

- test lower-bit builds;
- benchmark caching and batched candidate generation;
- test speculative/MTP only if normal decode misses latency target;
- validate packaged Mac app.

## P4 — ship V1

No personalization training required.

## P5 — collect preference data

After real use, add local preference ranking and only then revisit training.

---

# 13. V1 success condition

Pari V1 is ready when:

- a pasted paragraph gets a decent, meaning-safe rewrite;
- selecting a word or phrase quickly produces several sensible alternatives;
- replacements can freely change length;
- sentence alternatives are usable and reasonably fast;
- the user can mix/edit/revert everything;
- the model does not systematically inflate vocabulary/formality;
- the whole system fits and behaves acceptably on the target 16-GB Mac;
- no model training was required to reach this baseline.
