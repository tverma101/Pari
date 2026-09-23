#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

node validate-english-core.mjs
node audit-english-core-shadow.mjs
node test-english-core-choice-parser.mjs
python3 test_english_core_choice_parser.py

# Builders below require no model and verify that the model-visible task lanes can
# be regenerated from the private seed without throwing or exposing gold labels.
node build-english-core.mjs >/dev/null
node build-english-core-prompt-robustness.mjs >/dev/null
node build-english-core-choice-order-robustness.mjs >/dev/null

python3 - <<'PY'
import json
from pathlib import Path

for name in [
    "english-core-shadow.jsonl",
    "english-core-prompt-robustness.jsonl",
    "english-core-choice-order-robustness.jsonl",
]:
    rows = [json.loads(line) for line in Path(name).read_text().splitlines() if line.strip()]
    assert rows, f"{name}: no generated tasks"
    ids = [row["id"] for row in rows]
    assert len(ids) == len(set(ids)), f"{name}: duplicate IDs"
    for row in rows:
        forbidden = {"answer", "expected", "gold", "goldLabel", "expectedLetter", "goldBaseChoiceIndex"}
        leaked = forbidden.intersection(row.keys())
        assert not leaked, f"{name}:{row['id']} leaked gold fields {sorted(leaked)}"
        assert isinstance(row.get("prompt"), str) and row["prompt"].strip(), f"{name}:{row['id']} missing prompt"
PY

printf '%s\n' 'English Core structural self-check passed.'
