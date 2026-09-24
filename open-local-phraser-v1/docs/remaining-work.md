# Pari remaining work — V1 execution index

**Updated:** 2026-09-23

The old paragraph-first quality roadmap in this file has been superseded by the English Studio V1 plan.

Do not use historical versions of this document as the current product contract.

## Current product target

Pari V1 is a **fast, local, human-controlled rewriting studio**, not an autonomous paraphraser.

```text
paste paragraph
  -> optional rewrite-strength draft
  -> select word / phrase / clause / sentence
  -> get fast context-aware alternatives
  -> choose / mix / type / undo / revert
```

The first whole-paragraph rewrite only needs to be a useful starting point. The main V1 value is interactive control over wording.

Replacement length is free:

- 1 word -> 1 word;
- 1 word -> many words;
- many words -> 1 word;
- phrase -> phrase;
- clause -> clause;
- sentence -> sentence;
- split/join where safe.

V1 must not systematically turn ordinary writing into academic/corporate prose.

## V1 training rule

**No paraphraser training for V1.**

Do not spend the V1 critical path on:

- generator fine-tuning;
- teacher/student distillation;
- synthetic training-corpus creation;
- training a new MTP head.

Allowed V1 research:

- local model/runtime shootouts;
- direct quantization comparisons;
- native aggressive-low-bit model experiments;
- existing MTP/speculative runtime experiments;
- benchmark/evaluator work;
- UI/candidate-routing work.

Post-V1 personalization begins with a small preference/ranking layer trained from real user choices among objectively valid suggestions.

## Canonical docs

Use these files under `benchmarks/english-studio-v3/`:

- `PROJECT_PLAN.md` — product and architecture decisions;
- `V1_SHOOTOUT.md` — V1 model/runtime experiment;
- `README.md` — benchmark design;
- `BENCHMARK_MODEL_MAP.md` — route-specific benchmark/model mapping;
- `v1-candidates.json` — pinned candidate roster;
- `v1-suite-config.json` — fast-suite target layout;
- `v1-result-schema.json` — reproducible result format;
- `v1-prompt-contracts.json` — model-agnostic generation behavior;
- `dataset-ledger.json` — dataset provenance and train/eval policy;
- `interactive.seed.json` — product-specific interactive acceptance cases;
- `build-v1-core.mjs` — deterministic internal V1 core builder;
- `build-composite.mjs` — broader release/research composite builder.

## Issue map

- **#13** — V1 EPIC / canonical project checklist.
- **#14** — primary editor implementation: arbitrary span selection and fast alternatives.
- **#15** — model/runtime registry cleanup so benchmarks load the model they claim to load.
- **#10** — V1 model/runtime shootout.
- **#7** — objective candidate validation/ranking gates.
- **#11** — broad release validation.
- **#8** — QuillBot paragraph comparison as a secondary report.
- **#6** — closed as superseded; Ling research retained historically.

## Execution order

### Phase A — make experimentation reliable

1. #15: resolve exact production checkpoint and remove ambiguous hard-coded fallback behavior.
2. Build the V1 fast suite and result capture around the new registry.
3. Preserve raw outputs so evaluator/ranker changes can be replayed without regeneration.

### Phase B — build the actual product interaction

1. #14: arbitrary span selection.
2. 1->many / many->1 replacement support.
3. clause/sentence alternatives.
4. direct typing, undo and revert.
5. progressive candidate loading.
6. protected-content-safe insertion.

This can proceed in parallel with the first model shootout.

### Phase C — choose the simplest good-enough local generation stack

Run #10 against the pinned candidate roster.

Required first sweep:

1. current Pari incumbent;
2. MiniCPM5-2B MLX 4-bit;
3. Qwen3.5-4B MLX 4-bit;
4. Ministral 3 8B Q4_K_M as the first non-Qwen control;
5. Ternary Bonsai 2 27B as the aggressive-low-bit large-model experiment.

Ling-3.0-tiny is optional after the required core sweep.

Choose by route-specific quality/latency/memory Pareto results, not one intelligence score.

### Phase D — candidate validity and ranking

Use #7 to combine:

```text
protected anchors
-> negation/modality/role/quantity checks
-> grammar in the resulting full sentence
-> semantic contradiction gate
-> dedupe/diversity
-> register/vocabulary-drift checks
-> contextual ranking
```

Keep the stack cheap enough for interactive use. Remove expensive judges that do not measurably reduce real errors.

### Phase E — release validation

Run #11 after a candidate stack looks good on the V1 fast suite.

Use route-relevant external human/reference benchmarks plus all old Pari regressions.

Do not collapse the report to one `Pari score`.

### Phase F — comparison/reporting

Run #8 for QuillBot overlap on paragraph-first-draft behavior.

Do not use QuillBot head-to-head as the definition of the whole product because it does not measure Pari's interactive word/phrase/sentence control.

## V1 ready when

- a pasted paragraph receives a safe, usable starting rewrite;
- selected words/phrases quickly receive several sensible alternatives;
- shorter and longer replacements work naturally;
- sentence alternatives are useful;
- user can mix, type, undo and revert without unrelated text mutating;
- protected facts remain exact;
- simple writing is not systematically inflated into academic language;
- whole app fits and behaves acceptably on the target 16-GB Mac;
- another model's gain is too small to justify its extra RAM/latency/runtime complexity;
- no paraphraser training was required.

## Post-V1

Collect real local interaction events for personalization:

```text
source context
selected span
candidate set shown
candidate chosen
candidate ignored/reverted
manual replacement
final approved text if approval is used
strength/action type
```

Objective quality gates remain authoritative for correctness. User behavior only teaches preference among valid expressions.

Start with preference-memory/ranking. Fine-tune the generator only if real usage later proves ranking is insufficient.
