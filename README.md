# Pari

Pari is a local-first paraphrasing tool for macOS. This repository holds the
product and its supporting workspaces.

## Layout

| Folder    | Purpose |
|-----------|---------|
| `app/`    | Canonical production app: React/TypeScript/Vite frontend, Swift/WKWebView desktop wrapper, benchmarks, docs. See `app/AGENTS.md`. |
| `lab/`    | Safe Rewrite Lab — non-canonical experimental engine sandbox. See `lab/README.md`. |
| `inspect/` | Separate standalone repo holding frozen copies of earlier project folders for inspection/diffing. Its internal folder names are historical on purpose. |

Build artifacts land in `app/release/` (`Pari.app`, `Pari.dmg`); superseded
builds are moved to `app/release/archive/`.

## Common commands

```bash
cd app
npm ci            # first setup
npm run build     # frontend build
npm run build:desktop   # Pari.app + Pari.dmg via build_dmg.sh
npm run qa:approval     # headless QA
```

Names that are intentionally NOT renamed (runtime identifiers, renaming would
orphan user data): the `open-local-phraser-approval-memory` IndexedDB name,
the `open-local-phraser-v2.settings` localStorage key, the
`OpenLocalPhraserV2` executable, the `com.tejas.openlocalphraser` bundle ID,
and `~/Library/Application Support/Open Local Phraser/`.
