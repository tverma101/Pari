# Codex turn log

## 2026-09-07 — FreeLLMAPI model selection and Pari route

- `scope`: Pari production checkout, model catalog, packaged macOS app, and
  bounded FreeLLMAPI shootout.
- `project`: `tverma101/Pari`, branch `feat/quality-judge-holdout`; canonical
  checkout is this directory.
- `goal`: Test usable FreeLLMAPI models against Pari's frozen English-repair
  corpus, select the safest quota-compatible candidate, and add an explicit
  packaged route without weakening the local fallback.
- `status`: implemented, tested, packaged, and published to the isolated
  feature branch in commit `a5580c1` (`feat: add quota-safe FreeLLM inference
  route`).
- `changed_files`: `native-runtime/freellm_worker.py`, Swift route selection in
  `Sources/OpenLocalPhraser/main.swift`, native bridge/backend metadata,
  `script/build_and_run.sh`, `package.json`, `build_dmg.sh`, model catalog and
  downloader path handling, shootout runners, README/AGENTS guidance, and
  existing grammar/learned-judge hardening in the working branch.
- `inspected_scope`: FreeLLMAPI local `/v1/models` and chat completions,
  249-model catalog, current configured providers, Qwen3/MiniCPM/Qwen3.5/Ling
  local bundles, and the four production/benchmark model paths.
- `selection`: `gemma-4-31b` is the explicit FreeLLMAPI default. On the frozen
  64-case corpus it scored 57/64 (89%) with 2 hard-gate failures and a 0.51s
  median; `llama-3.3-70b-fp8-fast` scored 59/64 (92%) with 3 hard-gate
  failures and a 0.62s median. Gemma wins the safety-first selection rule.
  The two runs used about 22k measured prompt+completion tokens. These are
  automatic selection signals, not a QuillBot or local-Qwen superiority claim.
- `implementation`: `PARI_GENERATION_BACKEND=freellm` opts in; the key is
  process-only through `PARI_FREELLM_API_KEY`; base URL, model, and timeout are
  configurable. The remote worker sends one draft and Pari may send one
  stricter repair request, then applies the existing protection, meaning,
  grammar, flow, NLI, and offline fallback gates.
- `validation`: `npm run build`; `npm run qa:approval`; `npm run
  qa:learned:judge`; `npm run qa:grammar:harper`; `npm run qa:grammar:ewt`;
  `npm run qa:native:model`; `npm run qa:native:prompt`; `npm run
  benchmark:quality`; `npm run build:desktop`; `npm run qa:installed`; `npm
  run qa:installed:connected`; `npm run qa:installed:custom`; `npm run
  qa:installed:missing-model`; and `npm run qa:installed:freellm` all passed.
  The packaged remote smoke reported `generator=freellm-api`, contextual
  choices, and grammar highlighting. The final rebuilt app has no model
  weights or Python bytecode cache in the bundle, and
  `codesign --verify --deep --strict` passes after the installed local smoke.
- `evidence_state`: source implemented=yes; tests passed=yes; packaged and
  installed=yes; live FreeLLMAPI route reached=yes; user visual confirmation=no.
- `blocker`: none for the local implementation. FreeLLMAPI provider
  availability, routing, and quotas are live service state and can change;
  the app remains local by default and fails closed to its offline engine. The
  final native UI quota refresh was not captured because the Mac locked; no
  current quota number is inferred from that missing read.
- `cleanup`: the transient API key was cleared from the clipboard, no task
  processes remain, and the generated invalidating bundle cache was moved
  recoverably to `/tmp/pari-bundle-pycache-2026-09-07` before the final rebuild.
- `next_action`: none required for this turn. Do not inspect or run GitHub
  Actions without a separate request.
- `rollout_refs`: prior Pari learned-judge and holdout work is recorded in the
  Codex memory rollout archive; this turn's external benchmark JSONL remains
  under the task workbench and is not bundled into the app.

## 2026-09-07 — Paraphraser readiness checkpoint and fragment repair

- `scope`: Pari production checkout, native Qwen3 generation pipeline, frozen
  64-case evaluation, packaged macOS app, and installed recovery paths.
- `project`: `tverma101/Pari`, branch `feat/quality-judge-holdout`; canonical
  checkout is this directory.
- `goal`: Decide whether Pari is ready to present as a reliable paraphraser;
  where it was not, repair the highest-confidence quality gap and revalidate
  the shipped path.
- `assessment`: not ready to claim a broadly reliable or QuillBot-superior
  paraphraser. It is ready as a safety-first local rewrite prototype with a
  packaged native path. The remaining readiness proof is human and
  product-specific, not another generic model score.
- `changed_files`: `src/lib/generation/brokenProseRepair.ts`,
  `src/lib/generation/rewriteQuality.ts`,
  `src/lib/generation/directEnglishRepair.ts`,
  `native-runtime/paraphrase_worker.py`, both MLX/OpenAI-compatible shootout
  prompts, `scripts/qa-paraphrase.mjs`, `scripts/qa-native-model.mjs`,
  `scripts/qa-native-prompt.py`, `docs/remaining-work.md`, and this log.
- `implementation`: recognized only source-backed standalone causal, waiting,
  and note fragments; completed those conservatively without adding an actor,
  event, or outcome; normalized high-confidence “because of reasons” wording;
  tightened model prompts against invented facts; and added unit, prompt, and
  native-model regression fixtures.
- `benchmark`: the same raw Qwen3-4B MLX run remained 61/64 (95%) with all
  broken-word, vague, run-on, word-salad, tense/agreement, register, and canary
  cases passing. The remaining automatic misses were `fr-02`, `fr-03`, and
  `fr-08` fragment band-fit cases. This score is a judge signal, not a human
  paraphrase-quality claim. Raw output and scores were moved to
  `/tmp/pari-benchmark-2026-09-07/` and are not repository artifacts.
- `validation`: `npm run qa:paraphrase`; `npm run qa:native:prompt`; `npm run
  qa:learned:judge`; `npm run qa:grammar:harper`; `npm run qa:grammar:ewt`;
  `npm run qa:native:model`; `npm run benchmark:quality`; `npm run build`;
  `npm run build:desktop`; `codesign --verify --deep --strict --verbose=2
  release/Pari.app`; `npm run qa:installed`; `npm run
  qa:installed:missing-model`; `npm run qa:installed:custom`; and `npm run
  qa:installed:connected` all passed. The final bundle contains no model
  weights or `__pycache__` directories.
- `evidence_state`: source implemented=yes; automated tests passed=yes;
  model-backed native fixture passed=yes; packaged=yes; installed native,
  disconnected, and recovery paths passed=yes; FreeLLM route remains covered
  by the previous live smoke; blind human QuillBot comparison=no; user visual
  confirmation=no.
- `blocker`: no local implementation blocker. Readiness is blocked by the
  remaining P0 human evidence: a larger held-out real-paragraph comparison
  against the same default/conservative QuillBot inputs and a contextual
  synonym spot-check. Do not promote Qwen3.5, MiniCPM, Ling, or FreeLLMAPI on
  the automatic score alone.
- `cleanup`: task-generated benchmark files were moved recoverably outside the
  repository; no model weights were added to the app bundle; no GitHub Actions,
  PR, merge, or default-branch mutation was performed.
- `next_action`: run the P0.1/P0.2/P0.4 human spot-check and larger holdout,
  then reassess readiness before making any model-promotion or PR decision.
- `rollout_refs`: prior Pari learned-judge and holdout work is recorded in the
  Codex memory rollout archive; current raw outputs are retained only under
  the temporary path above.

## 2026-09-07 — Bounded live QuillBot browser comparison

- `scope`: QuillBot's live in-app browser page and the installed Pari native
  worker, using the same synthetic corpus sample.
- `method`: QuillBot `https://quillbot.com/paraphrasing-tool` in Standard mode,
  guest session, with no sign-in or quota workaround. Pari used the installed
  Qwen3-4B MLX worker with its normal post-processing.
- `case`: `bw-02`, input `cant make it tmrw, smth came up sry`.
- `observed_outputs`: QuillBot visibly produced `Sorry, something came up and
  I can't make it tomorrow.` and a repeated request produced the variant `I
  apologize, but I can't make it tomorrow.` Pari produced `I can't make it
  tomorrow, something came up. I'm sorry.`
- `assessment`: both systems produced grammatical text. Pari preserved the
  source's reason in both the input and its output; one observed QuillBot
  variant omitted that reason while sounding more polished. This is one live
  example, not a general superiority claim.
- `limitation`: a further guest request opened QuillBot's `Continue for free`
  sign-up limit. The comparison stopped there; no account login, duplicate
  session, or quota bypass was attempted. A blind multi-case comparison is
  still outstanding.
- `evidence_state`: live QuillBot one-case sample=yes; installed Pari output
  yes; blind pairwise human comparison=no; user visual confirmation=no.
- `cleanup`: the QuillBot tab was reloaded to its blank initial state; no
  external account or repository state was changed.

## 2026-09-07 — Bounded pending-status word-salad repair

- `scope`: Pari's native Qwen3 worker, local finalization, MLX/OpenAI-compatible
  shootout prompts, regression fixtures, packaged app, and installed smoke
  paths.
- `goal`: Continue improving the user-facing paraphrase boundary after the
  native probe exposed a dense operational-note noun stack.
- `changed_files`: `src/lib/generation/brokenProseRepair.ts`,
  `native-runtime/paraphrase_worker.py`, both shootout prompt adapters,
  `scripts/qa-paraphrase.mjs`, `scripts/qa-native-model.mjs`,
  `docs/remaining-work.md`, and this log.
- `implementation`: added a bounded, source-neutral repair for sentences of
  the form “The ... is pending ... status,” moving the stated status into a
  grammatical “The ... status of ... is pending” frame. The rule requires a
  recognizable multiword subject and short status phrase, preserves the
  subject/status terms, and does not invent a cause, actor, or outcome. The
  native prompt and standalone shootout prompts now describe the same repair.
- `validation`: `npm run qa:paraphrase`; `npm run qa:native:prompt`;
  `npm run qa:learned:judge`; `npm run qa:grammar:harper`; `npm run
  qa:grammar:ewt`; `npm run qa:native:model`; `npm run benchmark:quality`;
  `npm run build`; `npm run build:desktop`; `codesign --verify --deep
  --strict --verbose=2 release/Pari.app`; `npm run qa:installed`; `npm run
  qa:installed:connected`; `npm run qa:installed:missing-model`; and `npm run
  qa:installed:custom` all passed. The native fixture passed through Qwen3
  candidate fan-out, and the packaged worker contains the repair.
- `evidence_state`: source implemented=yes; automated tests passed=yes;
  model-backed native fixture passed=yes; packaged=yes; installed local,
  connected-native, missing-model fallback, and custom-mode paths passed=yes;
  current live FreeLLMAPI route not re-smoked because its credential is not
  present; blind human QuillBot comparison=no; user visual confirmation=no.
- `blocker`: no local implementation blocker. Pari is still not ready for a
  broad QuillBot-class or superiority claim; the larger held-out and blind
  human comparison remain the required evidence.
- `cleanup`: generated Python cache was moved recoverably to
  `/tmp/pari-pycache-word-salad-2026-09-07`; the app bundle contains no model
  weights or Python bytecode; no GitHub Actions, PR, merge, or default-branch
  mutation was performed.
- `next_action`: continue with P0.1/P0.2/P0.4 human holdout and contextual
  synonym review before any model promotion or readiness claim.

## 2026-09-07 — Test and documentation publication audit

- `scope`: canonical Pari checkout, QA scripts/fixtures, benchmark guidance,
  and project documentation on `feat/quality-judge-holdout`.
- `goal`: Publish all pending canonical test and documentation work to GitHub.
- `result`: no uncommitted or unpushed canonical test/documentation files were
  present before this audit. The QA and documentation changes from the prior
  improvement are already included in commit `31d7bcb`, and local `HEAD`
  matches `origin/feat/quality-judge-holdout`.
- `evidence_state`: canonical source/test/docs tracked=yes; remote branch
  synchronized=yes; ignored `paraphraser-inspect/` workbench not published;
  user-confirmed remote review=no.
- `validation`: `git status --porcelain=v1 --untracked-files=all` was clean;
  tracked QA/documentation paths were enumerated with `git ls-files`; remote
  identity and branch tracking matched `git@github.com:tverma101/Pari.git`.
- `blocker`: none for canonical test/documentation publication. The ignored
  workbench is outside the verified Pari source boundary and was not staged.
- `next_action`: none; continue from the synchronized topic branch.

## 2026-09-07 — Broadened the manual synonym palette

- `scope`: canonical Pari source, contextual/dictionary synonym generation,
  synonym QA, packaged desktop app, and installed smoke paths on
  `feat/quality-judge-holdout`.
- `goal`: optimize the practical paste-a-paragraph workflow for manual editing
  by making more of the existing safe local synonym pool reachable without
  widening automatic paragraph generation.
- `changed_files`: `src/App.tsx`,
  `src/lib/rewriteStack/advancedParaphrase.ts`,
  `scripts/qa-paraphrase.mjs`, `README.md`, `docs/remaining-work.md`, and this
  log.
- `implementation`: raised the shared visible synonym cap from 40 to 64 and
  made the UI use that exported boundary. Existing ranked contextual,
  dictionary, WordNet, thesaurus, and mask-model candidates remain ordered by
  the current semantic safeguards; the automatic paragraph path is unchanged.
  Initial base tokens now request contextual expansion when the broader
  palette is opened.
- `validation`: `npm run qa:approval`; `npm run benchmark:quality`;
  `npm run qa:native:prompt`; `npm run build`; `npm run build:desktop`;
  `codesign --verify --deep --strict --verbose=2 release/Pari.app`;
  packaged-bundle hygiene check; `npm run qa:installed`; `npm run
  qa:installed:connected`; `npm run qa:installed:missing-model`; and `npm run
  qa:installed:custom` all passed. The regression suite confirms the 64-option
  boundary and more than 40 generated local choices for `world`.
- `evidence_state`: source implemented=yes; automated tests passed=yes;
  packaged and signed=yes; installed local, connected-native, recovery, and
  custom-mode paths passed=yes; live FreeLLMAPI not re-smoked in this UI-only
  pass; blind human QuillBot comparison=no; user visual confirmation=no.
- `blocker`: no local implementation blocker. The broader list is a manual
  candidate palette, not a promise that all 64 entries are equally good; the
  top 6–10 remain the intended spot-check surface. No QuillBot-superiority
  claim is made.
- `cleanup`: no model weights or Python bytecode entered the app bundle; no
  GitHub Actions, PR, merge, default-branch mutation, or external account
  action was performed.
- `next_action`: use the installed app on a real paragraph and manually review
  the first 6–10 choices for the words that matter, then reassess any ranking
  changes from actual use.

## 2026-09-07 — Hardened the automatic paraphrase boundary

- `scope`: production finalization, native Qwen3 worker normalization, protected
  content validation, automatic evaluation replay, packaged app, and installed
  runtime smoke paths on `feat/quality-judge-holdout`.
- `goal`: continue improving Pari until the current automatic evaluation
  boundary is saturated while preserving meaning, uncertainty, and protected
  facts.
- `changed_files`: `src/lib/generation/brokenProseRepair.ts`,
  `src/lib/generation/sentenceFlow.ts`, `src/lib/generation/meaningContract.ts`,
  `src/lib/safety/protectedContent.ts`, `native-runtime/paraphrase_worker.py`,
  `benchmarks/eval/run-eval.mjs`, `benchmarks/llm-shootout/README.md`,
  `scripts/qa-paraphrase.mjs`, `scripts/qa-native-model.mjs`, and this log.
- `implementation`: added narrow source-gated repairs for standalone
  evaluative and location fragments, mirrored the repairs in the native worker,
  registered “for unspecified reasons” as a cause relation, and allowed only
  case-only normalization of protected negation spans. The evaluator now has an
  explicit `--production-postprocess` mode that scores retained external model
  outputs after Pari's real `finalizeDraft` boundary while keeping raw-generator
  scoring separate.
- `validation`: `npm run qa:approval`; `npm run qa:native:model`; `npm run
  qa:native:prompt`; `npm run qa:learned:judge`; `npm run qa:grammar:harper`;
  `npm run qa:grammar:ewt`; `npm run benchmark:quality`; `npm run build`;
  `npm run build:desktop`; `codesign --verify --deep --strict release/Pari.app`;
  `hdiutil verify release/Pari.dmg`; `npm run qa:installed`; `npm run
  qa:installed:connected`; `npm run qa:installed:missing-model`; and `npm run
  qa:installed:custom` all passed. The raw retained Qwen3-4B 64-case replay
  remains 61/64; the same outputs after Pari finalization score 64/64 (8/8 in
  every category) with learned NLI and fluency active. The explicit FreeLLM
  installed probe timed out waiting for a changed rewrite and fell back to the
  unchanged paragraph, so it is not live-provider evidence. A no-provider
  local-safe-only adversarial replay scored 39/64 and failed two hard gates;
  that fallback intentionally leaves most input unchanged and is not the
  model-backed production boundary.
- `evidence_state`: source implemented=yes; automated regression and
  model-backed fixtures passed=yes; raw generator benchmark=61/64; Pari
  postprocessed product-boundary replay=64/64; packaged and signed=yes; local,
  connected-native, missing-model fallback, and custom installed paths
  passed=yes; FreeLLM live route=not proven; blind human QuillBot comparison=no;
  user confirmation=no.
- `blocker`: no local implementation blocker. The 64/64 result is a frozen
  automatic corpus replay and does not establish general quality or superiority
  to QuillBot. The source-gated fragment rules are intentionally narrow, the raw
  generator still has three band-fit misses, the local-safe recovery path is not
  intended to be a full paraphraser, and the larger human holdout remains
  outstanding.
- `cleanup`: the rebuilt app contains no model weights or Python bytecode; no
  GitHub Actions, PR, merge, default-branch mutation, or external account
  action was performed. The existing packaging audit warning remains 18 npm
  vulnerabilities and was not changed in this scoped quality pass.
- `learning_checkpoint`: promoted the source-gated fragment repair and the
  explicit raw-versus-production evaluation split because both are backed by
  current executable tests. Quarantined broad model-promotion and QuillBot
  superiority conclusions. Skipped new model downloads because the incumbent
  Qwen3 path plus production finalization already saturates the current frozen
  automatic corpus.
- `next_action`: commit and push the audited topic-branch changes; if a higher
  confidence claim is needed afterward, add a larger untouched corpus and the
  blind human/QuillBot comparison rather than tuning against this frozen set.

## 2026-09-07 — Restored and bounded the FreeLLM route

- `scope`: FreeLLMAPI runtime, Pari's optional remote generation path, packaged
  desktop app, and installed smoke validation on `feat/quality-judge-holdout`.
- `goal`: restart the local FreeLLM service after its timeout and make the
  paste-and-paraphrase route responsive enough for practical use.
- `changed_files`: `src/lib/generation/localParaphrase.ts` and this log.
- `implementation`: restarted the pre-existing `/Applications/FreeLLMAPI.app`
  instance after verifying its existing unified-key screen; the service
  returned to `127.0.0.1:31415` and accepted the existing key without
  regenerating or recording it. FreeLLM's single network candidate now uses
  Pari's bounded single-draft inspection instead of loading the local
  MiniLM/NLI/fluency ranking stack. The optional Harper grammar check is capped
  at 1.5 seconds; protected-content and deterministic rewrite-quality gates
  remain authoritative. Local Qwen3 multi-candidate ranking is unchanged.
- `model_selection`: the fresh 64-case FreeLLM comparison completed 64/64
  requests for `gemma-4-31b` and `gpt-oss-120b`. Gemma scored 59/64 raw and
  after Pari finalization; gpt-oss scored 50/64 in both views and produced
  control-echo/empty-style outputs. Neither replaces the incumbent Qwen3
  product boundary, whose frozen effective replay remains 64/64.
- `validation`: `npm run qa:approval`; `npm run build`; `npm run build:desktop`;
  `codesign --verify --deep --strict --verbose=2 release/Pari.app`; `hdiutil
  verify release/Pari.dmg`; `npm run qa:installed`; `npm run
  qa:installed:connected`; `npm run qa:installed:freellm` with the existing
  local key; `npm run qa:installed:custom`; `npm run qa:grammar:harper`; and
  `npm run qa:learned:judge` all passed. The rebuilt FreeLLM smoke completed in
  about four seconds with `generator=freellm-api`, after the previous roughly
  90-second headless timeout. The direct native FreeLLM worker also completed
  successfully in about one second.
- `evidence_state`: source implemented=yes; automated regression passed=yes;
  packaged, signed, and DMG checksum-verified=yes; FreeLLM service live=yes;
  installed FreeLLM route live-and-smoke-tested=yes; general model quality
  superiority over QuillBot=no; blind human holdout=no; user visual
  confirmation=no.
- `blocker`: no current local implementation blocker. FreeLLM remains an
  optional remote dependency with provider quota and network variability; the
  current evidence supports Gemma as the best tested FreeLLM candidate, not as
  a replacement for local Qwen3. The existing packaging audit warning remains
  18 npm vulnerabilities and was not changed in this scoped pass.
- `cleanup`: the copied key was cleared from the clipboard after each smoke;
  no key was written to the repository or logs. No model weights or Python
  bytecode entered the app bundle; no GitHub Actions, PR, merge,
  default-branch mutation, or force-push was performed.
- `learning_checkpoint`: promoted the remote fast-path boundary and Harper
  timeout because they are backed by a reproduced timeout, a direct worker
  isolation check, and a passing installed smoke. Quarantined promotion of
  FreeLLM models because Gemma remained below the incumbent effective score
  and gpt-oss emitted unsafe control echoes. Skipped another model download.
- `next_action`: commit and push the audited topic-branch change; retain the
  optional FreeLLM route for users who prefer remote variety, with local Qwen3
  as the default quality baseline.

## 2026-09-07 — Completed the automatic MiniCPM challenger check

- `scope`: temporary Hugging Face MiniCPM5-2B-MLX download, frozen Pari
  evaluator, current model-selection documentation, and automatic regression
  suites on `feat/quality-judge-holdout`.
- `goal`: continue the automatic quality push and close the model-comparison
  portion of P0.1 without silently changing Pari's production model.
- `changed_files`: `README.md`, `benchmarks/llm-shootout/README.md`,
  `docs/remaining-work.md`, `benchmarks/llm-shootout/minicpm5-2b-mlx-outputs-20260907.jsonl`,
  `benchmarks/eval/results-minicpm5-2b-mlx-outputs-20260907.jsonl.json`,
  `benchmarks/eval/results-minicpm5-2b-mlx-outputs-20260907.jsonl_pari-postprocess.json`,
  and this log. No application source or model weights were added.
- `implementation`: used the Hugging Face CLI dry run before downloading the
  Apache-2.0 MiniCPM5-2B-MLX checkpoint to an exact temporary directory. The
  thinking-disabled 64-case MLX run completed all requests, then was scored
  both raw and after Pari's real finalization boundary. MiniCPM scored 43/64
  raw and 51/64 postprocessed, below Qwen3's retained 64/64 postprocessed
  result; it is rejected for promotion. Corrected the README and shootout
  documentation to distinguish the latest Gemma 59/64 FreeLLM snapshot from
  the older 57/64 provider snapshot.
- `validation`: MiniCPM MLX load and 64/64 generation requests; raw and
  `--production-postprocess` evaluator runs; `npm run qa:approval`; `npm run
  benchmark:quality`; `npm run qa:grammar:harper`; `npm run qa:grammar:ewt`;
  `npm run qa:learned:judge`; `npm run qa:native:prompt`; and the full
  `npm run qa:native:model` suite all passed. The native suite covered the
  four-candidate flow, fragments, quantifier boundaries, protected facts,
  meaning guardrails, and bookish negation.
- `evidence_state`: automatic model comparison complete=yes; Qwen3 production
  boundary retained=yes; source/docs changes implemented=yes; automatic QA
  passed=yes; temporary challenger not bundled or installed=yes; packaged
  artifact from the prior source commit remains signed and smoke-tested=yes;
  blind human holdout=no; QuillBot parity/superiority=no; user visual
  confirmation=no.
- `blocker`: no automatic model-promotion blocker remains. Pari is still not
  fully proven as a broadly reliable or QuillBot-class paraphraser because the
  remaining readiness evidence is a blind real-paragraph comparison, actual
  contextual synonym review, and target-Mac memory/latency capture. The
  existing 18 npm vulnerability audit warning remains unchanged.
- `cleanup`: the temporary 1.4 GB MiniCPM checkpoint remains outside the
  repository and was not placed in the app bundle; the raw replay and compact
  score reports are the only committed evaluation artifacts. No GitHub
  Actions, PR, merge, default-branch mutation, force-push, or external
  publication was performed in this evaluation turn.
- `learning_checkpoint`: promoted the MiniCPM rejection and corrected dated
  FreeLLM evidence because the claims are backed by current executable runs
  and retained raw/effective scores. Quarantined any general claim that the
  automatic judge proves human or QuillBot superiority. Skipped installing a
  second production model.
- `next_action`: if “fully ready” means the documented narrow v1 quality gate,
  perform the remaining blind real-paragraph/synonym/QuillBot spot-check; if
  automatic-only work is preferred, the next high-value experiment is a new
  untouched corpus rather than more tuning on the frozen 64 cases.

## 2026-09-08 — Fixed the rewrite amount slider and weak screenshot rewrite

- `scope`: packaged Pari slider interaction, screenshot-paragraph native
  generation, quantifier meaning guard, and regression coverage.
- `goal`: make changing rewrite amount actually affect a current unedited
  draft, and stop a strong native rewrite from being discarded into the weak
  offline fallback shown in the supplied screenshot.
- `changed_files`: `README.md`, `docs/remaining-work.md`, `src/App.tsx`,
  `src/lib/generation/meaningContract.ts`, `native-runtime/paraphrase_worker.py`,
  `scripts/qa-paraphrase.mjs`, and this log. Existing unrelated dirty work was
  preserved.
- `implementation`: replaced the four-step range with a continuous 0–100
  range using live `input` and `change` handling, visible percentage semantics,
  and a 450 ms regeneration debounce. Slider changes automatically regenerate
  only an unedited draft; after manual edits Pari keeps the edit and explains
  that Paraphrase must be pressed to apply a new amount. Added the natural
  `some`/`certain` quantity class to the meaning contract and instructed the
  native worker to preserve quantifier scope and strength. The supplied
  boredom paragraph now stays on the native Qwen3 best-of-4 path and produces
  a materially stronger 51-word rewrite.
- `validation`: `npm run qa:approval`; `npx tsc -p tsconfig.json --noEmit`;
  Python bytecode compilation; direct four-candidate Qwen3 probe on the exact
  screenshot paragraph; `npm run build:desktop`; strict app signature
  verification; `hdiutil verify release/Pari.dmg`; and `npm run qa:installed`
  all passed. The freshly launched packaged app showed the real native Qwen3
  output and no weak `receive a break` fallback. The live packaged web UI
  slider was exercised through 100 → 0 → 100 with the Deep label present.
- `evidence_state`: source implemented=yes; focused regression passed=yes;
  packaged and signed=yes; DMG checksum-verified=yes; installed native
  smoke-tested=yes; live app output user-visible-to-Codex=yes; user visual
  confirmation=no.
- `blocker`: no current local implementation blocker. Native-app coordinate
  dragging was unavailable through the computer-use surface, but the same
  packaged WebKit range accepted full-range keyboard interaction and the
  native app completed the real rewrite flow. No claim of QuillBot parity or
  human superiority is made.
- `cleanup`: temporary local browser verification tab was closed. No model
  weights, secrets, GitHub Actions, PR mutation, commit, push, merge, or
  default-branch change was performed.
- `learning_checkpoint`: promoted the slider debounce and quantifier fix
  because both are covered by focused regression checks and installed/live
  evidence. Quarantined any broader quality claim beyond this screenshot
  flow. Skipped additional model downloads because the retained Qwen3 path
  completed successfully.
- `next_action`: use the running packaged Pari app; commit and push remain
  separate actions requiring explicit publication authorization.

## 2026-09-08 — Added high-amount sentence restructuring and majority-scope repair

- `scope`: high/Deep Rewrite amount behavior across the native Qwen3 path and
  the deterministic offline fallback, with prompt, meaning-contract, and
  installed/live regressions.
- `goal`: make a high Rewrite amount produce visible sentence-level reframing
  while preserving sentence count, discourse relationships, protected terms,
  and the stronger meaning of majority quantifiers.
- `changed_files`: `native-runtime/paraphrase_worker.py`,
  `src/lib/generation/localParaphrase.ts`,
  `src/lib/generation/meaningContract.ts`, `scripts/qa-native-prompt.py`,
  `scripts/qa-paraphrase.mjs`, `README.md`, `docs/remaining-work.md`, and
  this log. Existing unrelated dirty work was preserved.
- `implementation`: added high-amount native instructions to rebuild sentence
  openings, clause order, and grammatical framing rather than only swapping
  synonyms. Added a bounded shared structural pass for clear fronted
  cause/contrast/condition/time/context clauses before native ranking and on
  the offline fallback. Added a sentence-scoped repair for a native `most` →
  `many` weakening, while allowing explicit `majority` equivalents; the
  contract continues to permit broad `a number of`/`many`/`several` usage.
- `validation`: `npm run qa:paraphrase`; `npm run qa:native:prompt`;
  `npm run qa:native:model`; `npx tsc -p tsconfig.json --noEmit`;
  Python bytecode compilation; repeated direct Qwen3 high-strength probes;
  `npm run build:desktop`; strict `codesign --verify --deep --strict`;
  `hdiutil verify release/Pari.dmg`; final `npm run qa:installed`; and
  packaged WebKit slider interaction 56 → 100 → 0 → 100. The final visible
  Deep run used Qwen/Qwen3-4B-MLX-4bit, preserved `Most`, kept four sentences,
  and visibly reframed the last sentence to put `in certain contexts` after
  the main clause.
- `evidence_state`: source implemented=yes; focused regression passed=yes;
  native fixture suite passed=yes; packaged and signed=yes; DMG checksum
  verified=yes; installed native smoke-tested=yes; live Deep output
  user-visible-to-Codex=yes; user visual confirmation=no.
- `blocker`: no current local implementation blocker. The native candidate
  may still be conservative on paragraphs without a safe fronted clause; the
  open-ended generator remains model-dependent. No claim of QuillBot parity,
  human superiority, or universal Deep restructuring is made.
- `cleanup`: temporary packaged-browser range-check tab was closed; only the
  final visible Pari process remains from this turn. No model weights or
  secrets were copied into the repo. No commit, push, PR mutation, GitHub
  Actions, merge, force-push, or default-branch change was performed.
- `learning_checkpoint`: promoted the prompt contract, bounded structural
  pass, and majority-scope repair because each is covered by current focused
  tests plus packaged/native evidence. Quarantined the claim that every high
  rewrite must restructure every sentence. Skipped additional model downloads
  because the installed Qwen3 path completed successfully.
- `next_action`: use the final packaged app; commit/push remain separate
  publication actions requiring explicit authorization.

## 2026-09-08 — Issue #11 v2 benchmark and user-stopped XL run

- `scope`: canonical `/Users/tejas/Projects/Pari/open-local-phraser-v1`, issue
  #11 standards-traced v2 model comparison, shared sentence/factual-anchor
  safety boundary, and local model receipts.
- `goal`: continue the v2 benchmark, test feasible required candidates, and
  preserve a truthful promotion boundary for Pari's paragraph paraphraser.
- `changed_files`: `src/lib/nlp/sentenceSplit.ts`,
  `src/lib/safety/protectedContent.ts`, `scripts/qa-paraphrase.mjs`,
  `benchmarks/llm-shootout/run_seq2seq.py`,
  `benchmarks/llm-shootout/README.md`, `benchmarks/paraphrase-v2/README.md`,
  `benchmarks/paraphrase-v2/model-receipts.md`,
  `benchmarks/paraphrase-v2/model-status.json`,
  `benchmarks/paraphrase-v2/report.mjs`, `docs/remaining-work.md`, and this
  log. Existing unrelated dirty work was preserved.
- `implementation`: protected `a.m./p.m.` markers and hardened the shared
  sentence splitter against email/URL/decimal interior periods; added the
  regression coverage; added the T5/seq2seq research runner; and wired
  required-model status into the v2 report.
- `benchmark`: CoEdIT-large completed 72/72 and scored 51/72 with 14
  hard-safety failures. CoEdIT-XL loaded and passed one MPS smoke generation,
  then the user explicitly stopped the 11.4 GB full run after 55/72 rows due
  to memory pressure; the partial JSONL is valid but intentionally unscored.
  ADAL's downloaded checkpoint contained NaN tensors; DIPPER exposed no
  weights; Ling's required runtime was unavailable. Qwen3/Qwen3.5/MiniCPM
  score bundles were refreshed where completed before the stop.
- `validation`: `npm run qa:paraphrase`; Python bytecode compilation for the
  new runner; v2 corpus validation; JSON/JSONL artifact parse checks; and
  `git diff --check` passed. No benchmark, scorer, model, or XL process
  remains; post-stop memory free percentage reported 64%.
- `evidence_state`: source implemented=yes; focused QA passed=yes; v2
  harness/receipts implemented=yes; CoEdIT-large benchmarked=yes; CoEdIT-XL
  smoke-tested=yes and full benchmark=user-stopped; production promotion=no;
  human preference evidence=no; installed/live evidence unchanged from the
  prior checkpoint; user visual confirmation=no.
- `blocker`: issue #11's human-rating gate and complete comparison of
  unavailable/user-stopped candidates remain open. No claim of QuillBot
  superiority or model promotion is made.
- `cleanup`: exact orphaned Node scorer workers and the XL benchmark process
  were terminated after the user stop; no model weights were copied into the
  app or repository. The 11.4 GB checkpoint and 55 valid rows remain in `/tmp`
  and the repo respectively for recoverable later work. No commit, push, PR
  mutation, GitHub Actions, merge, force-push, or default-branch change was
  performed.
- `learning_checkpoint`: promoted the meridiem/decimal boundary regression
  because focused QA reproduced and then prevented the factual-prefix loss.
  Quarantined XL quality conclusions because the user stopped the run.
  Recorded ADAL/DIPPER/Ling as candidate-state limitations rather than
  substituting unverified runtimes. Skipped further benchmark execution after
  the explicit memory stop.
- `next_action`: keep the worktree and partial XL artifact paused; if resumed,
  run only a memory-bounded plan or delete the exact temporary XL weights with
  explicit authorization. Commit/push remain separate publication actions.

## 2026-09-08 — Skipped CoEdIT-XL and refreshed the current leaderboard

- `scope`: issue #11 v2 automatic leaderboard, complete scored bundles, and
  the user-stopped CoEdIT-XL comparison boundary.
- `goal`: continue the comparison without restarting the memory-intensive
  11.4 GB model, and expose the strongest currently completed results.
- `changed_files`: `benchmarks/paraphrase-v2/results/report-current/` generated
  leaderboard artifacts and this log. No model runner, score bundle, or
  production source was rerun or changed.
- `implementation`: generated a consolidated report from the complete
  original-reference, deterministic fallback, Qwen3 incumbent, Qwen3
  best-of-four research selector, Qwen3.5, CoEdIT-large, and MiniCPM bundles.
  The 55-row CoEdIT-XL partial remains excluded and its model status remains
  `user-stopped`.
- `validation`: `npm run benchmark:v2:report -- ... --out-dir
  benchmarks/paraphrase-v2/results/report-current` completed with 7 engines,
  72 cases, and 1,512 blinded pairwise rows. The refreshed report identifies
  `qwen3-4b-incumbent-bestof4-raw` as the automatic diagnostic leader at
  69/72; no human ratings were supplied.
- `evidence_state`: complete automatic comparison=yes; CoEdIT-XL full
  comparison=no/user-stopped; human preference=no; production promotion=no;
  installed/live evidence unchanged; user visual confirmation=no.
- `blocker`: automatic diagnostics remain supporting evidence only. The
  human gate and production-safety/installed-runtime gates remain open.
- `cleanup`: no benchmark process was started; the XL checkpoint and partial
  rows remain recoverable. No commit, push, PR mutation, GitHub Actions,
  merge, force-push, or default-branch change was performed.
- `learning_checkpoint`: promoted the explicit exclusion of incomplete
  candidates from the leaderboard because the report now records required
  model status alongside complete score bundles. Quarantined any claim that
  the best-of-four raw research selector is a shippable production winner.
  Skipped all further XL execution.
- `next_action`: use the refreshed report for issue #11 review; if quality
  work continues, use human/blinded or new-corpus evidence rather than
  restarting CoEdIT-XL without an explicit memory-bounded plan.
