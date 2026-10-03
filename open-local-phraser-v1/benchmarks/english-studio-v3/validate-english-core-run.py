"""Validate English Core result metadata before promotion-quality comparison.

Usage:
    python validate-english-core-run.py result.json
    python validate-english-core-run.py result.json --promotion

The default mode reports reproducibility warnings. --promotion turns the
promotion-quality requirements from ENGLISH_CORE_ROBUSTNESS.md into hard errors.
This validates metadata/completeness/integrity, not linguistic correctness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA_PATH = HERE / "english-core-result-schema.json"
# Issue #63: one versioned runtime-neutral decoding/prompt-adaptation registry,
# consumed here and by the parity tests. The validator no longer hard-codes
# per-runtime numeric sentinels or per-backend adaptation strings.
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from english_core_runtime_semantics import (  # noqa: E402
    RUNTIME_SEMANTICS_VERSION,
    decoding_equivalence,
    normalize_decoding,
    registry_summary,
    resolve_adaptations,
)

RESULT_SCHEMA_VERSION = 1
VALIDATOR_CONTRACT_VERSION = 1
SUPPORTED_SCHEMA_KEYWORDS = {
    "$schema", "$id", "title", "description", "type", "required", "properties",
    "additionalProperties", "items", "minItems", "uniqueItems", "minLength", "pattern",
    "minimum", "maximum", "enum", "const", "$ref",
}

SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
UNKNOWN = {"", "unknown", "unspecified", "n/a", "na", "none-known"}

# Issue #63: the #60 result schema closes `decoding.topK` at `minimum: 0`,
# which is exactly the rule issue #63 corrects: vLLM's own frozen default is
# -1. The schema is owned by the #60 work, so the validator recognizes the
# schema's numeric bound as superseded for this one path rather than editing
# another owner's file, and records the discrepancy it applied in the report.
SCHEMA_TOPK_MINIMUM_OVERRIDES = {"decoding.topK"}


def known(value) -> bool:
    return str(value or "").strip().lower() not in UNKNOWN


def is_sha256(value) -> bool:
    return bool(SHA256_RE.fullmatch(str(value or "")))


def schema_validation_errors(run, schema, errors: list[str]) -> list[str]:
    """Validate against the result schema, deferring only topK's numeric bound.

    The schema check is the same ``validate_schema`` pass as before; the sole
    difference is that a ``$.decoding.topK: number below minimum`` diagnostic is
    held back for the registry to decide, because the registry knows which
    negative top-k values are registered native disabled sentinels.
    """
    deferred: list[str] = []
    for message in validate_schema(run, schema):
        if message.startswith("$.decoding.topK:") and "minimum" in message:
            deferred.append(message)
            continue
        errors.append(message)
    return deferred


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_outputs_sha256(outputs: list[dict]) -> str:
    """UTF-8, sorted keys, ensure_ascii=False, default separators, finite numbers only."""
    payload = json.dumps(outputs, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    return sha256_bytes(payload)


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate JSON object key: {key!r}")
        obj[key] = value
    return obj


def _reject_constant(value: str):
    raise ValueError(f"non-finite JSON number is not allowed: {value}")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number is not allowed: {value}")
    return parsed


def strict_json_loads(text: str):
    return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant, parse_float=_finite_float)


def validate_schema(value, schema, *, path="$", root_schema=None) -> list[str]:
    """Deterministic implementation of the JSON Schema keywords in our schema."""
    root_schema = schema if root_schema is None else root_schema
    errors: list[str] = []
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            return [f"{path}: unsupported schema reference {ref!r}"]
        target = root_schema
        try:
            for segment in ref[2:].split("/"):
                target = target[segment.replace("~1", "/").replace("~0", "~")]
        except (KeyError, TypeError):
            return [f"{path}: unresolved schema reference {ref!r}"]
        return validate_schema(value, target, path=path, root_schema=root_schema)
    expected = schema.get("type")
    expected_types = expected if isinstance(expected, list) else ([expected] if expected else [])
    def matches(kind):
        if kind == "object": return isinstance(value, dict)
        if kind == "array": return isinstance(value, list)
        if kind == "string": return isinstance(value, str)
        if kind == "boolean": return isinstance(value, bool)
        if kind == "integer": return isinstance(value, int) and not isinstance(value, bool)
        if kind == "number": return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        if kind == "null": return value is None
        return False
    if expected_types and not any(matches(kind) for kind in expected_types):
        return [f"{path}: expected {' or '.join(expected_types)}, got {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: value must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value is outside the allowed enum")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value: errors.append(f"{path}: missing required field {key!r}")
        properties = schema.get("properties", {})
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in properties:
                errors.extend(validate_schema(child, properties[key], path=child_path, root_schema=root_schema))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{child_path}: unknown field")
            elif isinstance(schema.get("additionalProperties"), dict):
                errors.extend(validate_schema(child, schema["additionalProperties"], path=child_path, root_schema=root_schema))
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0): errors.append(f"{path}: too few items")
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, ensure_ascii=False, sort_keys=True, allow_nan=False) for item in value]
            if len(encoded) != len(set(encoded)): errors.append(f"{path}: items must be unique")
        if "items" in schema:
            for index, child in enumerate(value):
                errors.extend(validate_schema(child, schema["items"], path=f"{path}[{index}]", root_schema=root_schema))
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0): errors.append(f"{path}: string too short")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value): errors.append(f"{path}: string does not match pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value): errors.append(f"{path}: number must be finite")
        if "minimum" in schema and value < schema["minimum"]: errors.append(f"{path}: number below minimum")
        if "maximum" in schema and value > schema["maximum"]: errors.append(f"{path}: number above maximum")
    return errors


def schema_implementation_errors(schema, path="$schema") -> list[str]:
    """Fail closed if the declarative contract grows beyond implemented keywords."""
    errors = [f"{path}: unsupported schema keyword {key!r}" for key in schema if key not in SUPPORTED_SCHEMA_KEYWORDS]
    if isinstance(schema.get("properties"), dict):
        for key, child in schema["properties"].items():
            if isinstance(child, dict): errors.extend(schema_implementation_errors(child, f"{path}.properties.{key}"))
    for key in ("items", "additionalProperties"):
        child = schema.get(key)
        if isinstance(child, dict): errors.extend(schema_implementation_errors(child, f"{path}.{key}"))
    return errors


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("result")
    ap.add_argument("--promotion", action="store_true", help="enforce Tier-2/promotion metadata as hard requirements")
    ap.add_argument("--compat-legacy-v0", action="store_true", help="accept an unversioned historical result for exploratory diagnostics only")
    args = ap.parse_args()

    result_path = Path(args.result)
    try:
        run = strict_json_loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"invalid result JSON: {exc}")
    if not isinstance(run, dict):
        raise SystemExit("invalid result JSON: top-level value must be an object")
    errors: list[str] = []
    warnings: list[str] = []
    schema_version = run.get("schemaVersion")
    deferred_topk_schema_errors: list[str] = []
    schema_sha256 = sha256_bytes(SCHEMA_PATH.read_bytes()) if SCHEMA_PATH.is_file() else None
    if schema_version == RESULT_SCHEMA_VERSION:
        try:
            schema = strict_json_loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise SystemExit(f"cannot load result schema: {exc}")
        errors.extend(schema_implementation_errors(schema))
        deferred_topk_schema_errors = schema_validation_errors(run, schema, errors)
    elif schema_version is None and args.compat_legacy_v0 and not args.promotion:
        warnings.append("legacy unversioned result accepted through --compat-legacy-v0; exploratory only")
    elif schema_version is None:
        errors.append("schemaVersion missing; result schema version is never inferred from fields")
    elif schema_version == 0 and args.compat_legacy_v0 and not args.promotion:
        warnings.append("legacy schemaVersion=0 accepted through --compat-legacy-v0; exploratory only")
    else:
        errors.append(f"unsupported result schemaVersion={schema_version!r}; supported current version is {RESULT_SCHEMA_VERSION}")

    def issue(message: str, promotion_required: bool = False) -> None:
        if args.promotion and promotion_required:
            errors.append(message)
        else:
            warnings.append(message)

    model = run.get("model") if isinstance(run.get("model"), dict) else {}
    decoding = run.get("decoding") if isinstance(run.get("decoding"), dict) else {}
    repro = run.get("reproducibility") if isinstance(run.get("reproducibility"), dict) else {}
    outputs = run.get("outputs") or []

    if not isinstance(outputs, list):
        errors.append("outputs must be an array")
        outputs = []

    if not known(model.get("name")):
        errors.append("model.name missing")
    if not known(model.get("repoOrName")):
        issue("model.repoOrName missing/unknown", True)
    if not known(model.get("revision")):
        issue("model.revision missing/unknown", True)
    if not known(model.get("quantization")):
        issue("model.quantization missing/unknown; use an explicit value such as fp16/bf16/q4/q8/full", True)
    if model.get("checkpointType") in (None, "unknown"):
        issue("model.checkpointType missing/unknown", True)
    if not known(model.get("runtime")) or not known(model.get("runtimeVersion")):
        issue("runtime identity/version incomplete", True)
    if not known(model.get("tokenizerName")):
        issue("tokenizerName missing/unknown", True)

    artifact_hash = model.get("artifactSha256")
    if artifact_hash and not is_sha256(artifact_hash):
        errors.append("model.artifactSha256 is not a SHA-256 hex string")
    elif not artifact_hash:
        issue("model.artifactSha256 missing; exact model artifact is not cryptographically pinned", True)

    task_hash = run.get("taskFileSha256")
    if not is_sha256(task_hash):
        errors.append("taskFileSha256 missing/invalid")

    declared_task_count = run.get("taskCount")
    if not isinstance(declared_task_count, int) or isinstance(declared_task_count, bool) or declared_task_count < 1:
        issue("taskCount missing/invalid; expected positive integer", True)

    task_path = Path(str(run.get("taskFile") or ""))
    task_ids: list[str] | None = None
    if task_path.exists() and task_path.is_file():
        actual = sha256_bytes(task_path.read_bytes())
        if actual != task_hash:
            errors.append("taskFileSha256 does not match the current task file bytes")
        try:
            task_ids = [strict_json_loads(line)["id"] for line in task_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if len(task_ids) != len(set(task_ids)):
                errors.append("duplicate task IDs in task file")
            if isinstance(declared_task_count, int) and declared_task_count != len(task_ids):
                errors.append(f"taskCount={declared_task_count} does not match task file count={len(task_ids)}")

            output_ids = [row.get("id") for row in outputs if isinstance(row, dict)]
            if len(output_ids) != len(set(output_ids)):
                errors.append("duplicate output IDs in result")
            if set(task_ids) != set(output_ids):
                missing = sorted(set(task_ids) - set(output_ids))
                extra = sorted(set(output_ids) - set(task_ids))
                issue(f"output/task ID mismatch: missing={len(missing)} extra={len(extra)}", True)
            if len(outputs) != len(task_ids):
                issue(f"output count={len(outputs)} does not match task file count={len(task_ids)}", True)
        except Exception as exc:
            errors.append(f"could not validate task/output IDs: {exc}")
    else:
        issue("taskFile path is not locally resolvable; hash/count cannot be rechecked against task bytes", args.promotion)
        if isinstance(declared_task_count, int) and declared_task_count != len(outputs):
            issue(f"taskCount={declared_task_count} does not match output count={len(outputs)}", True)

    prompt_mode = run.get("promptModeRequested")
    if prompt_mode not in {"plain", "chat", "auto"}:
        errors.append("promptModeRequested missing/invalid")
    if prompt_mode == "auto":
        issue("promptModeRequested=auto is exploratory; promotion runs require explicit plain or chat adaptation", True)

    observed = run.get("promptAdaptationModesObserved") or []
    if not observed:
        issue("promptAdaptationModesObserved missing", True)
    # Issue #63: compare the *logical* adaptation class, resolved through the
    # versioned registry, instead of demanding one backend-specific string.
    # The exact raw adapter values are preserved in the report.
    resolutions = resolve_adaptations(observed)
    unregistered_adaptations = [r.raw for r in resolutions if not r.registered]
    if unregistered_adaptations:
        errors.append(
            "unregistered prompt adaptation adapter(s): "
            f"{unregistered_adaptations}; unknown adaptation strings fail closed"
        )
    logical_classes = {r.logical_class for r in resolutions if r.registered and r.logical_class}
    if len(logical_classes) > 1:
        issue(
            "mixed prompt adaptation logical classes observed: "
            f"{sorted(logical_classes)} from {sorted(set(observed))}",
            True,
        )
    if prompt_mode == "plain" and logical_classes and logical_classes != {"plain"}:
        errors.append(
            f"plain prompt mode produced non-plain adaptation class(es): "
            f"{sorted(logical_classes)} from raw {sorted(set(observed))}"
        )
    if prompt_mode == "chat" and logical_classes and logical_classes != {"chat_template"}:
        errors.append(
            f"chat prompt mode produced non-chat-template adaptation class(es): "
            f"{sorted(logical_classes)} from raw {sorted(set(observed))}"
        )
    # A plain run must not be able to satisfy the chat contract, and a chat run
    # must not claim plain adaptation. Both directions are checked above via the
    # logical class; this guards the reverse masquerade explicitly.
    if prompt_mode == "chat" and logical_classes == {"plain"}:
        errors.append(
            "chat prompt mode was satisfied by plain adaptation; plain cannot masquerade as chat_template"
        )
    if prompt_mode == "plain" and logical_classes == {"chat_template"}:
        errors.append(
            "plain prompt mode was satisfied by a chat_template adapter; "
            "chat_template cannot masquerade as plain"
        )
    for row in outputs:
        if not isinstance(row, dict):
            continue
        row_adaptation = row.get("promptAdaptation")
        if row_adaptation is None:
            continue
        row_resolution = resolve_adaptations([row_adaptation])[0]
        if not row_resolution.registered:
            errors.append(
                f"output {row.get('id')!r} records unregistered prompt adaptation "
                f"adapter {row_resolution.raw!r}; unknown adaptation strings fail closed"
            )
            continue
        # Per-row evidence must agree with the run-level observed set. A row
        # whose logical class differs from the run's would let a chat result
        # carry plain rows (or the reverse) without tripping either check.
        if len(logical_classes) == 1 and row_resolution.logical_class not in logical_classes:
            errors.append(
                f"output {row.get('id')!r} records prompt adaptation "
                f"{row_resolution.raw!r} (logical class {row_resolution.logical_class!r}) "
                f"but the run observed logical class(es) {sorted(logical_classes)} "
                f"from {sorted(set(observed))}"
            )

    checkpoint_type = model.get("checkpointType")
    if checkpoint_type == "base" and prompt_mode == "chat":
        issue("base checkpoint evaluated through chat adaptation; justify protocol before comparison", True)
    if checkpoint_type in {"chat", "instruct"} and prompt_mode == "plain":
        issue("chat/instruct checkpoint evaluated with plain prompt; justify protocol before comparison", True)

    if "chat_template" in logical_classes:
        if not is_sha256(model.get("chatTemplateSha256")):
            issue("chat template was used but chatTemplateSha256 is missing/invalid", True)

    required_decoding = ["temperature", "topP", "topK", "maxNewTokens", "forcedChoiceMaxNewTokens", "seed"]
    for key in required_decoding:
        if key not in decoding:
            issue(f"decoding.{key} missing", True)
    # Issue #63: decoding semantics come from the registry, not from
    # per-runtime integer assumptions. `decoding.topK < 0` is no longer an
    # error: vLLM's own frozen default (-1) is a registered disabled sentinel.
    runtime = model.get("runtime")
    decoding_norm = normalize_decoding(decoding, runtime)
    for parameter, entry in sorted(decoding_norm.parameters.items()):
        if parameter == "speculativeDecoding":
            # Informational only: absent/unsupported speculative fields are a
            # schema limitation, not a result defect.
            continue
        if entry.mode == "invalid":
            errors.append(f"decoding.{parameter} is invalid: {entry.note} (raw={entry.raw!r})")
        elif entry.mode == "unregistered_sentinel":
            errors.append(
                f"decoding.{parameter} uses an unregistered sentinel for runtime "
                f"{decoding_norm.runtime!r}: raw={entry.raw!r}; {entry.note}"
            )
        elif entry.mode == "unregistered_negative_top_k":
            errors.append(
                f"decoding.topK is negative ({entry.raw!r}) but runtime "
                f"{decoding_norm.runtime!r} is not in the runtime-semantics registry; "
                "the disabled-sentinel meaning cannot be established, so this fails closed"
            )
        elif entry.mode == "unregistered_runtime":
            # An unregistered runtime is reported as a reproducibility warning,
            # not a promotion blocker: the fail-closed rule is reserved for the
            # case that actually cannot be interpreted (a negative top-k whose
            # sentinel meaning is unknown). A well-formed top-k on an unknown
            # runtime is comparable-as-unpinned, not invalid.
            issue(
                f"runtime {decoding_norm.runtime!r} is not in the runtime-semantics registry; "
                f"decoding.{parameter} semantics are unpinned (raw={entry.raw!r})"
            )
        elif entry.mode == "runtime_dependent_zero":
            issue(
                f"decoding.topP=0 has runtime-dependent meaning "
                f"(vLLM rejects it; llama.cpp/MLX treat it as unconstrained)",
                True,
            )
    # The #60 schema closes decoding.topK at minimum 0; issue #63 supersedes
    # that bound for registered native disabled sentinels. When the registry
    # accepted the value as a registered sentinel (topK mode "disabled"), the
    # deferred schema diagnostic is superseded and dropped. When the registry
    # also rejected the value, its own fail-closed error stands and the deferred
    # schema diagnostic is restored so the report shows both the schema and the
    # registry reason.
    if deferred_topk_schema_errors:
        topk_mode = decoding_norm.mode("topK")
        if topk_mode == "disabled":
            pass  # registered sentinel: the schema's numeric bound is superseded
        else:
            errors.extend(deferred_topk_schema_errors)

    if not known(repro.get("benchmarkRevision")):
        issue("reproducibility.benchmarkRevision missing/unknown", True)

    if args.promotion and schema_version == RESULT_SCHEMA_VERSION:
        if repro.get("resultSchemaVersion") != schema_version:
            errors.append("reproducibility.resultSchemaVersion must match top-level schemaVersion for promotion")
        if repro.get("resultSchemaSha256") != schema_sha256:
            errors.append("reproducibility.resultSchemaSha256 must match the validated schema bytes for promotion")

    declared_raw_hash = repro.get("rawOutputSha256")
    if not is_sha256(declared_raw_hash):
        issue("reproducibility.rawOutputSha256 missing/invalid", True)
    elif outputs:
        actual_raw_hash = canonical_outputs_sha256(outputs)
        if actual_raw_hash.lower() != str(declared_raw_hash).lower():
            errors.append("reproducibility.rawOutputSha256 does not match the current outputs array; result may have been modified after generation")

    output_ids = [row.get("id") for row in outputs if isinstance(row, dict)]
    if len(output_ids) != len(outputs):
        errors.append("one or more outputs are not objects")
    if any(not known(x) for x in output_ids):
        errors.append("one or more outputs have missing IDs")
    if len(output_ids) != len(set(output_ids)):
        errors.append("duplicate output IDs")

    if not outputs:
        errors.append("result has no outputs")

    report = {
        "version": 2,
        "schemaValidation": {
            "validatorContractVersion": VALIDATOR_CONTRACT_VERSION,
            "validationMode": "promotion" if args.promotion else "exploratory",
            "resultSchemaVersion": schema_version,
            "schemaSha256": schema_sha256 if schema_version == RESULT_SCHEMA_VERSION else None,
            "compatibilityMode": "legacy-v0-exploratory" if args.compat_legacy_v0 and schema_version in (None, 0) else None,
        },
        "result": str(result_path),
        "mode": "promotion" if args.promotion else "exploratory",
        "declaredTaskCount": declared_task_count,
        "observedOutputCount": len(outputs),
        "locallyResolvedTaskCount": len(task_ids) if task_ids is not None else None,
        "rawOutputHashVerified": bool(outputs and is_sha256(declared_raw_hash) and canonical_outputs_sha256(outputs).lower() == str(declared_raw_hash).lower()),
        "runtimeSemantics": {
            "runtimeSemanticsVersion": RUNTIME_SEMANTICS_VERSION,
            "runtime": decoding_norm.runtime,
            "runtimeRegistered": decoding_norm.runtime_registered,
            "decoding": decoding_norm.as_dict(),
            "schemaOverrides": {
                "paths": sorted(SCHEMA_TOPK_MINIMUM_OVERRIDES),
                "reason": (
                    "issue #63: the result schema closes decoding.topK at minimum 0, which "
                    "rejects vLLM's own frozen default -1; the runtime-semantics registry "
                    "decides which negative top-k values are registered native disabled "
                    "sentinels instead"
                ),
                "deferredSchemaDiagnostics": list(deferred_topk_schema_errors),
                "acceptedAsRegisteredSentinel": bool(
                    deferred_topk_schema_errors and decoding_norm.mode("topK") == "disabled"
                ),
            },
            "promptAdaptation": {
                "requested": prompt_mode,
                "logicalClasses": sorted(logical_classes),
                "observed": [r.as_dict() for r in resolutions],
            },
            # The full mapping the validator consumed, so a report records the
            # registry identity it was judged against rather than an opaque
            # integer. One versioned mapping, consumed by runners, validator,
            # #60 self-check, and the #62 parity tests.
            "registry": registry_summary(),
        },
        "errors": errors,
        "warnings": warnings,
        "status": "fail" if errors else ("pass_with_warnings" if warnings else "pass"),
        "interpretation": [
            "This validator checks reproducibility/comparability metadata and result-file integrity, not English correctness.",
            "The raw-output hash uses UTF-8 JSON with sorted keys, ensure_ascii=false, default separators, and finite numbers only.",
            "Promotion mode intentionally rejects ambiguous adaptation, incomplete task coverage, and unknown artifact metadata rather than assuming two runs are comparable.",
            "Decoding and prompt adaptation are interpreted through the versioned runtime-semantics registry; backend-native values are preserved in runtimeSemantics.decoding and compared only in their logical form.",
            "runtimeSemantics.decoding.unrecorded names the runner fields that would be required before stop/EOS and llama.cpp speculative decoding can be compared across runtimes.",
            "A passing result still requires benchmark-native anchors, robustness lanes, statistical comparison, and human validation at the claim tier specified in ENGLISH_CORE_ROBUSTNESS.md."
        ]
    }
    print(json.dumps(report, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
