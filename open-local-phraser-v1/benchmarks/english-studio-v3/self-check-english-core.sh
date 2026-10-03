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
python3 test_kaggle_edge_cases.py
python3 test_protocol_output_diagnostics.py
python3 test_word_studio_transform_builder.py

# Issue #59: prove the literal runbook, the CLI stage model, the pinned runtime
# registry, and this self-check agree, then run every landed P0 hardening
# contract registered in kaggle-runbook-contract.json. This runs at
# accelerator-off, so S1 fails closed on instrument drift before any GPU time.
# Contracts whose test module has not landed are declared pending in the
# registry and become required automatically once their module exists.
python3 test_kaggle_runbook_consistency.py

python3 test_kaggle_fault_injection.py        # #30 resume/atomic-summary/terminal states
python3 test_kaggle_roster_resume.py          # #30 roster-level resume and terminal status
python3 test_kaggle_candidate_provenance.py    # #33 provenance; #39 phase-aware finalist set
python3 test_kaggle_candidate_stage_attribution.py  # #53 explicit failure-stage attribution
python3 test_kaggle_batch_policy.py            # #47 load-vs-generation OOM and frozen ladder
python3 test_kaggle_stage_ladder.py            # #48 stage/task identity; #49 Q1->Q4 ladder
python3 test_kaggle_data_preparation_lock.py   # #52 CPU data-prep dependency lock is hash-pinned and fail-closed
python3 test_kaggle_weight_sensitivity.py      # #56 close-contender weight-sensitivity lane
python3 test_kaggle_promotion_gate_parity.py   # #62 shared promotion gate, vLLM and Prism parity
python3 test_kaggle_telemetry.py               # #31 per-GPU telemetry receipt and drift analysis
python3 test_progressive_option_timing.py      # #29 progressive first-usable-option timing
python3 test_english_core_allowed_choices.py   # #44 frozen allowed-choice metadata contract
python3 test_kaggle_result_schema.py           # #60 strict versioned result schema
python3 test_kaggle_thinking_capability.py     # #58 effective chat-template / thinking mode
python3 test_official_evidence_semantic_validation.py  # versioned official-evidence semantics
python3 test_official_converter_provenance.py  # #66 converter code/config identity for official anchors
python3 test_repro_manifest_semanticqa_conversion_gate.py  # #66 repro-manifest conversion chain is re-derivable
python3 test_english_core_runtime_semantics.py  # #63 runtime-neutral decoding/adaptation semantics
python3 test_english_core_public_full_sources.py  # #67 frozen finalist source identity and promotion gate
python3 test_english_core_public_full_promotion_gate.py  # #67 public-full scorer's --promotion gate
python3 -c "import english_core_public_sources as m; assert m.SOURCE_CONTRACT_VERSION == 1; print('english_core_public_sources import OK')"
python3 test_word_studio_human_eval.py           # #69 blinded human/product eval pipeline
python3 test_semanticqa_lcc_label_parser.py       # #44 ASCII-alphanumeric taxonomy token boundary
python3 test_english_core_snapshot_provenance.py  # #65 snapshot/scorer provenance binding
# #64 strict/recoverable parallel score views: test_english_core_choice_views.py over
# english_core_choice_views.py and english-core-choice-view-fixtures.json
python3 test_english_core_choice_views.py
# #64 JS half: the three MJS scorers must publish the same frozen scoreView block.
python3 test_mjs_score_view_contract.py
python3 native-blimp/test_native_blimp.py     # #68 native minimal-pair likelihood lane

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
import importlib.util
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()

spec = importlib.util.spec_from_file_location("pari_run_validator", "validate-english-core-run.py")
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)
RESULT_SCHEMA_VERSION = validator.RESULT_SCHEMA_VERSION
RESULT_SCHEMA_SHA256 = (
    validator.sha256_bytes(validator.SCHEMA_PATH.read_bytes())
    if validator.SCHEMA_PATH.is_file()
    else None
)

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
    # The strict result schema (Issue #60) refuses to infer a version, so the
    # fixture must declare the current one explicitly. Read it from the validator
    # rather than hardcoding it, so this self-check cannot drift from the schema.
    "schemaVersion": RESULT_SCHEMA_VERSION,
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
        "resultSchemaVersion": RESULT_SCHEMA_VERSION,
        "resultSchemaSha256": RESULT_SCHEMA_SHA256,
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
