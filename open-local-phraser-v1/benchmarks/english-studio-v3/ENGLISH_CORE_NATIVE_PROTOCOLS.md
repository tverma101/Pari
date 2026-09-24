# Pari English Core — native / official protocol lane

The common prompted English Core screen exists for fast apples-to-apples triage across modern chat/instruct models. It is **not** a replacement for benchmark-native scoring.

This document records native or official protocol lanes that should be used before making promotion-quality or research-level claims.

## 1. Why a native lane is required

Benchmark adaptation can change what is being measured. A prompt such as:

```text
Which sentence is more acceptable?
A. ...
B. ...
```

mixes the target linguistic ability with instruction following, answer formatting and chat-template behavior.

Where an established benchmark defines a model-native scoring protocol, English Core reports that result separately from the common prompted screen.

Do not average native and prompted scores into one opaque number.

---

## 2. BLiMP — primary native grammar lane

### Published protocol

Warstadt et al. (TACL 2020) evaluate each minimal pair by asking whether a language model assigns **higher probability to the acceptable sentence** than to the unacceptable sentence.

Reference: https://aclanthology.org/2020.tacl-1.25/

This is closer to raw grammatical knowledge than asking a chat model to answer an A/B instruction.

### Current reproducible MLX path

Current `mlx-lm` exposes an `lm-evaluation-harness` adapter with sequence log-likelihood scoring. Current `lm-evaluation-harness` provides a `blimp` group containing all 67 English BLiMP tasks, with the good sentence as the target choice and accuracy as the aggregate metric.

Relevant upstream files:

- `ml-explore/mlx-lm/mlx_lm/evaluate.py`
- `EleutherAI/lm-evaluation-harness/lm_eval/tasks/blimp/_blimp.yaml`
- `EleutherAI/lm-evaluation-harness/lm_eval/tasks/blimp/_template_yaml`

### Command

For a raw/native likelihood run:

```bash
python -m mlx_lm.evaluate \
  --model /path/to/model \
  --tasks blimp \
  --output-dir blimp-native \
  --no-apply-chat-template \
  --seed 123
```

Record:

- model/revision/artifact hash;
- quantization;
- `mlx-lm` revision/version;
- `lm-evaluation-harness` revision/version;
- tokenizer revision;
- whether chat templating was disabled;
- per-task BLiMP scores;
- group aggregate.

### Interpretation

For base causal LMs, this is the preferred BLiMP evidence.

For instruct/chat checkpoints, raw sentence likelihood is still informative about the underlying model distribution, but the checkpoint was optimized for a chat format. Therefore report **both**:

1. native likelihood BLiMP;
2. Pari's common prompted BLiMP screen.

A disagreement between those lanes is a protocol-sensitivity result, not something to average away.

---

## 3. CoLA

CoLA's established headline metric is **Matthews correlation coefficient (MCC)** over acceptability labels.

Reference: https://aclanthology.org/Q19-1040/

English Core rules:

- the current 300-example balanced prompted subset is a **screen only**;
- do not call accuracy on that balanced subset an official CoLA score;
- promotion-quality reporting should preserve the native evaluation distribution and report MCC;
- if a generative LLM is adapted through a prompt rather than a trained classifier head, label the result `prompted CoLA classification (MCC)` rather than implying the original supervised setup.

The model adaptation and metric are separate pieces of provenance.

---

## 4. WiC

WiC evaluates whether a target word has the same sense in two contexts.

Reference: https://aclanthology.org/N19-1128/

English Core rules:

- public-fast label-balanced accuracy is a screening diagnostic;
- a serious public result should use the full official evaluation/validation distribution available for local scoring and report accuracy;
- preserve the exact prompt/adaptation protocol because a prompted generative model is not identical to a supervised WiC classifier.

---

## 5. PAWS

PAWS evaluates paraphrase identification under high lexical overlap.

Reference: https://aclanthology.org/N19-1131/

English Core rules:

- public-fast balanced sampling remains a screen;
- full-distribution evaluation should be reported separately;
- report the benchmark's classification metrics appropriate to the chosen PAWS split/protocol;
- do not merge PAWS classification evidence with free-form paraphrase generation quality.

---

## 6. SWORDS — primary native lexical lane

SWORDS is a high-priority anchor because it directly evaluates contextual lexical substitution for writing assistance.

Reference: https://aclanthology.org/2021.naacl-main.345/

Pari provides adapters:

- `build-swords-english-core-prompts.py`
- `convert-swords-english-core-output.py`

The final result must be scored by the **official SWORDS evaluator**. Pari does not redefine SWORDS metrics.

Preserve the official dataset version, evaluator revision and generated `.lsr.json` output.

---

## 7. JFLEG — primary native fluency lane

JFLEG provides human fluency rewrites and an official multi-reference GLEU evaluation workflow.

Reference: https://aclanthology.org/E17-2037/

Pari provides adapters:

- `build-jfleg-english-core-prompts.py`
- `convert-jfleg-english-core-output.py`

Use the official JFLEG references and GLEU evaluator rather than replacing them with a general LLM judge.

---

## 8. EditEval / IteraTeR

For generative editing, prefer editing-native evidence over blank-page writing leaderboards.

- EditEval: https://aclanthology.org/2024.conll-1.7/
- IteraTeR: https://aclanthology.org/2022.acl-long.250/

Use task-native metrics and held-out human revisions where reproducible. Preserve per-task results because editing capabilities need not move together.

WritingBench and creative-writing diagnostics remain secondary evidence.

---

## 9. Native-vs-prompted reporting rule

For any public anchor, report these fields explicitly:

```text
benchmark
benchmark version/revision
source split/config
model adaptation
native or prompted
chat template on/off
metric
scorer/evaluator revision
score
```

Allowed examples:

- `BLiMP native likelihood accuracy`
- `BLiMP Pari prompted-screen accuracy`
- `CoLA prompted classification MCC on native validation distribution`
- `SWORDS official evaluator result`
- `JFLEG official GLEU`

Not allowed:

- `BLiMP score` when the protocol is unclear;
- `CoLA official score` from the balanced 300-item Pari screen;
- combining native and prompted results into one number without showing both.

Protocol disagreement is evidence about model behavior and evaluation sensitivity, not noise to hide.