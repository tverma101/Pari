# Pari English Core — base-LLM selection benchmark

This benchmark answers a narrower question than the normal Pari acceptance suite:

> Which candidate model has the strongest underlying English competence for Pari's rewriting/editing workload?

It deliberately excludes coding, math, tool use, factual knowledge, agent performance and most generic reasoning. Those capabilities can make a modern LLM look strong while telling us very little about whether it understands word sense, collocation, natural phrasing or register.

The machine-readable definition is `english-core-config.json`. Fresh Pari-authored shadow cases are in `english-core-shadow.seed.json`.

---

## 1. English Core score

For **base-LLM selection only**, one weighted composite is allowed:

| Dimension | Weight |
| --- | ---: |
| contextual lexical meaning / word association | 25 |
| collocation and natural lexical choice | 20 |
| grammar / syntax | 15 |
| paraphrase semantics | 15 |
| fluency / register | 10 |
| generative expression | 10 |
| discourse relations | 5 |
| **Total** | **100** |

Always publish the seven subscores next to the composite. The composite is never allowed to replace the route-specific Pari product benchmark.

A model can therefore be the strongest English base model and still lose the final product decision because it is too slow, too large, unsafe after quantization, or worse than a specialist on a particular route.

---

## 2. Dimension A — contextual lexical meaning / word association (25%)

This is the most important dimension for Pari.

Public anchors:

- **SWORDS** — contextual lexical substitution with high-coverage human judgments: https://aclanthology.org/2021.naacl-main.345/
- **WiC** — tests whether a word has the same sense in two contexts: https://aclanthology.org/N19-1128/
- **CoInCo / SemEval lexical substitution** where a clean evaluation package is available.

Measure:

- word-sense discrimination;
- context-valid substitution;
- target meaning preservation;
- human-reference recall at 10 and 40 candidates;
- usable-candidate rate at 10 and 40;
- candidate ranking quality.

Example:

`Sales showed a sharp decline in August.`

Target: `sharp`

Correct contextual replacement: `steep`

Wrong senses such as `pointed`, `loud` or `sweet` should not receive credit simply because they are valid meanings of the word elsewhere.

---

## 3. Dimension B — collocation and natural lexical choice (20%)

A model must know not only that words are semantically related, but which combinations English speakers actually use.

Public anchor:

- **Evaluating language models for the retrieval and categorization of lexical collocations** (EACL 2021): https://aclanthology.org/2021.eacl-main.120/

Fresh Pari shadow cases cover adjective+noun, verb+noun, adverb+adjective and preposition compatibility.

Examples:

- `heavy rain` > `strong rain`
- `make a decision` > `perform a decision`
- `deeply concerned` > `heavily concerned`
- `draw a conclusion` > `pull a conclusion`

This dimension is intentionally large because thesaurus-like systems often know that two words are related while still producing English that sounds wrong.

---

## 4. Dimension C — grammar / syntax (15%)

Public anchors:

- **BLiMP** — 67 linguistic phenomena with 1,000 minimal pairs each: https://aclanthology.org/2020.tacl-1.25/
- **CoLA** — 10,657 acceptability examples from linguistics literature: https://aclanthology.org/Q19-1040/

Measure direct acceptability preference without asking the model to explain itself.

Example:

A. `The collection of old photographs was damaged.`

B. `The collection of old photographs were damaged.`

Expected answer: A.

Where local runtimes expose reliable logits, record the probability margin in addition to forced-choice accuracy.

---

## 5. Dimension D — paraphrase semantics (15%)

Public anchors:

- **PAWS** for high-overlap adversarial paraphrase pairs;
- existing Pari semantic-adversarial cases.

Fresh shadow cases test:

- actor/patient reversal;
- causal reversal;
- negation;
- modality/certainty;
- quantity;
- temporal order;
- comparison;
- focus/scope.

Example:

A. `Jordan sent Alex the document.`

B. `Alex sent Jordan the document.`

The lexical overlap is almost perfect, but the meaning is different. A good English model must notice the role reversal.

---

## 6. Dimension E — fluency / register (10%)

Public anchors:

- **JFLEG** for human fluency correction;
- **GYAFC** for formality/style distinctions: https://aclanthology.org/N18-1012/
- Pari register and vocabulary-ceiling cases.

The goal is not to reward formality. It is to test whether the model understands the source register and can preserve it.

Example source:

`Honestly, the new layout is kind of annoying.`

Preferred:

`Honestly, the new layout is a little annoying.`

Do not reward:

`The revised interface produces considerable user dissatisfaction.`

Both are grammatical, but only the first preserves the original voice and intensity.

---

## 7. Dimension F — generative English expression (10%)

This is intentionally a minority of the English Core score.

Use:

- selected WritingBench style/language tasks as a secondary anchor;
- EQ-Bench Creative Writing diagnostics only as secondary evidence;
- fresh Pari span/sentence/paragraph generation cases as the primary product-shaped diagnostic.

Measure:

- semantic preservation;
- naturalness;
- structural diversity;
- register fit;
- stock-LLM phrase rate;
- unnecessary length inflation.

A model that writes impressive essays but performs poorly on lexical sense, collocation or register should not win English Core.

---

## 8. Dimension G — discourse relations (5%)

Public anchor:

- **BeDiscovER**, using a focused English subset only: https://aclanthology.org/2026.eacl-long.207/

The benchmark covers discourse markers, temporal reasoning, discourse relations, sentence ordering and dialogue discourse parsing. Pari only needs the subset relevant to editing existing prose.

Fresh shadow examples test:

- `if` versus `when`;
- cause versus contrast;
- concession;
- purpose;
- temporal order;
- sentence ordering.

---

## 9. Public anchors versus fresh shadow cases

Every dimension should report two result groups:

1. **public-anchor score** — established benchmark data;
2. **Pari shadow score** — newly authored cases testing the same linguistic abilities.

Do not merge the two until both are visible separately.

Why:

- public benchmarks may have appeared in modern pretraining corpora;
- a model may memorize benchmark surface patterns without possessing equally strong underlying language competence;
- fresh shadow cases let us test the same phenomenon with different wording.

Shadow cases are evaluation-only. Never train on them or tune prompts specifically against them. Rotate/add cases once repeated experimentation starts overfitting the file.

---

## 10. Prompting protocol

For forced-choice tasks, prefer the smallest possible instruction.

Example:

```text
Which sentence is more natural English?
A. She made a decision.
B. She performed a decision.
Answer only A or B.
```

Do **not** ask for explanations or chain-of-thought. We are measuring English competence, not verbosity or reasoning-style compliance.

For lexical generation:

```text
Sentence: The examples clarified the rule for me.
Selected text: clarified
Give up to 20 replacements that fit this exact sentence and preserve the intended meaning.
```

Preserve raw outputs and fixed decoding settings for every candidate model.

---

## 11. Interpreting results

Example profile:

| Model | Lexical | Collocation | Grammar | Semantics | Register | Generation | Discourse | Core |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 94 | 91 | 92 | 88 | 86 | 79 | 84 | 89.2 |
| B | 84 | 83 | 96 | 94 | 82 | 93 | 91 | 88.4 |
| C | 96 | 95 | 90 | 91 | 91 | 70 | 79 | 90.2 |

In this hypothetical result, C is the strongest underlying English model even though B is the better open-ended writer.

That distinction is exactly why English Core exists.

---

## 12. Final selection flow

1. Run English Core on all plausible base LLMs.
2. Keep the per-dimension profile and English Core composite.
3. Reject/flag models whose public-anchor strength does not reproduce on fresh shadow cases.
4. Only then compare quantizations, RAM, latency and MTP/speculation.
5. Run the existing Pari V1 route-specific benchmark on the surviving models.
6. Choose the shipping route/model based on the product Pareto frontier, not English Core alone.
