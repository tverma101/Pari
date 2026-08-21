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

Metrics should report safety rate, protected-span preservation, sentence-count preservation, newly introduced grammar issues, semantic similarity margin, and average output length drift. “Changed more” is not a quality metric.
