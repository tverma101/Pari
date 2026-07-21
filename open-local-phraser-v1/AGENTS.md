# Open Local Phraser V2.1

## Canonical

Canonical macOS phrasing tool. Experimental rewrite at `open-local-phraser-v1-safe-rewrite-lab/`.

## Build

```bash
./build_dmg.sh          # Package into DMG for distribution
```

## Stack

- TypeScript (Vite), Xenova transformers for sentence embedding
- macOS wrapper (web app packaged as native app, loads under `file://`)

## Architecture

- Local rule-based rewrite engine + static synonym/phrase bank
- Optional sentence-embedding ranking with `Xenova/all-MiniLM-L6-v2`
- No generative LLM included

## Generated files (untracked)

- `dist/` — build output
- `release/` — packaged releases (DMGs)
- `node_modules/` — dependencies
- `public/models/Xenova/` — downloaded transformer model files (gitignored)
