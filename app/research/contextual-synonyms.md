# Contextual synonym / lexical-substitution direction

Pari's inline word chooser is not intended to be a thesaurus. Its product goal is:

> Given a word in an actual sentence, offer a small set of replacements that preserve the sentence's intended meaning and remain grammatical and natural in that exact context.

A dictionary relationship is only a source of candidates. It is not sufficient evidence that a word is a good replacement.

## Current production direction

The active implementation uses the existing local stack:

1. deterministic phrase/synonym bank;
2. WordNet/thesaurus candidate generation;
3. local DistilBERT and DistilRoBERTa masked-language-model candidates;
4. ConCat-style context anchoring for MLM generation: the untouched sentence is supplied alongside a second copy with the selected word masked;
5. whole-sentence semantic reranking with the bundled `Xenova/paraphrase-MiniLM-L6-v2` encoder;
6. existing POS, article, grammar, duplicate-word, specificity, risk, and preference-memory ranking before display.

The semantic ranker is optional. If it cannot load, the chooser must continue to work with the deterministic/rule-ranked candidate set.

## Why original + masked context

Research: **Lexical Substitution is not Synonym Substitution: On the Importance of Producing Contextually Relevant Word Substitutes** (ICAART 2025).

Code: https://github.com/sebischair/ConCat

ConCat keeps the original sentence as a meaning anchor and pairs it with the masked sentence rather than asking a masked language model to infer the target only from the hole. Its implementation also filters antonyms and incompatible morphological forms and evaluates candidate fit using contextual representations.

The public ConCat repository is MIT licensed. Pari does not copy its Python runtime; the relevant architecture is implemented with Pari's already-bundled browser models.

## Smart Word Suggestions benchmark

Microsoft's **Smart Word Suggestions** task is a closer evaluation target than ordinary synonym datasets because it asks for useful replacements in context rather than exhaustive dictionary synonyms.

Repository: https://github.com/microsoft/SmartWordSuggestions

Paper/project: https://www.microsoft.com/en-us/research/publication/smart-word-suggestions-for-writing-assistance/

The Microsoft repository is MIT licensed. The dataset is useful as a research/evaluation source; verify the dataset's own terms before redistributing any derived fixture corpus.

## 2025 learned ranking follow-up

**Learning to Substitute Words with Model-based Score Ranking** (NAACL 2025) trains a BERT-based substitution system using model-based preference/ranking objectives over Smart Word Suggestions data.

Paper: https://aclanthology.org/2025.naacl-long.576/

Reference implementation: https://github.com/Hyfred/Substitute-Words-with-Ranking

Important shipping constraint: the reference GitHub repository currently declares no repository license. Treat the code and released weights as research/reference material only unless licensing is clarified. The general idea—learn or compute a contextual quality ranking over generated substitutions—is safe to reproduce independently.

## Product rules

- Keep the original word available in the popup.
- Keep sentence revert available.
- Prefer 6-10 excellent visible choices over dozens of weak thesaurus entries; broader candidate pools are for internal ranking.
- Preserve part of speech and inflection unless a phrase-level substitution intentionally changes the local syntax and passes grammar checks.
- Filter antonyms and polarity reversals aggressively.
- Do not promote a candidate solely because its embedding similarity is high; grammar/collocation rules remain independent gates.
- Score the full substituted sentence, not only target-word similarity.
- Phrase substitutions are legitimate when the selected span is a phrase; do not force single-word replacement for idioms/collocations.
- User approvals/reverts may influence ordering, but must not override grammar or meaning safety.

## Evaluation priorities

For inline substitutions, weight quality in this order:

1. contextual sense / naturalness;
2. meaning preservation;
3. grammatical compatibility and inflection;
4. usefulness / variety;
5. raw lexical distance from the original.

A candidate that is technically a synonym but makes the sentence strange is a failure.
