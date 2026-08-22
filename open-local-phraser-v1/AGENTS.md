# Open Local Phraser

This directory is the canonical production app. Do not implement production behavior in `../open-local-phraser-v1-safe-rewrite-lab/`.

## Architecture

- React 19 + TypeScript + Vite frontend.
- Swift/AppKit/WKWebView desktop wrapper.
- One local-first paragraph workflow with a bundled native MLX generator and a deterministic local-safe fallback; never add a remote fallback.
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

The native path is configured in `native-models/config.json` (env `PARI_NATIVE_MODEL_ID` / `PARI_NATIVE_MODEL_PATH` override). Qwen3.5-4B is the current **incumbent/control only** — do not bake Qwen strings into new code. See `benchmarks/llm-shootout/README.md` (Ling-3.0-tiny challenger: 7.9B/1.3B active, ~4.2GB MLX-4bit via rapid-mlx) and `benchmarks/quillbot/README.md`. Describe the native path as primary only when packaged loading and installed headless evidence pass. The `local-safe-engine` remains deliberately bounded and deterministic. Do not claim "beats QuillBot" until the frozen 300-500+ held-out benchmark (#8) passes on the hardened English-quality judge (#7) without higher meaning/invention failures (ro-04 regression is the canonical false-pass).
