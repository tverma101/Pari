# Pari

Pari is a local-first paraphrasing tool with shared Personal and Warmth styles. It produces one editable rewrite, offers compact contextual suggestions, repairs malformed prose, and learns only from text the user explicitly approves.

## Product behavior

- One `Paraphrase` action produces one stable draft.
- The draft is directly editable and can be pasted over.
- Highlighted words expose a scrollable local palette of up to 64 ranked
  contextual/dictionary alternatives when enough safe choices exist.
- `Save & learn` validates protected content, stores the original/final pair, and updates preference memory.
- `Discard`, copy, abandoned drafts, and failed approvals save and learn nothing.
- Generation requests can be cancelled, and stale requests cannot replace newer output.
- Personal keeps the writer's voice warm, clear, and explanatory. Warmth makes robotic, cynical, or unnecessarily cold wording noticeably more human while preserving honest negative facts and the writer's intent. Both styles use the same learned approval memory and grammar/protection gates.
- The continuous 0–100 Rewrite amount control bounds how much wording changes without exposing technical ranking controls. Light, Balanced, Strong, and Deep use aligned rewrite budgets and progressively stronger phrase/context selection; Deep also requests paragraph-level restructuring. On an unedited draft, changing it regenerates the draft after a short debounce; manual edits are preserved until the user presses Paraphrase.
- The packaged macOS app includes standard Edit and Window menus, native Command-C/V/X/A shortcuts, Undo/Redo, and an NSPasteboard bridge for the in-app Copy and Paste actions.

## Local persistence

The packaged WKWebView sends approved records and preference memory to the Swift wrapper. The wrapper stores one atomically-written state file under:

```text
~/Library/Application Support/Open Local Phraser/approved-state.json
```

Browser development uses IndexedDB only as a local fallback when the native bridge is unavailable. Approved text is never stored in `localStorage`.

## Safety

The protection layer snapshots URLs, email addresses, numbers, dates, times, currency, percentages, citations, quotes, names, list markers, negation, and modality. Generated and edited text must preserve those spans before approval. A candidate that fails validation falls back to the original text.

## Build and verify

```bash
npm ci
npm run models:download
npm run models:install                 # optional: connect the configured model outside Pari.app
npm run models:check
npm run build
npm run qa:approval
npm run qa:learned:judge
npm run qa:native:model
npm run qa:native:prompt
npm run benchmark:quality
npm run research:grammar:download
npm run research:grammar:check
npm run build:desktop
# optional: explicit FreeLLMAPI route smoke, with PARI_FREELLM_API_KEY set in the shell
# npm run qa:installed:freellm
```

The model downloader restores the twelve pinned local bundles in the
development checkout: eleven ONNX models used for semantic checks, entity
protection, contextual word suggestions, learned NLI, and learned fluency,
plus the configured Apache-2.0 native paragraph generator. Qwen3-4B is the
production incumbent; Qwen3.5-4B remains the general-model benchmark control,
while MiniCPM5-2B and Ling-3.0-tiny are challengers. `npm run
models:download` transfers the bundles in parallel, writes manifests with
SHA-256 hashes, and repairs incomplete or corrupt files.
`npm run models:download:native` is the explicit opt-in command that downloads
only the configured native generator into
`~/Library/Application Support/Open Local Phraser/Models/`, outside the app.
`npm run models:install` copies a previously verified checkout model to that
same external location without downloading it again.

`npm run build` verifies the checkout models before copying the browser models
into the web bundle. `build:desktop` deliberately does not copy the native
generator checkpoint into `Pari.app` or the DMG; it ships only the one-shot
native worker.
At runtime Pari discovers a complete external model through
`PARI_NATIVE_MODEL_PATH` or the Application Support location above. If it is
missing, incomplete, unreadable, or the Python/MLX runtime is absent, Pari keeps
the deterministic local-safe engine active and displays an actionable
connection message. The packaged app makes no remote model requests by itself.

`qa:approval` covers protected content, 6–10 synonym choices, grouped edit compression, approval-only preference learning, approved-example retrieval, safe local generation, cancellation-safe APIs, and five warm latency samples.

`qa:native:model` runs local MLX fixtures through the bundled generator: the screenshot-style Personal paragraph, a Warmth register probe, severely broken prose, adversarial “nuclear” notes, protected dates/URLs/emails/currency, meaning-marker guardrails, direct-English filler repair, bookish-negation repair, and quantifier/sentence-boundary repair. One fixture also carries bounded approved style context through the worker. It checks output hygiene, grammar repair, protected anchors, sentence-flow behavior, and noticeable Warmth transformation.

`qa:native:prompt` checks the native prompt contract without loading the checkpoint. It verifies that approved local examples, learned wording preferences, contraction/sentence-shape preferences, and reverted phrases cross the Swift bridge as bounded style context, while the current paragraph remains the only source of facts.

`benchmark:quality` runs the supplied communication reflection as a 747-word regression fixture alongside 12 varied samples through Personal at four rewrite amounts. It checks protected anchors, sentence-count preservation, obvious collocation/grammar artifacts, lexical change rate, and per-sample latency.

`qa:grammar:harper` exercises the bundled offline Harper WASM grammar checker
against representative agreement and article errors. Harper runs only on the
edited text, adds diagnostics to Pari's existing hard-rule checks, and fails
closed to those built-in checks if its optional runtime cannot initialize.

`qa:grammar:ewt` runs the hard grammar validator against 2,000 held-out
sentences from the pinned UD English EWT test split and enforces bounded
high/medium-severity rates so new rules do not over-warn clean natural English.

`build:desktop` builds the Vite bundle, compiles the Swift/WKWebView wrapper, creates an ad-hoc signed `.app`, and creates a DMG without embedding the native generator, downloading a model, or contacting a remote model service.

`npm run qa:installed` runs the fresh lean packaged app with a hidden,
accessory-only window. It exercises the real installed UI, the screenshot-style
paragraph, the disconnected-model fallback, contextual model choices, and
grammar highlighting without activating, closing, or taking focus from a
visible Pari window. `npm run qa:installed:connected` runs the same packaged
app with `PARI_NATIVE_MODEL_PATH` pointed at the separately stored checkout
model and requires native MLX generation. The wrapper serves the bundle from a
loopback-only local HTTP origin; its CSP allows only that private origin and the
app makes no remote model requests.

`npm run qa:installed:missing-model` runs the same hidden installed workflow
with a deliberately absent native path. It verifies that Pari selects the
deterministic local-safe-engine fallback and exposes an actionable “model is
not connected” recovery notice instead of leaving the Paraphrase action dead.

The optional FreeLLMAPI route is explicit and quota-aware. FreeLLMAPI must be
running locally, and the key is supplied only through the process environment;
Pari does not persist it in the repository, app bundle, or approval state. The
route sends one remote draft per generation and at most one stricter repair
request when Pari's existing protected-content, meaning, grammar, and flow
gates reject the first draft. A failed or rejected remote request falls back to
the deterministic local-safe engine; the normal local Qwen3 route remains the
default when this is not enabled.

```bash
export PARI_GENERATION_BACKEND=freellm
export PARI_FREELLM_BASE_URL=http://127.0.0.1:31415/v1
export PARI_FREELLM_API_KEY='paste-the-FreeLLMAPI-unified-key-here'
export PARI_FREELLM_MODEL=gemma-4-31b
npm run build:desktop
npm run qa:installed:freellm
```

The selected FreeLLMAPI model is `gemma-4-31b`. In the latest 2026-09-07
64-case rerun it scored 59/64 (92%) both raw and after Pari finalization;
`gpt-oss-120b` scored 50/64 (78%) and exposed control-text/empty-style
responses, so it was rejected. An earlier provider snapshot recorded Gemma at
57/64 and Llama 3.3 70B at 59/64; those results are retained as dated research
evidence because free-provider routing can change. Gemma remains an optional
remote candidate, not a claim that FreeLLM beats the local Qwen3 incumbent or
QuillBot. The benchmark also quarantined Qwen3.6 for visible thinking plus a
provider token-rate cap, and listed models that returned provider-side
404/502/503 responses. Free-tier availability and provider limits are live
service state; confirm them in the [FreeLLMAPI model catalog](https://freellmapi.co/models) before changing the configured model.

The expanded frozen 300-case holdout is the stronger current automatic check:
Qwen3 scored 222/300 raw and 228/300 after the real Pari finalizer. A
production-schedule best-of-four replay with the exact protected-content gate
scored 227/300, so candidate sampling did not justify changing the default.
These are engineering signals, not human-quality or QuillBot-parity claims;
the held-out results and raw replays live under
[`benchmarks/llm-shootout/`](benchmarks/llm-shootout/).

Pari also ships a separate local agent style backend. Run `npm run backend:styles` or `./script/build_and_run.sh --agent-style-backend` to start only the loopback API; it prints an ephemeral `127.0.0.1` URL, persists validated custom styles to `~/Library/Application Support/Open Local Phraser/custom-styles.json`, and exits after ten minutes without activity. Set `PARI_AGENT_STYLE_IDLE_TIMEOUT_SECONDS=60` for a shorter session. This mode does not create a WebKit window or change the visible app's rewrite behavior. The API supports `GET /health`, `GET /v1/styles`, `POST /v1/styles`, `PATCH /v1/styles/:id`, `DELETE /v1/styles/:id`, and `POST /v1/shutdown`. A style body contains `name`, `description`, `instructions`, `baseMode` (`personal` or `warmth`), `strength` (0–100), and optional bounded `tweaks` (`strengthOffset` -24…24, `warmthPolish`, and `preserveSentenceCount`). Saved styles appear as custom modes in Pari on the next load/focus refresh. Every custom mode routes through the same shared protection, grammar, flow, native-model, critic, fallback, and approval-learning engine; custom instructions and tweaks only add bounded preferences. `npm run qa:agent:styles` verifies headless startup, CRUD persistence, validation boundaries, and idle shutdown against the packaged binary. `npm run qa:installed:custom` additionally creates an agent style, launches the installed app headlessly, connects the separately stored model, selects that saved mode, and verifies native MLX generation plus the existing UI probes before cleaning it up.

The rewrite quality gates also check sentence-flow preservation, known-to-new information order, parallel verb series (including conservative repair of simple mixed gerund lists), vague sentence openings, safe concision of padded phrases, protected spans, approval-only learning, model control-text echoes, duplicate punctuation, note-fragment repair, direct-English filler removal, collocations/verb frames, broad plural-noun and determiner-led sentence-boundary agreement, and a conservative meaning contract for negation, modality, quantity, discourse relationships, and point of view. High/Deep amounts additionally ask the native generator for paragraph-level sentence restructuring; the offline fallback applies only bounded, relationship-preserving fronted or trailing clause/context moves, method-phrase movement, and a small safe subject recast. Phrase-level alternatives are filtered by collocation and sentence context, then repaired or rejected by the same final quality gates. High-severity hard grammar defects are never accepted in a generated candidate, even when the source already contains a defect of the same class. A rejected native draft receives one stricter local critic/repair pass before the deterministic fallback is used. These checks follow established revision guidance on sentence clarity and purposeful variety from [Purdue OWL](https://owl.purdue.edu/owl/graduate_writing/introduction_to_writing/documents/revising-and-editing/sentence-clarity-transcript.pdf) and cohesion/parallel structure from the [George Mason University Writing Center](https://writingcenter.gmu.edu/writing-resources/grammar-style/improving-cohesion-the-known-new-contract).

`research:grammar:download` fetches four pinned, license-tracked development snapshots in parallel: Harper for rule research alongside the bundled `harper.js` runtime, LanguageTool for broad rule coverage research, GECToR for edit-tagging correction research, and UD English EWT for held-out grammar-flow evaluation. They live under `research/grammar-sources/`, do not receive user text, and the research snapshots are not themselves bundled into the app. See [`research/quality-roadmap.md`](research/quality-roadmap.md) and [`research/grammar-sources/README.md`](research/grammar-sources/README.md) for the 80/20 quality plan and shipping constraints.

The output editor also runs a local grammar/flow diagnostic after generation and after manual edits. Agreement, quantifier-head agreement, sentence boundaries, article, modal-verb, pronoun-case, repetition, common forms such as “could have”/“a lot,” and similar hard issues receive warning underlines and a short status count; contextual word choices, citation-safe sentence revert, and direct editing remain available.

## Current backend boundary

The production desktop path currently uses an optional external Qwen/Qwen3-4B-MLX-4bit checkpoint launched through the one-shot local MLX worker. Qwen3.5-4B is currently the **general-model benchmark control** in `benchmarks/llm-shootout`; MiniCPM5-2B and Ling-3.0-tiny are challenger checkpoints. Keeping benchmark control, production backend, challengers, and the explicit remote route separate lets new models and grammar-specialist cascades compete without silently changing the app.

The tracked `native-models/config.json` is the source of truth for the model
ID, local path, required files, and runtime. `PARI_NATIVE_MODEL_ID` and
`PARI_NATIVE_MODEL_PATH` are explicit overrides. The local worker is isolated
from WebKit, receives the selected style, repairs malformed prose, and never
receives remote requests. When `PARI_GENERATION_BACKEND=freellm` is explicitly
set, a separate one-shot worker calls the local FreeLLMAPI-compatible endpoint
using `PARI_FREELLM_BASE_URL`, `PARI_FREELLM_API_KEY`, and
`PARI_FREELLM_MODEL`; the API key remains process-only. The packaged app contains no native weights. It
looks first at the absolute `PARI_NATIVE_MODEL_PATH`, then at the configured
model under `~/Library/Application Support/Open Local Phraser/Models/`, and
retains compatibility with older development bundles. If the model is not
connected, Python/MLX is absent, generation times out, or a draft fails
protected-content/grammar/flow gates, Pari explains the failure and uses the
bounded `local-safe-engine` fallback. The fallback remains intentionally
conservative: it now covers selected phrase-level/contextual repairs and a few
meaning-preserving high-strength structural moves, but it cannot match the
native model on open-ended structural repair.

The production quality judge is also local-only: bundled DeBERTa-v3-xsmall
provides bidirectional NLI and bundled DistilBERT masked-LM scoring provides a
separate fluency signal. `npm run qa:learned:judge` must prove both assets ran;
if either asset is unavailable, the evaluator reports the explicit fallback
state instead of presenting a heuristic score as learned quality.
