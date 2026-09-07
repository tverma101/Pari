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
