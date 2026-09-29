# Pari Rewrite amount benchmark

This directory keeps the deterministic local-safe fallback diagnostic
(run.mjs with corpus.json) separate from a difficult, real-LLM benchmark
(run_native.py with corpus.brutal.v2.json). Fallback results do not count as
LLM paraphraser results.

The native corpus has 31 hand-authored cases covering quantifier scope,
negation, modality, causality, chronology, conditional exceptions,
counterfactuals, attribution, quoted instructions, technical identifiers,
numbers, uncertain evidence, personal voice, fragment repair, and dense long
paragraphs. Each case includes mustPreserve, doNotInfer, and editIntent notes.

Run the native model across every distinct slider configuration:

~~~sh
python3 benchmarks/strength-sweep/run_native.py --python /path/to/python-with-mlx
~~~

The complete 0–100 control currently collapses to six different prompt and
sampling configurations: 0–24, 25–49, 50–68, 69–74, 75–81, and 82–100. The
default tests one value from each configuration plus 100 as a repeat check
(seven runs per paragraph). Use --strengths 0-100 only when you specifically
want an actual generation at every integer; the fixed per-paragraph seed makes
those same-configuration calls directly comparable. Use --ids quantifiers-01,modal-scope-01 for a quick smoke.

The runner calls Pari's real native paraphrase worker, including its prompt,
MLX generation, and Python postprocessing. It uses one candidate to isolate the
slider; production normally ranks four candidates, so this is generator
evidence, not end-to-end UI acceptance. It also asks the exact TypeScript
protected-content extractor used by Pari for each case. The only binary gates
are successful non-empty generation and preservation of those exact protected
spans. The LLM judge assesses meaning, fluency, and fit; human review remains
the final decision.

Each completed row is flushed to raw.jsonl immediately. run.json captures the
model path, Python/MLX versions, repository checkpoint, corpus hash, and source
hashes for the worker and safety extractor. Re-running the identical command
resumes missing pairs; a changed configuration requires a different --out-dir.
The default output directory is results/native-brutal-v2/.

The summary reports per-strength change rates, lexical change, hard-gate
results, latency, and identical-output plateaus. These are diagnostics, not
quality scores. Judge completed sweeps with the separate local Qwen3-4B
checkpoint:

~~~sh
python3 benchmarks/strength-sweep/judge_native.py \
  --run-dir benchmarks/strength-sweep/results/native-brutal-v2 \
  --model "/Users/tejas/Library/Application Support/Open Local Phraser/Models/native-models/Qwen/Qwen3-4B-MLX-4bit"
~~~

It scores meaning, fluency, and slider fit and flags material meaning errors.
Ratings are supporting evidence, not ground truth or automatic approval; the
human still decides. The judge is an offline analysis aid, not part of Pari's
generation path, and it is not required for MTP speed measurements. When the
generator is Qwen3-4B, this is a self-judge; when the generator is Qwen3.5-4B,
it is a separate checkpoint, though still from the Qwen family.

Run the model-free overlapping-anchor regression after changing native
postprocessing:

~~~sh
python3 benchmarks/strength-sweep/qa_protected_masking.py
~~~

native_batch_server.py keeps the target model resident. It optionally supports
an external MLX draft model for isolated speed/parity testing, but that is
speculative decoding, not native MTP:

~~~sh
python3 benchmarks/strength-sweep/run_native.py --draft-model /path/to/draft --num-draft-tokens 3 --out-dir /tmp/pari-qwen-draft-probe
~~~

Do not enable that path in Pari's normal generation unless it shows both
correctness and a repeatable wall-clock win. A draft experiment must use a
separate output directory so its results cannot be mixed with target-only
rows.

## Qwen3.5 native MTP benchmark

The available Qwen native MTP drafter is not compatible with Pari's current
Qwen3-4B production weights. It requires a matching Qwen3.5-4B target and
MLX-VLM's MTP runtime. The benchmark therefore uses Pari's existing Qwen3.5-4B
general-model control as both the target-only control and the MTP target; it
does not promote or silently replace the production model.

The paired runner uses the same target, prompt builder, postprocessor, slider
values, input text, and deterministic per-case seed in both modes. It warms
both paths first and alternates their order. Model loading is excluded from
per-request latency. It records full request time, inference time, tokens per
second, finish reason, protected-text gates, and output text. A separate MTP
only pass covers the complete 31-case corpus at each distinct slider prompt
and sampling regime plus the 100 endpoint repeat:

~~~sh
python3 benchmarks/strength-sweep/run_mtp_native.py \
  --model /path/to/Qwen3.5-4B-MLX-4bit \
  --draft-model /path/to/Qwen3.5-4B-MTP-4bit \
  --python /path/to/venv/bin/python \
  --modes target-only,mtp \
  --strengths regimes \
  --out-dir benchmarks/strength-sweep/results/qwen35-mtp-speed-pilot

python3 benchmarks/strength-sweep/run_mtp_native.py \
  --model /path/to/Qwen3.5-4B-MLX-4bit \
  --draft-model /path/to/Qwen3.5-4B-MTP-4bit \
  --python /path/to/venv/bin/python \
  --modes mtp \
  --strengths regimes \
  --out-dir benchmarks/strength-sweep/results/qwen35-4b-mtp-brutal-v2
~~~

Pinned public artifacts used for this run:

- Target "mlx-community/Qwen3.5-4B-MLX-4bit", revision "32f3e8ecf65426fc3306969496342d504bfa13f3".
- Drafter "mlx-community/Qwen3.5-4B-MTP-4bit", revision "ab6f59bc6627196c611ab8851638651078170485".
- Runtime "mlx-vlm 0.7.2"; the isolated benchmark environment resolved MLX 0.32.2. Pari's installed MLX-LM runtime was not changed.

The [official MTP model card](https://huggingface.co/mlx-community/Qwen3.5-4B-MTP-4bit)
defines this 4-bit, 0.1B checkpoint as a drafter only for a compatible
Qwen3.5-4B target. The [MLX-VLM speculative-decoding guide](https://github.com/Blaizzy/mlx-vlm/blob/main/docs/usage.md)
documents the runtime/API used here.

The first counterbalanced pilot covered six difficult cases at five slider
values (30 matched pairs). On this Apple Silicon 16 GiB machine, MTP was faster
on 27/30 pairs, with 1.11x median and 1.14x geometric-mean speedup; all 30
target-only and MTP outputs were identical. This is a small local pilot, not a
2-3x guarantee or installed-app result. The long case benefited more than short
ones because MTP speeds decoding, not the whole prompt-processing path.

An observed product boundary: at strengths 82 and 100, the high-change
fragment case was rejected by Pari's exact protected-content rail when it wrote
the numeric anchor "8" as "eight", expanded a protected contraction, and
lowercased a protected name-adjacent phrase. Both target-only and MTP produced
the same candidate. Keep exact-anchor gate failures visible in the benchmark;
do not count those drafts as user-approved rewrites.

## Brutal slider run results (2026-09-22)

The full native MTP run completed all 217 rows: 31 synthetic paragraphs at the
seven slider representatives. Mean lexical change and the exact-span gate rate
move as follows:

| Slider | Mean lexical change | Exact-span gate passed |
| ---: | ---: | ---: |
| 0 | 1.2% | 100% |
| 25 | 1.5% | 100% |
| 50 | 8.3% | 96.8% |
| 69 | 11.7% | 87.1% |
| 75 | 11.7% | 83.9% |
| 82 | 24.3% | 54.8% |
| 100 | 24.3% | 54.8% |

This confirms the high end is no longer barely rewriting, but the 82/100
outputs pass the current literal-anchor gate on only 17/31 paragraphs. The 82
and 100 settings are the same prompt/sampling regime, and their outputs were
identical in this run.

Example from the low-edit control:

- Source: “The room was quiet, the instructions were clear, and I finished the
  form before lunch. I would use the same process again.”
- Strength 0: “The room was quiet; the instructions were clear, and I finished
  the form before lunch; I would use the same process again.”
- Strength 50: “The room remained quiet; the instructions were clear, and I
  completed the form before lunch; I would employ the same process again.”
- Strength 82: “The room remained quiet; the instructions were unmistakably
  clear, and I completed the form before lunch, a process I intend to repeat.”

The strength-82 wording is much more changed, but it also changes “would use
again” to “intend to repeat” and fails the exact `would` anchor. Treat this as a
real review flag, not a successful rewrite.

The paired target-only versus MTP speed pilot covered six difficult paragraphs
at strengths 0, 50, 75, 82, and 100 (30 matched pairs). MTP was faster on 27/30
pairs; median speedup was 1.11x and median time saved was 499 ms. All 30 output
pairs were byte-identical. This is generation time with both models already
loaded, not app end-to-end latency.

A second fresh-process pilot covered three paragraph lengths at strengths 50
and 82 (six matched pairs). It started a new worker for every request and
included Python startup, model loading, prompt construction, and generation.
MTP was faster on 5/6 pairs; median worker wall time was 7.92 s with MTP versus
9.02 s target-only (1.14x). The six outputs were byte-identical. The long case
saved about 8–10 seconds; the short cases showed smaller and less consistent
gains. This includes worker/model startup but not Swift, WebKit, or visible-app
overhead.

The optional Qwen3-4B LLM judge was attempted but did not complete this run
reliably: it repeated or truncated its JSON ratings on some paragraphs. No
judge score averages are reported. The raw model outputs, slider metrics, and
paired timing results remain valid; use human review for meaning decisions.

The source now has an explicit opt-in app route for the compatible Qwen3.5
target/drafter pair; Pari still defaults to Qwen3-4B. The worker passed a real
local generation smoke, the Swift source typechecked, and an isolated copy of
the existing app bundle was rebuilt with the current Swift bridge and MTP
worker, ad-hoc signed, and run through `--headless --headless-require-native`.
That end-to-end smoke passed against the local Qwen3.5 target/drafter and
reported `generator=native-mlx`. It reused the existing bundle's web assets;
it is not a fresh release build, installed-app test, or user-visible/user-
confirmed test. Pari's normal Qwen3-4B default remains unchanged.
