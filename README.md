# Pari

Pari is a Mac writing assistant for school and college essays. Paste a
paragraph, tap any word or select a sentence, and Pari shows many options that
fit the context. You always pick the final words. The plan is in
[`docs/PLAN.md`](docs/PLAN.md).

## Layout

| Folder    | Purpose |
|-----------|---------|
| `app/`    | Mac app: React/TypeScript/Vite frontend and Swift/WKWebView desktop wrapper. See `app/AGENTS.md`. |
| `bench/`  | Word Studio benchmark: tasks, Kaggle runners, scoring. |
| `kaggle/` | Kaggle notebooks for candidate runs, data generation and training. |
| `model/`  | Quantizing (and, only if needed, distilling) the chosen model to MLX for the Mac. |
| `docs/`   | The plan and the decisions log. |

Earlier experiments (`lab/`, the old `app/benchmarks` suites, `app/research/`)
are kept on branch `archive/2026-10` and tag `archive-2026-10`.

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

```bash
cd bench/word-studio
python3 -m unittest discover -p 'test_*.py'   # benchmark unit tests
```

Names that are intentionally NOT renamed (runtime identifiers, renaming would
orphan user data): the `open-local-phraser-approval-memory` IndexedDB name,
the `open-local-phraser-v2.settings` localStorage key, the
`OpenLocalPhraserV2` executable, the `com.tejas.openlocalphraser` bundle ID,
and `~/Library/Application Support/Open Local Phraser/`.
