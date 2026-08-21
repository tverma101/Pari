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

The bundled native path is Qwen/Qwen3-4B-MLX-4bit launched by the packaged Swift worker. Describe the native path as primary only when packaged loading and installed headless evidence pass; keep all target-device latency and runtime prerequisites honest. The `local-safe-engine` remains deliberately bounded and deterministic.
