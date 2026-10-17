# Word Studio v2 judging rubric (#87)

Claude judges every candidate's options blind, in a dedicated Claude session.
The judge may read `RUBRIC.md`, `v2/judging/<run-id>/packets/*.md`, and
`scores.template.jsonl`. Candidate names, model/run metadata, raw outputs, and
`sealed/key.json` stay closed until `scores.jsonl` is final. Changing this file
changes its sha256, so judging that is already under way must finish under the
old version.

## Order of work

1. **Code checks first** (`v2/hard_checks.py`). An option with a `fail` flag
   breaks a rule the prompt states plainly. It is not judged and counts as
   relevance 0. A `warn` flag (a number changed or added, negation changed,
   name dropped, length off, new quotation, copies the paragraph) is a hint for
   the judge, never a verdict. Numbers only warn because "19th" ->
   "Nineteenth" keeps the fact. An option that really changes or invents a
   number is 0.

   Format is reported, never judged. `strict` means the reply is only the
   JSON object. `lenient` means the options were read from JSON in a code
   fence, from a complete JSON object followed by other text (only the object
   counts), or from a plain list. `unparseable` means no options, so every
   slot is below the bar. Malformed JSON is never repaired.
2. **Judge each output.** Use the paragraph, the selection and the
   instruction in the packet. Give a relevance label to every judged option,
   then the five criteria for the list as a whole.
3. **Un-blind and aggregate** (`v2.aggregate`). Every score must cite its task
   id, output ref and the raw output's sha256. The aggregator re-hashes the
   raw file and refuses any score that does not match.

## Relevance labels, per option

The writer has a small working vocabulary and picks every final word, so a
label asks one question: would a careful teacher accept this option in the
writer's essay, in this sentence, with the writer's meaning?

| Label | Meaning |
|---|---|
| **2 strong** | Fits the sentence and the paragraph as written, keeps the meaning and the certainty, reads like a good essay, and adds something the original lacks: a more precise word, a cleaner sentence. A writer could pick it without editing. |
| **1 usable** | Correct and on topic, but plain, a near-synonym of the original, slightly off in register, or needs a small edit (an article, a tense). A writer would not be misled by picking it. |
| **0 below the bar** | Wrong meaning, wrong sense of the word, ungrammatical in place, changes a fact, a number, a quotation, the negation or the certainty, adds a claim, is off topic, or is too odd or too rare for the essay. Every `fail` option is 0. |

Kind-specific readings:

- `tap_word`: the option replaces only the tapped word. Judge the sentence
  with the option in place. A different word sense is 0 ("good" as in
  "goods"). A word much rarer than the essay can carry ("salubrious" for
  "good") is 0.
- `phrase_to_word`: one word with the phrase's meaning in this sentence.
- `word_sentences`: the sentence must use the word correctly and could sit in
  this paragraph, making its point with only ideas the paragraph has.
- `condense`: same claim in fewer words. Dropping a detail the paragraph
  needs is 0. Dropping filler ("In my opinion, I think") is the point.
- `paraphrase`: new wording, about the same length and meaning.
- `academic`: a more formal register with the same certainty. Adding hedges
  or boosters that change certainty, or citations or evidence, is 0.

## Relevance bar and the swap rule (#91)

- **At the bar** means label 1 or 2. **Below the bar** means label 0, or a
  missing option (the model returned fewer than three).
- **Top of the list** is positions 1–3, the options the popover shows first.
- **Swap rule:** after the paste buffer ends (up to 30 s), an option in
  positions 1–3 may be swapped only if it is below the bar. Options in
  position 4 and lower never move. #91 builds a runtime check that predicts
  label 0. It is measured against these labels, so its error rate on judged
  options is known before it ships.

## Criteria, per output

Scores are 1–5 for the whole option list. Leave `criteria` null when no
option was judged (no output, or every option failed).

| Criterion | 5 | 3 | 1 |
|---|---|---|---|
| `fit` | every option fits the sentence and paragraph | about half fit | almost none fit |
| `meaning` | every option keeps the meaning, facts and certainty | some drift or overstate | meaning is often changed |
| `register` | clear essay register throughout | a mix of plain, stiff or casual | wrong register for an essay |
| `variety` | options give real choices, not near copies | some repetition | mostly the same option |
| `usefulness` | a writer with a small vocabulary gets several strong picks, best first | one or two good picks, or best buried | little the writer could use |

## Score file

Copy `scores.template.jsonl` to `scores.jsonl` and fill it in. The first line
is the header:

```json
{"header": true, "judge": "claude-opus-5-5", "session": "<session id>", "blind": true, "rubric_sha256": "…", "key_sha256": "…", "packets_index_sha256": "…"}
```

Each other line is one output:

```json
{"task_id": "ws2-screen-p01-tap_word-1", "label": "C", "output_ref": "o-…", "output_sha256": "…",
 "criteria": {"fit": 4, "meaning": 5, "register": 4, "variety": 3, "usefulness": 4},
 "relevance": {"1": 2, "2": 2, "3": 1, "5": 0}, "note": "option 5 is the wrong sense"}
```

- `relevance` keys are 1-based option numbers, and only the judged ones. The
  aggregator recomputes the code checks and refuses a row that labels a
  `fail` option or misses a judged one.
- `note` is short and required whenever an option is labelled 0, naming the
  option and the reason.

## Results

`v2.aggregate` writes `v2/results/<run-id>/results.json` and `results.md`.
For each candidate:

- **top-3 at bar:** positions 1–3 at the bar, out of 3 × tasks. This is the
  main metric. Ties go to usable options per task.
- top-1 at bar, top-3 strong, usable options per task, strong share;
- criteria means;
- code-check fail and warn counts (including options past the requested count),
  output format counts, token-limit hits;
- latency on Kaggle T4 (Transformers fp16, so not the Mac): median and p90
  for first text, first option, third option and the whole output;
- citations: every task id, output ref, raw output path and sha256 behind
  the numbers.

Candidates whose run failed appear with their error and no scores.
