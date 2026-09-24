#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

# The benchmark tooling is part of the measurement instrument. Syntax-check all
# local Python and Node modules before trusting any model result. This is a
# structural regression check only; it does not execute optional public-dataset or
# model dependencies.
python3 - <<'PY'
from pathlib import Path
import py_compile

for path in sorted(Path('.').glob('*.py')):
    py_compile.compile(str(path), doraise=True)
PY

for module in ./*.mjs; do
  node --check "$module" >/dev/null
done

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

# Regression-test the promotion validator itself. A complete, internally
# consistent synthetic result must pass; changing an output without updating its
# recorded raw-output hash must fail. This exercises result-integrity logic without
# requiring MLX, a model download, or public datasets.
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
python3 - "$TMP_DIR" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
task = {"id": "fixture-1", "prompt": "Choose A or B.\nA. alpha\nB. beta\nAnswer only with the letter.", "generative": False}
task_path = root / "tasks.jsonl"
task_bytes = (json.dumps(task) + "\n").encode("utf-8")
task_path.write_bytes(task_bytes)

outputs = [{
    "id": "fixture-1",
    "output": "A",
    "latencySeconds": 0.0,
    "promptAdaptation": "plain",
    "promptAdaptationDetail": "none",
}]
raw_hash = hashlib.sha256(json.dumps(outputs, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

run = {
    "runId": "self-check-fixture",
    "model": {
        "name": "fixture-model",
        "repoOrName": "fixture/model",
        "revision": "fixture-revision-1",
        "artifactSha256": "a" * 64,
        "quantization": "full",
        "checkpointType": "base",
        "runtime": "fixture-runtime",
        "runtimeVersion": "1.0.0",
        "tokenizerName": "fixture-tokenizer",
        "chatTemplate": "none/plain",
        "chatTemplateSha256": None,
    },
    "taskFile": str(task_path),
    "taskFileSha256": hashlib.sha256(task_bytes).hexdigest(),
    "taskCount": 1,
    "promptModeRequested": "plain",
    "promptAdaptationModesObserved": ["plain"],
    "promptAdaptationDetailsObserved": ["none"],
    "decoding": {
        "temperature": 0.0,
        "topP": 1.0,
        "topK": 0,
        "maxNewTokens": 8,
        "forcedChoiceMaxNewTokens": 8,
        "seed": 0,
    },
    "outputs": outputs,
    "reproducibility": {
        "benchmarkRevision": "fixture-benchmark-revision",
        "rawOutputSha256": raw_hash,
        "notes": [],
    },
}
(root / "valid.json").write_text(json.dumps(run, indent=2) + "\n")

tampered = json.loads(json.dumps(run))
tampered["outputs"][0]["output"] = "B"
(root / "tampered.json").write_text(json.dumps(tampered, indent=2) + "\n")
PY

python3 validate-english-core-run.py "$TMP_DIR/valid.json" --promotion >/dev/null
if python3 validate-english-core-run.py "$TMP_DIR/tampered.json" --promotion >/dev/null 2>&1; then
  echo "ERROR: tampered English Core result unexpectedly passed promotion validation" >&2
  exit 1
fi

printf '%s\n' 'English Core structural/integrity self-check passed.'
