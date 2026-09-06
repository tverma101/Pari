# Pari paraphrasing quality roadmap

This is the working research and implementation plan for the active Pari quality goal. The priority is 80% language quality and 20% editing clarity.

## 80%: meaning-preserving English

Every candidate should pass these gates before it reaches the editor:

1. Preserve protected spans exactly: names, links, email addresses, dates, numbers, measurements, quoted text, and code-like fragments.
2. Preserve sentence count and the relationship between sentences: cause, result, contrast, condition, time, example, and addition.
3. Preserve negation, modality, tense, person, and the main argument roles unless the source explicitly changes them.
4. Reject grammar defects in generated output: article mismatch, subject/verb disagreement, quantifier-head agreement, malformed punctuation, comma splices, repeated words, broken verb frames, common forms such as “could of” and “alot,” run-ons, fragments, and mixed parallel lists. A source defect does not permit a candidate to introduce or retain a high-severity defect merely because it has the same issue label.
5. Prefer ordinary English collocations and known-to-new information flow over word-for-word synonym substitution.
6. Prefer a conservative original sentence over a broken rewrite. The safest output is always better than a more different but unreliable one.

The implementation order is sentence normalization, grammar linting, conservative repairs, candidate scoring, then broader lexical variety. Grammar linting is a validator and a fallback trigger; it must not rewrite arbitrary user prose without evidence.

Current shared implementation also includes a protected-span-aware English repair pass for high-confidence agreement, modal, article, pronoun-case, punctuation, and note-fragment errors. Citation abbreviations such as `et al. (2018)` are excluded from structural fragment joining, and the offline Harper signal guards both native and deterministic candidates when its local runtime is available. Open-ended rewrites remain model-driven; deterministic repairs are deliberately bounded.

## Multi-model editing system

Pari should be treated as an editing system in which specialized models compete, not as a single LLM plus rules. The production path remains conservative until a candidate stack wins the frozen evaluation suite.

For research, generate independent candidates when practical:

- **grammar specialist**: minimal corrections for agreement, articles, tense, prepositions, punctuation, malformed constructions, and other grammatical errors;
- **general rewrite model**: natural reconstruction, paraphrasing, sentence structure, flow, Warmth, and Personal-style behavior;
- **deterministic safe engine**: conservative fallback and high-confidence local repairs;
- **original text**: always remains a valid candidate when every rewrite is worse.

Candidate selection should reuse Pari's existing protection, grammar, semantic, discourse, and approval gates. A model does not get to bypass these gates because it is specialized.

A useful research pipeline is:

```text
input -> protected-span snapshot
      -> grammar-specialist candidate ----\
      -> conservative LLM candidate -------+-> shared candidate scorer -> final draft
      -> stronger LLM candidate -----------/
      -> deterministic/original fallback --/
```

The scorer should prioritize, in order: unsupported-invention rate, protected-span preservation, negation/modality/quantity safety, grammatical correctness, natural English/collocations, semantic preservation, requested rewrite strength, and learned style fit. “Changed more” is not a quality metric.

### Specialist shootout

Before fine-tuning a new Pari checkpoint, benchmark released editing/GEC systems against the current local controls. Initial research targets:

| Candidate | Approx. size | Intended role | Notes |
| --- | ---: | --- | --- |
| GECToR | ~355M | minimal grammar edits | Apache-2.0 implementation; useful as a fast correction specialist |
| DeCoGLM | ~335M | detect then locally correct | attractive architecture for avoiding whole-sentence over-rewrites |
| BART-family GEC | ~400M | grammar correction | benchmark representative checkpoints before choosing an implementation/license |
| CoEdIT-large | ~770M | grammar + coherence + paraphrase | strong conceptual fit; released checkpoints are research/non-commercial licensed, so do not silently promote into a distributable backend |
| Qwen3.5-4B | 4B | general rewrite control | current shootout control, not automatically the production backend |
| Ling-3.0-tiny | 7.9B total / 1.3B active | sparse general rewrite candidate | benchmark via the existing OpenAI-compatible local runner until runtime support is production-ready |

Do not promote a specialist from paper scores alone. Run the exact Pari fixtures and measure grammar, naturalness, reconstruction, meaning preservation, protected-span safety, latency, and peak memory on the target Mac.

If a small grammar specialist plus a general rewrite model materially beats the single-model path, keep the ensemble until there is evidence that distilling the combined behavior into one 1–4B local checkpoint preserves the quality advantage.

## 20%: editing and highlighting

The current editor already preserves manual text edits and offers word and sentence revert actions. The next UI pass should make the language state visible without adding a second editor model:

- changed words and phrases use one clear change treatment;
- grammar or flow warnings use a separate warning treatment;
- protected spans remain visually quiet and are never offered as synonym targets;
- the inline menu exposes the original, safe alternatives, sentence revert, and copy sentence actions;
- highlights must be rendered from text ranges, not brittle DOM mutation, so typing, paste, keyboard selection, and undo remain reliable.

## Resource policy

Pinned external resources live under `research/grammar-sources/` and are not bundled by Vite or copied into `public/`. Each snapshot has a source URL, pinned tag, license, intended use, download timestamp, and archive SHA-256. A resource can move into the shipped app only after a separate runtime, size, licensing, and installed-app verification decision.

## Evaluation plan

The local regression suite should grow in four directions:

- hand-written adversarial paraphrase fixtures for agreement, articles, punctuation, collocations, connectors, parallelism, and meaning;
- sentence-flow and discourse fixtures based on known/new information structure;
- a held-out natural-English corpus used for validator false-positive checks, with its license retained beside the fixture data;
- installed headless tests that prove a draft is generated, editable, context actions load, and missing optional model files produce an actionable fallback rather than a dead button.

Metrics should report safety rate, protected-span preservation, sentence-count preservation, newly introduced grammar issues, semantic similarity margin, average output length drift, candidate win rate by error class, peak memory, and latency. “Changed more” is not a quality metric.
