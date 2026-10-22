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
| `subagent_judge.py` | Blind judging by Claude subagents inside a Claude Code session, for when the `claude` CLI cannot run. |
| `leaderboard.py` | Pools every verified judging folder of one task set into one ranking, so a new model is judged alone. |
| `import_t3_judgment.py` | Imports a completed GPT 6.1 Sol blind batch with its T3 task, model, effort and response-hash receipt. |

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
# 4. Run a blind judge. Claude CLI uses v2.claude_batch_judge; an owner-directed T3 GPT 6.1 Sol batch uses v2.import_t3_judgment.
python3 -m v2.claude_batch_judge --judging v2/judging/<run-id> --model <versioned-claude-model-id>
# 5. Verify citations, un-blind and write v2/results/<run-id>/.
python3 -m v2.aggregate --judging v2/judging/<run-id>
```

The Claude judge makes one fresh `claude -p` call per task (40 for the
screen set) with Opus at high effort, and its receipt totals the calls' tokens
and cost ([`CLAUDE_CLI.md`](CLAUDE_CLI.md)). The T3 GPT importer is kept for the
GPT judgment the owner ordered on 2026-10-18; see
[`DECISIONS.md`](../../../docs/DECISIONS.md) and [`T3_GPT_JUDGE.md`](T3_GPT_JUDGE.md).
A GPT receipt is recorded as GPT/T3 and never reported as a Claude judgment.

Results carry error bars. Each candidate's top-3 at bar gets a 95% interval,
and so does its gap to the leader, paired by task. Both use standard errors
clustered by source paragraph, because the tasks from one paragraph are not
independent ([Miller 2024, "Adding Error Bars to Evals"](https://arxiv.org/abs/2411.00640)).
A gap whose interval includes 0 is marked "not separable": the task set cannot
tell that candidate from the leader, and the full 200-task set should decide it.

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

The 2×T4 reference (`qwen35-35b-a3b-gptq-int4`) is a GPTQ MoE checkpoint.
Transformers alone cannot fill its per-expert weights, so the launcher also
installs GPTQModel for GPTQ candidates and the runner loads them with it. Since
GPTQModel does not check for missing weights, the runner compares the loaded
model with the checkpoint index itself. A model with any weight placed off the
GPUs fails at load instead of running on the CPU. GPTQModel builds a float
shell on the CPU first, and splitting its fused experts copied about 43 GB of
placeholder values, so the first smoke (`2026-10-22T1846Z-screen-94c5fca-limit2`)
was killed for host RAM. The runner now does that split without the copy
(`lazy_expert_shells`). The second smoke (`2026-10-22T1859Z-screen-ac3f270-limit2`)
loaded past that, but GPTQModel's default Marlin kernel does not compile for
the T4, so the runner asks for the ExLlamaV2 kernel. The reference answers whether
a big open model beats the best Mac-sized one by enough to justify
distillation (#92). Judge it alone with anchors, like any new model.

## Judging with subagents

When the `claude` CLI has no login or API key of its own (for example in a
cloud session), a Claude Code session judges with subagents instead:

```bash
python3 -m v2.subagent_judge prepare --judging v2/judging/<run-id> --work <scratch>/judge
# Give each subagent one batch from <scratch>/judge/plan.json. It reads only
# prompts/<task>.md, writes answers/<task>.json, and runs `check` on each answer.
python3 -m v2.subagent_judge collect --judging v2/judging/<run-id> --work <scratch>/judge --model <model>
python3 -m v2.aggregate --judging v2/judging/<run-id>
```

The prompts are the CLI judge's prompts, and the answers go through the same
validation. The work folder has no key, run metadata or raw output. The
receipt (`judge-session-receipt.json`) names the agents and hashes every saved
answer. It also records `model_verified: false`, because unlike the CLI's
`modelUsage`, a subagent's model can't be checked per call.

## Adding a new model

New models keep coming, so a new one is judged alone and never forces a
re-judge of the others. The cost is its own 40 screen outputs, plus 200 only
if it reaches the top group.

1. Add it to `bench/candidates.json` with a pinned revision.
2. Smoke test it, then run the screen on Kaggle for that model alone:
   `launch.py --set screen --candidates <new-id>`, then `fetch.py`.
3. Build packets with drift anchors: about 10 outputs that were already
   judged, mixed in blind:
   `python3 -m v2.blind --run v2/runs/<run-id> --anchors-from v2/judging/<earlier screen> --anchor-tasks 10`
4. Judge (CLI or subagents), then `python3 -m v2.aggregate --judging v2/judging/<run-id>`.
   `results.md` shows how far the anchors moved from their original labels.
5. Rank it with everything judged before: `python3 -m v2.leaderboard --set screen`.
   Folders judged by different judge setups are pooled only with
   `--allow-mixed-judges`, after checking the anchor agreement.
6. Only if its gap to the leader is not separable, repeat 2–5 on the `full`
   set with anchors from the earlier full judging.

Pooling works because the rubric gives absolute labels to each option, not a
ranking within a packet. A change to the rubric, the code checks or the prompts
breaks that, so `v2.leaderboard` refuses to pool across rubrics. Old outputs
then have to be judged again under the new version.

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
