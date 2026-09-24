# Pari English Core — lexical-collocation benchmark audit

This note records the research/provenance audit behind the `collocation_naturalness` dimension. It exists because collocation knowledge carries substantial product weight in Pari and must not rest on a vague citation or an unverified mirror.

## 1. EACL 2021 is the construct/data foundation

Primary paper:

- Luis Espinosa-Anke, Joan Codina-Filba, Leo Wanner. *Evaluating language models for the retrieval and categorization of lexical collocations*. EACL 2021.
- https://aclanthology.org/2021.eacl-main.120/

The paper defines lexical collocations as restricted combinations in which a base constrains the collocate used to express a semantic relation. Examples include `heavy rain`, `give a lecture`, and related lexical-function constructions.

### Important metadata correction: 16 categories, not 17

The ACL Anthology HTML abstract currently says **17** representative semantic categories. The paper PDF itself says **16** in the abstract and contribution statement, Table 2 lists 16 lexical functions, and Table 3 reports 16 labels. The released `labelmap.tsv` in the authors' repository also contains 16 labels.

For Pari, the paper PDF + released data are authoritative for the experimental protocol. Do not use the HTML-abstract value `17` as the benchmark category count.

The 16 EACL labels are:

- Oper1
- IncepOper1
- Oper2
- Real1
- Real2
- AntiReal2
- CausFunc0
- Caus1Func0
- LiquFunc0
- IncepPredPlus
- Magn
- AntiMagn
- Ver
- AntiVer
- Bon
- AntiBon

### Dataset and split design

The paper constructs a collocations-in-context corpus from an extended LEXFUNC resource and English Gigaword. It reports:

- 64,851 training sentences;
- 13,856 development sentences;
- 13,905 test sentences;
- 70/15/15 allocation approximately maintained per lexical function;
- critically, **no overlapping collocations across train/dev/test**, specifically to reduce lexical memorization.

That lexical-disjoint split is part of the construct-valid protocol. Pari must not replace it with a random sentence split.

The paper reports manual inspection precision above 0.95 for its corpus retrieval procedure, while also acknowledging that automatic retrieval can introduce some noise.

### Two distinct EACL tasks

The paper evaluates two different capabilities and they must not be conflated:

1. **Unsupervised collocate retrieval**
   - masked collocate prediction in sentence context;
   - BERT MLM in the paper;
   - ranking task;
   - MRR and MAP;
   - valid hits are collocates for a base under the corresponding lexical function;
   - paper explicitly notes incomplete gold coverage as a limitation.

2. **In-context lexical-function categorization**
   - input is effectively `<sentence, collocation, label>`;
   - 16-way LF classification;
   - the paper fine-tunes encoder models on the provided train split;
   - reports per-class precision/recall/F1 and average F1.

A zero-shot prompted LLM run is therefore **not** the native 2021 supervised categorization protocol and must never be reported as the paper's native score.

## 2. Original EACL release provenance

The paper itself links the authors' release repository:

- repository: `luisespinosaanke/lexicalcollocations`
- audited commit: `acbb5129f1601f8d1b6953fe9de5891a42e552c4`
- repository description explicitly identifies it as the EACL 2021 paper repository.

At that commit the original release contains:

- `data/lf_clf/labelmap.tsv`
- `data/lf_clf/train_data.tsv`
- `data/lf_clf/validation_data.tsv`
- `data/lf_clf/test_data.tsv`
- `data/gigaword_original/Collocations_Train.csv`
- `data/gigaword_original/Collocations_Val.csv`
- `data/gigaword_original/Collocations_Test.csv`

The classification test file has the expected simple form `sentence<TAB>collocation<TAB>numeric_label`, and the label map has the 16 classes used in the paper.

### License warning

The GitHub repository currently reports `license: null`, and no license file was found during this audit. Therefore:

- Pari must **not vendor or redistribute** the EACL data merely because the repository is public;
- any adapter should accept a user-obtained/local checkout or file path;
- this benchmark remains evaluation-only unless redistribution/use rights are separately established;
- the source commit/hash should be recorded for every serious run.

This is a legal/provenance caution, not a statement that local research evaluation is prohibited.

## 3. ACL 2026 SemanticQA is the modern LLM-facing collocation anchor

Primary paper:

- Yang Liu, Hongming Li, Melissa Xiaohui Qin, Chao Huang, Qiankun Liu. *Revisiting a Pain in the Neck: A Semantic Reasoning Benchmark for Language Models*. ACL 2026 Oral.
- https://aclanthology.org/2026.acl-long.210/

Official repository:

- `jacklanda/SemanticQA`
- audited commit: `56c82a587f4a6cef609255cd10af372d8c76600a`
- repository license: MIT for the benchmark code; upstream-source data rights still need to be respected independently.

SemanticQA explicitly reorganizes existing semantic-phrase resources for modern LLM evaluation and includes lexical-collocation tasks.

### Lexical Collocation Categorization (LCC)

SemanticQA's LCC:

- derives its labeled collocation data from the expanded LEXFUNC/EACL 2021 resource;
- uses a prompt containing the semantic taxonomy, context, and target collocation;
- evaluates zero-shot and few-shot LLMs directly;
- reports accuracy (and the repository also exposes macro/micro/weighted F1 tooling);
- paper Table 1 reports 305 LCC test examples for the main benchmark;
- Appendix B says test examples were sampled per semantic category for efficiency;
- includes controlled category-scaling experiments across 1/2/4/8/16 relation settings;
- the repository ships a fixed zero-shot prompt and prepared benchmark archive/harness.

The fixed zero-shot prompt asks the model to assign only the most plausible label from the supplied semantic taxonomy. This is much closer to Pari's base-LLM-selection setting than fine-tuning every candidate on the 2021 train split.

### Why SemanticQA does not replace EACL 2021

They answer different evidence questions:

- **EACL 2021** establishes the lexical-collocation construct, original corpus, lexical-disjoint split, retrieval formulation, and native supervised classification protocol.
- **SemanticQA 2026** provides a modern prompt-based LLM adaptation over collocation semantics and explicitly studies modern LLM behavior.

Pari should report them as separate protocol lanes rather than pretending they are interchangeable scores.

## 4. What English Core should use

For base-LLM screening, the preferred collocation evidence stack is:

1. **SemanticQA LCC zero-shot** — primary modern prompted collocation-semantic diagnostic for chat/instruct LLMs.
2. **SemanticQA LCC scaling** — robustness diagnostic showing whether fine-grained semantic distinctions collapse as taxonomy size rises.
3. **EACL 2021 release/protocol audit** — construct/source foundation and, where a comparable MLM/encoder is being studied, native retrieval or supervised categorization evidence.
4. **Pari fresh collocation minimal pairs** — contamination-resistant product-facing shadow evidence.

Do **not** collapse these into one number without preserving protocol labels.

## 5. Important limitations for Pari

Neither public benchmark is a perfect direct measurement of `naturalness` in the everyday writer sense.

- LF categorization measures fine-grained semantic/syntactic collocation relations, not simply whether `heavy rain` sounds better than `strong rain`.
- EACL retrieval gold is incomplete; the paper itself notes that valid collocates may be absent from the resource.
- SemanticQA's balanced test is deliberately controlled and is not the natural frequency distribution of all English collocations.
- SemanticQA's prompt taxonomy adds instruction-following/taxonomy-reading load to the linguistic judgment.
- Public collocation resources may be present in modern model training data.

Therefore the dimension must continue to pair public anchors with fresh Pari naturalness/collocation shadow cases and report results separately.

## 6. Standing implementation rules

Before a SemanticQA LCC result is used for promotion-quality model selection:

- pin the SemanticQA repository to a full immutable commit;
- require a clean checkout;
- hash the exact prepared LCC test/taxonomy/prompt files;
- preserve the exact zero-shot/few-shot setting;
- use the repository's documented evaluator or reproduce its metric transparently from frozen gold/predictions;
- record valid-output coverage in addition to accuracy/F1;
- do not silently cherry-pick the easiest category-scaling order;
- do not call a prompted LCC result the EACL 2021 native categorization score;
- preserve the public result separately from the fresh Pari collocation shadow score.

## 7. Research-backed conclusion

The prior `pending_reproducibility_audit` status was too pessimistic about source availability but too vague about protocol validity. The original 2021 release is publicly identifiable and pinned, and a 2026 peer-reviewed LLM benchmark now provides a modern prompt-based adaptation. The remaining engineering task is therefore not to invent a collocation benchmark; it is to wire the **existing SemanticQA LCC protocol reproducibly** while retaining EACL 2021 as distinct source/native evidence.
