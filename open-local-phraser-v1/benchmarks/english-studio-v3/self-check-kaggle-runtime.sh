#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

python3 - <<'PY'
from pathlib import Path
import py_compile
for path in sorted(Path('studio_backend').glob('*.py')):
    py_compile.compile(str(path), doraise=True)
PY

python3 test_kaggle_edge_cases.py
python3 test_protocol_output_diagnostics.py
python3 test_resume_contract.py
python3 test_studio_backend.py

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

execution = json.loads(Path("kaggle-execution-manifest.json").read_text())
stages = {row["id"]: row for row in execution["normalDecodeStages"]}
assert stages["protocol-smoke"]["expectedCases"] == 16
assert stages["english-core-fixed"]["expectedCases"] == 1943
assert stages["word-studio-transform"]["expectedCases"] == 100
assert stages["word-studio-strength"]["expectedCases"] == 112
assert execution["expectedNormalDecodeTaskExecutionsIncludingSmoke"] == 2171
assert execution["expectedQualityOrProductTaskExecutionsExcludingSmoke"] == 2155

smoke = [json.loads(x) for x in Path("kaggle-protocol-smoke.jsonl").read_text().splitlines() if x.strip()]
assert len(smoke) == 16
assert len({r["id"] for r in smoke}) == 16
assert any(r.get("generative") for r in smoke)
assert any(not r.get("generative") for r in smoke)
PY

printf '%s\n' 'Kaggle runtime/resume/product-suite/Studio self-check passed.'
