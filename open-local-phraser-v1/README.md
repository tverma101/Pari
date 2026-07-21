# Open Local Phraser V2.1

Open Local Phraser V2.1 is a compact macOS phrasing tool with:

- A local rule-based rewrite engine
- A static synonym and phrase bank
- Optional sentence-embedding ranking with `Xenova/all-MiniLM-L6-v2`
- A bundled macOS desktop wrapper that packages the full web app and local model files

This app does not include a generative LLM.

## V2.1 Hardening Summary

- Vite now builds relative asset URLs so the packaged app can load under `file://`
- The desktop wrapper loads `Contents/Resources/web/index.html` with directory-wide read access
- The packaged app logs startup diagnostics for `Resources`, `web/index.html`, `assets/`, and the bundled model directory
- The frontend shows a visible startup error card if React crashes during boot instead of failing to a blank white screen
- `Xenova/all-MiniLM-L6-v2` is bundled under `public/models/...` and copied into the packaged app
- Semantic ranking still lazy-loads and remains optional
- The app keeps working if semantic loading fails; alternatives fall back to rule-based ranking

## Dev

```bash
npm ci
npm run models:download
npm run models:check
npm run dev
```

## Model Download And Validation

```bash
npm run models:download
npm run models:check
```

`npm run models:download`:

- Resolves the required Transformers.js files for `Xenova/all-MiniLM-L6-v2`
- Downloads them into `public/models/Xenova/all-MiniLM-L6-v2/`
- Writes `manifest.json` for bundled-model detection
- Skips existing files unless `--force` is passed to `scripts/download-models.mjs`

`npm run models:check`:

- Loads the local bundled model from `public/models/`
- Runs a real embedding pass on three test sentences
- Verifies the related-sentence similarity is higher than the unrelated-sentence similarity

Latest local check result:

- Vector length: `384`
- `similarity(sentence1, sentence2)`: `0.933664`
- `similarity(sentence1, sentence3)`: `0.058350`
- Result: `PASS`

## Build The DMG

```bash
npm ci
npm run models:download
npm run models:check
npm run build
npm run build:desktop
```

`npm run build:desktop` rebuilds the frontend, validates the bundled MiniLM model again, creates `release/Open Local Phraser V2.app`, and then creates `release/Open Local Phraser V2.dmg`.

## Model Behavior

- Rule-based ranking is the default mode and does not load any embedding model on startup.
- Semantic ranking only loads when the user enables semantic ranking or runs the model self-test.
- The app prefers bundled local files first:
  - `models/Xenova/all-MiniLM-L6-v2/tokenizer.json`
  - `models/Xenova/all-MiniLM-L6-v2/tokenizer_config.json`
  - `models/Xenova/all-MiniLM-L6-v2/config.json`
  - `models/Xenova/all-MiniLM-L6-v2/onnx/model_quantized.onnx`
- When bundled files are present, the app fetches tokenizer/model artifacts from the local packaged path and uses local ONNX wasm assets from `dist/assets`.
- If bundled files are missing, the app attempts a remote/cache fallback.
- If semantic ranking cannot load, the app stays up and the alternatives popup falls back to rule-based ordering.

Offline behavior:

- With bundled model files present, packaged semantic ranking works without downloading from Hugging Face.
- The preferred and validated V2.1 path is the bundled local model.
- If bundled files are absent, remote fallback depends on network availability and browser cache state.

## Troubleshooting

### White Screen In The Packaged App

The V2 white-screen root cause was Vite emitting absolute `/assets/...` paths into `dist/index.html`. Under packaged `file://` loading, the app bundle contained the assets, but `WKWebView` could not resolve absolute paths.

V2.1 fixes:

- `vite.config.ts` sets `base: "./"`
- The app bundle copies the full `dist/` folder into `Contents/Resources/web/`
- `WKWebView` loads `index.html` with:

```swift
webView.loadFileURL(indexURL, allowingReadAccessTo: webDirectory)
```

If the packaged app still fails:

- Check `Contents/Resources/web/index.html`
- Check `Contents/Resources/web/assets/`
- Launch the app binary directly and inspect the startup logs printed by `main.swift`

### Missing Assets

Confirm these paths exist in the built app bundle:

```text
Open Local Phraser V2.app/
  Contents/
    Resources/
      web/
        index.html
        assets/
        models/
```

### Model Download Failure

- Re-run `npm run models:download`
- Re-run `npm run models:check`
- Confirm `public/models/Xenova/all-MiniLM-L6-v2/manifest.json` exists
- Confirm the packaged app contains `Contents/Resources/web/models/Xenova/all-MiniLM-L6-v2/`

### Semantic Fallback

If semantic ranking fails:

- The app keeps rendering
- Settings show the failure status and error message
- Popup alternatives fall back to rule-based ranking instead of crashing

## RAM Budget And Measurements

Targets:

- Base app under `1 GB`
- Semantic mode under `6 GB`

Measured with local process RSS tooling:

- Packaged app idle, rule-based startup: about `67-69 MB RSS`
- Headless browser smoke harness, built `dist/` bundle, rule-based after rewrite: about `1.00 GB RSS`
- Headless browser smoke harness, semantic model ready with bundled MiniLM: about `1.36 GB RSS`
- Headless browser smoke harness, repeated semantic popup reranking: about `1.31 GB RSS`

Notes:

- The packaged app idle number is from the release `.app` binary launched directly.
- The semantic-path numbers are from a headless Firefox smoke harness running the exact built `dist/` bundle and bundled MiniLM assets. This terminal session could not surface an onscreen `WKWebView` window, so direct packaged-app semantic RSS could not be sampled here.
- The measured semantic path stayed well below the `6 GB` cap.

## Known Limitations

- No generative model support
- No OpenAI, Ollama, LM Studio, RAG, training, or document import/export features
- Remote fallback is best-effort when bundled files are absent; the bundled local path is the validated production path
- The footer keeps showing semantic status even when popup ranking has fallen back to rule-based ordering after a model failure
