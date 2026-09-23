# Pari English Core — human evaluation protocol

This protocol separates two different jobs that must not be conflated:

1. **shadow-label validation** — checking whether supposedly objective gold labels are clear and defensible;
2. **generative-output evaluation** — comparing natural rewrites/alternatives where multiple outputs can legitimately be good.

The distinction matters because categorical linguistic labels and subjective language-quality preferences have different notions of disagreement and reliability.

## Research basis

Primary methodology references:

- van der Lee et al. (INLG 2019), *Best practices for the human evaluation of automatically generated text*: https://aclanthology.org/W19-8643/
- Belz, Mille & Howcroft (INLG 2020), *Disentangling the Properties of Human Evaluation Methods*: https://aclanthology.org/2020.inlg-1.24/
- Oortwijn, Ossenkoppele & Betti (HumEval 2021), *Interrater Disagreement Resolution*: https://aclanthology.org/2021.humeval-1.15/
- Hämäläinen & Alnajjar (HumEval 2021), *The Great Misalignment Problem in Human Evaluation of NLP Methods*: https://aclanthology.org/2021.humeval-1.8/
- Amidei, Piwek & Willis (COLING 2018), *Rethinking the Agreement in Human Evaluation Tasks*: https://aclanthology.org/C18-1281/
- Mohankumar & Khapra (ACL 2022), *Active Evaluation: Efficient NLG Evaluation with Few Pairwise Comparisons*: https://aclanthology.org/2022.acl-long.600/
- Elangovan et al. (ACL 2024), *ConSiDERS-The-Human Evaluation Framework*: https://aclanthology.org/2024.acl-long.63/
- Song et al. (ACL 2025), *Enhancing Human Evaluation in Machine Translation with Comparative Judgement*: https://aclanthology.org/2025.acl-long.1002/

## A. Independent shadow-label validation

### Purpose

Validate the author-written forced-choice labels before treating the shadow set as externally validated evidence.

This is different from asking which model output someone likes.

### Annotators

Use multiple independent annotators with strong English proficiency. Record:

- self-reported English proficiency / language background relevant to the task;
- whether the annotator has linguistics/editing expertise where applicable;
- any exclusion criteria chosen **before** inspecting model results.

Do not use the project owner as the sole gold-label authority.

### Blinding

Annotators must not see:

- model names;
- model outputs;
- benchmark/model rankings;
- the author's proposed answer;
- which items previously caused model errors.

The validation form should show only the linguistic item and answer options.

### Item-level response

For each forced-choice item, collect:

1. selected answer;
2. confidence on a small ordinal scale;
3. `ambiguous / more than one answer defensible` flag;
4. optional short rationale for flagged items.

Do not force annotators to choose a gold answer when they believe the item is genuinely ambiguous.

### Agreement and disagreement

Report:

- raw answer distributions per item;
- percent agreement;
- an agreement/reliability statistic appropriate to the label type and missing/abstain behavior;
- confidence intervals where practical;
- the number/rate of ambiguous-item flags.

Agreement should not be interpreted from one universal folklore threshold. Language judgments can contain legitimate variability, and reliability statistics have assumptions that must be stated.

### Adjudication

For objective-label tasks (grammar, sense identity, explicit semantic relation), disagreement is evidence that the item or instructions may be unclear.

Procedure:

1. freeze independent judgments;
2. identify disagreements/ambiguity flags;
3. review the item without model results;
4. clarify wording or remove the item when a unique gold answer cannot be defended;
5. record the original responses and the adjudication decision;
6. increment the shadow-set version when labels/items change.

Never change a gold label because a preferred model chose another answer.

### Minimum validity rule

Until this process is completed, `english-core-shadow.seed.json` remains labeled `author_labeled_unvalidated` and supports internal/transfer diagnostics only.

## B. Generative-output human evaluation

### Purpose

Evaluate contextual alternatives, sentence rewrites, paragraph revisions, and split/join outputs where there can be many correct/natural answers.

Here, disagreement can reflect legitimate human preference. Do not force consensus merely to create a cleaner number.

### Evaluation mode

Prefer **pairwise/comparative judgment** for close model selection when the criterion supports comparison. Pairwise evaluation has substantial precedent in NLG evaluation and can be easier and more discriminative than absolute scalar scoring.

For each source item, compare outputs from two systems under randomized order:

- A better;
- B better;
- tied / equally acceptable;
- both unacceptable, where relevant.

Keep criterion-specific judgments separate rather than asking for one vague `overall quality` score.

### Criteria

For Pari, primary criteria are:

1. **meaning preservation** — facts, roles, negation, modality, quantities, conditions, and discourse relations survive;
2. **contextual naturalness** — fluent, idiomatic English in the given context;
3. **register preservation** — source formality/intensity/voice remains appropriate unless change was requested;
4. **edit usefulness** — output is a genuinely usable alternative, not a near-duplicate or irrelevant variation;
5. **structural/lexical diversity** when a set of alternatives is being judged;
6. **unnecessary inflation** — avoid gratuitous length, abstraction, formality, or rare vocabulary.

Do not combine these into one score until the individual judgments are preserved.

### Experimental controls

- blind model identity;
- randomize A/B output order independently per item/annotator;
- randomize item order;
- keep source context visible;
- keep instructions/rubrics identical across systems;
- do not expose latency/model size during linguistic quality rating;
- preserve ties rather than forcing a winner;
- separate quality evaluation from personal style preference;
- do not let the model under test write or grade its own rubric responses.

### Raters

Use multiple independent raters for promotion-quality conclusions. Preserve anonymous rater IDs so rater effects and consistency can be inspected without exposing personal identity.

### Reporting

Report at least:

- raw pairwise counts: A wins / ties / B wins / both unacceptable where used;
- per-criterion pairwise results;
- rater count and annotations per item;
- uncertainty intervals / paired statistical analysis;
- agreement/reliability diagnostics with stated assumptions;
- disagreement rate and examples of high-disagreement items;
- exact rubric/instructions;
- randomization/blinding procedure;
- exclusions and adjudication procedure;
- raw anonymized ratings where privacy/license allows.

Do not collapse disagreement into a hidden adjudicated score for subjective criteria.

## C. User preference is a different signal

The Pari owner/user's choices are valuable **personalization labels**, not objective English-correctness gold.

Post-V1 user interactions may teach:

- preferred wording;
- preferred register;
- desired brevity;
- preferred candidate rank.

They must not overwrite objective grammar/meaning validity labels simply because the user chose a different style.

## D. Human-evaluation preregistration / freeze rule

Before showing final candidate-model outputs to raters, freeze and archive:

- test item version/hash;
- model IDs/revisions;
- output files/hashes;
- rubric;
- pair-generation/randomization seed;
- rater eligibility rules;
- primary criteria;
- analysis plan;
- exclusion/adjudication rules.

Any post-hoc exploratory analysis should be labeled exploratory.

## E. Claim rule

Human evaluation strengthens a claim only to the extent that the evaluation itself is aligned with the intended construct.

Examples:

- native/proficient annotator agreement on a WiC-like sense question supports the **gold label**;
- pairwise preference for a rewrite supports a **specified human quality/preference criterion**;
- neither automatically proves universal English competence.

Combine human evidence with public benchmark anchors, shadow transfer tests, prompt robustness, paired statistics, and product-route validation rather than making human preference the sole benchmark.
