# Word Studio v2

The benchmark that picks Pari's base model (#85, #86, #87). It runs on Kaggle
2×T4 first. Mac timing (#88) comes later, for the finalists only.

## Pieces

| File | What it does |
|---|---|
| `source/paragraphs.json` | 48 short student-voice essay paragraphs written for this benchmark (CC0). Quotations come only from public-domain works. |
| `prompts.py` | The frozen prompts, option counts, token caps and decoding settings. |
| `build_tasks.py` | Builds `tasks/screen.jsonl` (40 tasks) and `tasks/full.jsonl` (200 tasks, no shared sentences) and records their sha256 in `tasks/manifest.json`. |
| `run_candidate.py` | Runs one candidate on one set with Transformers and keeps every raw output with its stream timing. Records failures; never scores. |
| `controls.json` | A broken control that must fail at load, which proves failures get recorded. |
| `hard_checks.py` | Code checks on every option before judging. |
| `blind.py` | Builds blind judging packets and a sealed key from a fetched run. |
| `RUBRIC.md` | The judging rubric, relevance bar, swap rule (#91) and score file format. |
| `aggregate.py` | Verifies rubric, packet, index and raw-output hashes plus every score citation, then un-blinds and writes results. |

## Task kinds

| Kind | Options | Token cap | Feature |
|---|---|---|---|
| `tap_word` | 10 | 320 | tap a word: replacements that fit the sentence |
| `phrase_to_word` | 10 | 256 | phrase to one word |
| `word_sentences` | 5 | 768 | word to example sentences for this paragraph |
| `condense` | 5 | 640 | same meaning, fewer words |
| `paraphrase` | 5 | 768 | same length, new words |
| `academic` | 5 | 896 | more academic, no new claims |

Every candidate gets the same messages and one sample per task: temperature
0.7, top-p 0.9, top-k 50, seeded from the task id, with thinking off. Only the
model's own chat template differs, and the rendered prompt is kept with each
output.

## Workflow

From the repository root:

```bash
# 1. Push the commit, then start the Kaggle run (uses your Kaggle GPU quota).
python3 kaggle/word-studio/launch.py --set screen --candidates qwen35-2b,qwen35-4b,control-missing-revision
# 2. When it finishes, copy the raw outputs into v2/runs/<run-id>/.
python3 kaggle/word-studio/fetch.py --run-id <run-id>
```

From `bench/word-studio`:

```bash
# 3. Build blind packets. The judge reads RUBRIC.md, packets/*.md and scores.template.jsonl only.
python3 -m v2.blind --run v2/runs/<run-id>
# 4. Run the resumable Claude CLI judge; it records the pinned model and effort in scores.jsonl and its receipt.
python3 -m v2.claude_batch_judge --judging v2/judging/<run-id> --model <versioned-claude-model-id>
# 5. Verify citations, un-blind and write v2/results/<run-id>/.
python3 -m v2.aggregate --judging v2/judging/<run-id>
```

Runs, judging folders and results are never overwritten. A new attempt gets a
new run id (it carries the UTC launch time). The kernel slug is reused and
Kaggle serves only its latest output, so fetch a run before launching another.
A failed candidate is recorded with its error and gets no scores.
Before creating packets, the builder validates each completed run's exact
output filenames against its task limit and completion record. All judged
candidates must have the same task set; missing outputs are never silently
dropped. An explicit `--tasks` subset is recorded in `packets/index.json`.

Start with a smoke run (`--limit 2`) of every candidate. It shows which ones
load and generate on T4 in fp16 before the full screen spends quota.

## Rebuilding the tasks

```bash
python3 -m v2.build_tasks --check   # verify the committed tasks
python3 -m v2.build_tasks           # rebuild after an intentional change
```

Changing a paragraph or a prompt changes the task hashes. Results for the old
hashes then no longer match, so bump `PROMPT_VERSION` and start new runs.

## Tests

```bash
python3 -B -m unittest discover -p 'test_*.py'
```

These run on a CPU with no model weights, network or Kaggle credentials. CI
runs them in `deterministic-qa.yml`.
