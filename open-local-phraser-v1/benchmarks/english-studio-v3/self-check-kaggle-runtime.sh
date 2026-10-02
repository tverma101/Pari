#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

python3 test_kaggle_edge_cases.py
python3 test_protocol_output_diagnostics.py
python3 test_resume_contract.py

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

# The transform suite is public product-acceptance structure, so rebuild it into
# a temporary directory and verify its contract without modifying the checkout.
python3 build-word-studio-transform-suite.py \
  --output "$TMP_DIR/transform.jsonl" \
  --manifest "$TMP_DIR/transform.manifest.json" \
  --private-review-key "$TMP_DIR/transform.private-review.json" >/dev/null

python3 - "$TMP_DIR" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
rows = [json.loads(x) for x in (root / "transform.jsonl").read_text().splitlines() if x.strip()]
manifest = json.loads((root / "transform.manifest.json").read_text())
assert len(rows) == 100, len(rows)
assert manifest["cases"] == 100
assert len({r["id"] for r in rows}) == 100
assert all(r.get("requestedCount") == 10 for r in rows)
assert all(r.get("sourceText") and r.get("selectedText") for r in rows)
assert any(r.get("semanticMode") == "intentional_compression" for r in rows)
assert all("requirements" not in r and "expectations" not in r for r in rows)
PY

printf '%s\n' 'Kaggle runtime/resume/product-suite self-check passed.'
