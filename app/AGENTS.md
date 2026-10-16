# Pari

This directory is the Mac app. The plan is in `../docs/PLAN.md`. Benchmark code is in `../bench/`, Kaggle notebooks in `../kaggle/`, and model conversion in `../model/`.

The end state is a quantized model running on the Mac through the local MLX path below, so local-generator work is allowed again. Until the Word Studio benchmark picks a model, Qwen3-4B stays the default; do not change the default model without that decision.

## Architecture

- React 19 + TypeScript + Vite frontend.
- Swift/AppKit/WKWebView desktop wrapper.
- One local-first paragraph workflow with a bundled native MLX generator and a deterministic local-safe fallback; an explicitly selected FreeLLMAPI route may be used when the user opts in, but it must never become an implicit fallback or silently replace the local path.
- Personal and Warmth are the supported visible styles. They share approval memory, protected-content validation, and grammar/flow gates.
- Transient `ParaphraseSession` state until explicit approval.
- Protected-content validation before generation display and approval.
- Native Application Support persistence for approved records and preference memory.
- IndexedDB is a browser-only development fallback; it is not the packaged app database.

## Required checks

```bash
npm run build
npm run qa:approval
npm run build:desktop
```

Keep the old synonym/token helpers where they support contextual replacements. Keep the style selector compact and user-facing, but do not expose technical ranking selectors, model internals, background mutation, or user-facing training concepts.

The native path is configured in `native-models/config.json` (env `PARI_NATIVE_MODEL_ID` / `PARI_NATIVE_MODEL_PATH` override). Qwen3-4B is the production default until the benchmark decides. The optional FreeLLMAPI route is configured only through environment variables and is not a local fallback. Do not bake model identifiers into new code. Describe the native path as primary only when packaged loading and installed headless evidence pass. The `local-safe-engine` remains deliberately bounded and deterministic. Do not claim quality parity with QuillBot or any other tool without benchmark evidence.
