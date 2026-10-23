# Pari plan

**Status: approved by the owner on 2026-10-15.** Mirrored in pinned issue
#93. It replaces #71 and the 2026-10-07 plan. Decisions are logged in
[`DECISIONS.md`](DECISIONS.md).

## Implementation status (2026-10-23; does not change owner decisions)

- **Merged:** repo cleanup (#83), pinned candidate catalog (#84), essay-fit tap-word
  popover (#89), and Word Studio v2 benchmark infrastructure and real screened
  results (#85, #86, #87; [PR #99](https://github.com/tverma101/Pari/pull/99),
  merged as `30ab0e7`). Claude Opus 5.5 scored 200 anonymized screen outputs
  against 40 tasks with preserved raw Kaggle outputs and audited SHA receipts.
- **Screen is not final selection.** Qwen3.5-4B, SmolLM3-3B and Phi-4 Mini are
  statistically non-separated in the 40-task screen. Run these three on the
  previously frozen disjoint 200-task `full` set, blind-score again and compare
  paired intervals. The 35B 2×T4 reference has no Word Studio v2 quality score;
  retain that explicit missing state until a real attempt.
- **Mac gate is still open:** 4-bit MLX latency, unified-memory fit, quality loss
  and long-session stability on the actual 16 GB Mac (#88, #31), *before*
  production model promotion. Do not transplant Kaggle FP16 speed numbers.
- **App:** Word Lab [PR #97](https://github.com/tverma101/Pari/pull/97)
  passes deterministic CI but remains a draft pending real native-app
  screenshot/recording. Adaptive pre-compute (#91) is not complete.
- **Execution:** Follow [issue #34](https://github.com/tverma101/Pari/issues/34)
  for the current v2 full finalist workflow. The older English-Core/Bonsai
  instructions are archived and must not replace this approved plan.


## What Pari is

Pari is a Mac writing assistant for school and college essays. The writer's
working vocabulary is small, which makes rewriting hard. Pari shows many options
that fit the paragraph's context. The writer always picks the final words. The
AI never rewrites anything without a tap.

## Version 1 features

**Tap a word.** A small popover lists replacements that fit this sentence's
meaning and an essay register. These are not raw thesaurus entries. The tap
stays simple: one list, one click to apply.

**Word Lab panel**, beside the essay:

- **Word → sentences.** Pick a word, either yours or a suggestion. You see
  several sentences that use it in this paragraph's context, plus a "Use in my
  sentence" button.
- **Sentence → fewer words.** Select a sentence or phrase to get these options:
  - Condense: the same meaning in fewer words.
  - Phrase → one word: "refused to change his mind" → obstinate.
  - Same length, new words: a classic paraphrase.
  - More academic: essay register without adding new claims.

**Timing.** On paste, Pari processes the paragraph adaptively in the background.
- The first options are ready in about 5 s.
- The buffer lasts up to 30 s.
- After the buffer, options stay put. Only the options at the top of a list
  can be swapped, and only when they fall below the relevance bar. The bar is
  set from benchmark data. Lower options never move.
- When the writer edits a sentence, only that sentence is processed again. The
  model has to keep up with heavy editing.

**Pick log.** Every choice is recorded locally for a personal fine-tune later.
The log is never committed, because this repository is public.

**Not in v1:** a paragraph-wide "word bank" panel.

## Where things run

| Place | Role |
|---|---|
| Kaggle (2×T4, free) | Primary. Benchmark runs, data generation, fine-tuning. |
| Modal ($30/month free credits) | Overflow for fine-tuning when Kaggle can't fit the job. |
| Mac (16 GB) | Final runtime. The chosen model is quantized (MLX, about 4-bit) and runs locally. |

This reverses the 2026-10-07 rule "no new local-generator work". The end state
is a local model.

## Choosing the model

1. **Candidates.** Open models that fit 16 GB at about 4-bit, convert to MLX,
   and allow personal use. Plus one reference: the largest model that 2×T4 can
   serve. The candidate list is researched fresh. No family is assumed, because
   most models are tuned for maths and code, not vocabulary.
2. **Word Studio benchmark.** Tasks built on openly licensed or generated essay
   paragraphs. Every task maps to a v1 feature. Run a quick screen of about 40
   tasks on all candidates, then the full set of about 200 on the top 2–3.
3. **Blind judging by Claude.**
   - Code checks the hard rules first: format, protected content, meaning.
   - Claude then judges the rest without seeing candidate names.
   - Every score cites a task id and a raw output file.
4. **Speed on the real Mac.** After quantizing, measure time to first options
   and full pre-compute time on a ~150-word paragraph.
5. **Decision.** The winner is the best quality that meets the timing above on
   the 16 GB Mac.

**Evidence rule.**
- No number goes into a results file unless a real run produced it and its raw
  outputs are kept.
- No fallback or "calibrated" values, ever.
- A run that fails is recorded as failed.

PR #82 broke this rule; its fabricated results were removed in PR #94.

## Distillation (owner-locked, probably unused)

This happens only if big open models easily beat the best Mac-sized model. The
owner named GLM 5.3 Flash, DeepSeek and MiMo 2.6 Pro as the bar. If they do:
- Agents prepare the dataset format, prompts and validation scripts.
- Only the owner generates data with big LLMs and approves it.
- These issues are labelled `owner-only`.

Otherwise the winner is just quantized.

## Personal fine-tune (P2)

The pick log feeds a LoRA fine-tune once there are at least 200 picks. Training
runs on Kaggle, with Modal as overflow. The result is quantized and runs on the
Mac.

## Repository cleanup (clean in place)

Target layout:

```
app/     Mac app: React + Swift, editor, popover, Word Lab
kaggle/  notebooks: candidate runs, data generation, training
model/   quantize (and, if ever needed, distill) to MLX for the Mac
bench/   Word Studio tasks and scoring, only what is used
docs/    this plan and a decisions log
```

**Archived to branch `archive/2026-10` plus a tag.** They stay recoverable and
nothing is deleted from history.
- `lab/`
- `app/benchmarks/{eval,llm-shootout,paraphrase-v2,quillbot,strength-sweep}`
- `app/research/`
- Harness code that only served parked issues.

**Not in git, handled on disk.**
- `inspect/` is a separate, ignored repository. It moves out of this folder; it
  is not deleted.
- `open-local-phraser-v1/` holds only empty folders.

**PR #82.** Remove the fabricated result files and the hardcoded fallback
scores, then reopen #34, #31 and #75 with the reason.

**Issues.**
- A new pinned plan issue replaces #71.
- About 8–10 new issues, in build order.
- PR #12 gets closed.
- Old issues stay closed as history.

## Build order

1. Repository cleanup, the PR #82 removal, the new plan issue and the new issues.
2. Benchmark: the candidate list, tasks, a Kaggle runner with real outputs,
   blind judging, timing on the Mac. Then pick the model.
3. App: the popover, the Word Lab and adaptive pre-compute on the chosen model.
4. Keep the pick log working throughout.
5. Later: distillation prep (owner-only) and the personal fine-tune (P2).

## Open questions

- Until the model is chosen, what powers the app day to day: the existing local
  Qwen3-4B, or a Kaggle session? The default for now is the existing local
  Qwen3-4B.
