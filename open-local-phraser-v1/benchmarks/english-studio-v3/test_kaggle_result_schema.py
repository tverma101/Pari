#!/usr/bin/env python3
"""Focused integrity tests for English Core result schema v1 / issue #60."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
VALIDATOR = HERE / "validate-english-core-run.py"
SPEC = importlib.util.spec_from_file_location("english_core_result_validator", VALIDATOR)
validator = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(validator)


class ResultSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.tasks = self.root / "tasks.jsonl"
        self.tasks.write_text('{"id":"t1","prompt":"fixture"}\n', encoding="utf-8")
        self.output_rows = [{"id": "t1", "output": "A", "latencySeconds": 0.25}]
        schema_sha = hashlib.sha256(validator.SCHEMA_PATH.read_bytes()).hexdigest()
        self.run = {
            "schemaVersion": 1,
            "runId": "fixture-run",
            "timestamp": "2026-10-02T00:00:00Z",
            "status": "completed",
            "complete": True,
            "completedCount": 1,
            "model": {
                "name": "fixture", "repoOrName": "org/model", "revision": "a" * 40,
                "artifactSha256": "b" * 64, "quantization": "bf16", "checkpointType": "instruct",
                "runtime": "fixture-runtime", "runtimeVersion": "1.0", "tokenizerName": "org/model",
                "chatTemplateSha256": "c" * 64,
            },
            "hardware": {"machine": "cpu", "os": "test"},
            "taskFile": str(self.tasks),
            "taskFileSha256": hashlib.sha256(self.tasks.read_bytes()).hexdigest(),
            "taskCount": 1,
            "promptModeRequested": "chat",
            "promptAdaptationModesObserved": ["chat_template"],
            "promptAdaptationDetailsObserved": ["fixture"],
            "decoding": {"temperature": 0, "topP": 1, "topK": 0, "maxNewTokens": 16, "forcedChoiceMaxNewTokens": 4, "seed": 1},
            "outputs": self.output_rows,
            "reproducibility": {
                "benchmarkRevision": "d" * 40,
                "rawOutputSha256": validator.canonical_outputs_sha256(self.output_rows),
                "resultSchemaVersion": 1,
                "resultSchemaSha256": schema_sha,
                "notes": [],
            },
        }
        self.path = self.root / "result.json"

    def tearDown(self):
        self.temp.cleanup()

    def write_raw(self, content: str):
        self.path.write_text(content, encoding="utf-8")

    def run_cli(self, *flags):
        return subprocess.run([sys.executable, str(VALIDATOR), str(self.path), *flags], capture_output=True, text=True)

    def test_current_versioned_promotion_passes_and_binds_schema(self):
        self.path.write_text(json.dumps(self.run, ensure_ascii=False), encoding="utf-8")
        result = self.run_cli("--promotion")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schemaValidation"]["validationMode"], "promotion")
        self.assertEqual(report["schemaValidation"]["resultSchemaVersion"], 1)
        self.assertEqual(report["schemaValidation"]["schemaSha256"], self.run["reproducibility"]["resultSchemaSha256"])

    def test_promotion_requires_schema_identity_in_reproducibility(self):
        result = json.loads(json.dumps(self.run))
        result["reproducibility"].pop("resultSchemaVersion")
        self.path.write_text(json.dumps(result), encoding="utf-8")
        checked = self.run_cli("--promotion")
        self.assertNotEqual(checked.returncode, 0)
        self.assertIn("reproducibility.resultSchemaVersion must match", checked.stdout)

    def test_missing_schema_version_fails_promotion(self):
        legacy = dict(self.run)
        legacy.pop("schemaVersion")
        self.path.write_text(json.dumps(legacy), encoding="utf-8")
        result = self.run_cli("--promotion")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("schemaVersion missing", result.stdout)

    def test_unknown_future_schema_version_fails_closed(self):
        future = dict(self.run, schemaVersion=999)
        self.path.write_text(json.dumps(future), encoding="utf-8")
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported result schemaVersion", result.stdout)

    def test_required_field_typo_and_unknown_replacement_fail(self):
        broken = json.loads(json.dumps(self.run))
        broken["outputs"][0]["latencySecond"] = broken["outputs"][0].pop("latencySeconds")
        self.path.write_text(json.dumps(broken), encoding="utf-8")
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown field", result.stdout)
        self.assertIn("latencySeconds", result.stdout)

    def test_unknown_top_level_field_fails(self):
        broken = dict(self.run, surprise="meaningful later")
        self.path.write_text(json.dumps(broken), encoding="utf-8")
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("$.surprise: unknown field", result.stdout)

    def test_nan_rejected_during_json_parse(self):
        self.write_raw('{"schemaVersion":1,"runId":"x","model":{"name":"x"},"outputs":[{"id":"t1","output":"A","latencySeconds":NaN}]}')
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-finite JSON number", result.stderr)

    def test_infinity_rejected_in_probability(self):
        self.write_raw('{"schemaVersion":1,"runId":"x","model":{"name":"x"},"outputs":[{"id":"t1","output":"A","latencySeconds":1,"probabilities":{"A":Infinity}}]}')
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-finite JSON number", result.stderr)

    def test_overflowing_json_number_rejected(self):
        self.write_raw('{"schemaVersion":1,"runId":"x","model":{"name":"x"},"outputs":[{"id":"t1","output":"A","latencySeconds":1e999}]}')
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-finite JSON number", result.stderr)

    def test_null_percentile_with_reason_is_valid(self):
        result = json.loads(json.dumps(self.run))
        result["outputs"][0]["latencyPercentiles"] = {"p50Seconds": None, "p50UnavailableReason": "not collected", "p90Seconds": 0.5}
        errors = validator.validate_schema(result, json.loads(validator.SCHEMA_PATH.read_text()))
        self.assertEqual(errors, [])

    def test_duplicate_provenance_key_rejected(self):
        self.write_raw('{"schemaVersion":1,"runId":"x","model":{"name":"x"},"outputs":[{"id":"t1","output":"A","latencySeconds":1}],"reproducibility":{"benchmarkRevision":"a","benchmarkRevision":"b"}}')
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate JSON object key", result.stderr)

    def test_wrong_enum_and_type_fail_schema(self):
        broken = json.loads(json.dumps(self.run))
        broken["promptModeRequested"] = "automatic"
        broken["outputs"][0]["latencySeconds"] = "0.2"
        errors = validator.validate_schema(broken, json.loads(validator.SCHEMA_PATH.read_text()))
        self.assertTrue(any("enum" in error for error in errors), errors)
        self.assertTrue(any("expected number" in error for error in errors), errors)

    def test_wrong_model_container_fails_without_validator_crash(self):
        broken = dict(self.run, model="not-an-object")
        self.path.write_text(json.dumps(broken), encoding="utf-8")
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected object", result.stdout)

    def test_legacy_result_requires_explicit_exploratory_compatibility_flag(self):
        legacy = dict(self.run)
        legacy.pop("schemaVersion")
        legacy["reproducibility"] = dict(legacy["reproducibility"])
        legacy["reproducibility"].pop("resultSchemaVersion")
        legacy["reproducibility"].pop("resultSchemaSha256")
        self.path.write_text(json.dumps(legacy), encoding="utf-8")
        implicit = self.run_cli()
        self.assertNotEqual(implicit.returncode, 0)
        explicit = self.run_cli("--compat-legacy-v0")
        self.assertEqual(explicit.returncode, 0, explicit.stdout + explicit.stderr)
        promotion = self.run_cli("--promotion", "--compat-legacy-v0")
        self.assertNotEqual(promotion.returncode, 0)

    def test_canonical_output_hash_matches_independent_fixture_vector(self):
        rows = [{"id": "é", "output": "A", "latencySeconds": 0.25}]
        canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
        self.assertEqual(canonical.decode("utf-8"), '[{"id": "é", "latencySeconds": 0.25, "output": "A"}]')
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), "44266e228496d2b86bb793b9cb4851119e830135d5e916345f496b62dd4b45a8")
        self.assertEqual(validator.canonical_outputs_sha256(rows), "44266e228496d2b86bb793b9cb4851119e830135d5e916345f496b62dd4b45a8")
        with self.assertRaises(ValueError):
            validator.canonical_outputs_sha256([{"latencySeconds": float("inf")}])

    def test_schema_has_no_unimplemented_keywords(self):
        schema = json.loads(validator.SCHEMA_PATH.read_text())
        self.assertEqual(validator.schema_implementation_errors(schema), [])

    def test_node_score_consumer_runs_strict_validator_before_scoring(self):
        invalid = dict(self.run, schemaVersion=99)
        self.path.write_text(json.dumps(invalid), encoding="utf-8")
        result = subprocess.run(
            ["node", str(HERE / "score-english-core.mjs"), str(self.path)],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported result schemaVersion", result.stderr + result.stdout)

    def test_python_consumer_helper_exposes_validator_failure(self):
        invalid = dict(self.run, schemaVersion=99)
        self.path.write_text(json.dumps(invalid), encoding="utf-8")
        code = (
            "from english_core_result_contract import validate_result; "
            f"validate_result({str(self.path)!r})"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=HERE, capture_output=True, text=True
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unsupported result schemaVersion", result.stderr)

    def test_paired_comparison_requires_versioned_validated_score_artifacts(self):
        a = self.root / "a.score.json"
        b = self.root / "b.score.json"
        a.write_text('{"version":8}', encoding="utf-8")
        b.write_text('{"version":8}', encoding="utf-8")
        result = subprocess.run(
            ["node", str(HERE / "compare-english-core-models.mjs"), str(a), str(b), "1000"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("supported versioned English Core shadow-score", result.stderr)

    def test_uncertainty_consumer_requires_validated_score_artifact(self):
        score = self.root / "score.json"
        score.write_text('{"version":8}', encoding="utf-8")
        result = subprocess.run(
            ["node", str(HERE / "analyze-english-core-statistics.mjs"), str(score), "1000"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("versioned English Core shadow-score", result.stderr)


if __name__ == "__main__":
    unittest.main()
