"""Issue #63 parity and fail-closed tests for the runtime-semantics registry.

All evidence in this file is FABRICATED. No model, GPU, Kaggle session, or real
result file is involved; the fixtures reproduce only the field shapes the
in-tree runners write (run-english-core-vllm.py, run-english-core-llamacpp.py,
run-english-core-mlx.py) so the registry's behaviour is pinned without spending
accelerator time.

Run: python3 test_english_core_runtime_semantics.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from english_core_runtime_semantics import (
    RUNTIME_SEMANTICS_VERSION,
    decoding_equivalence,
    normalize_decoding,
    registry_summary,
    resolve_adaptations,
    resolve_adaptation,
)

HERE = Path(__file__).resolve().parent
VALIDATOR = HERE / "validate-english-core-run.py"
SCHEMA_PATH = HERE / "english-core-result-schema.json"

FAILURES: list[str] = []
CHECKS = 0


def check(condition: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(message)


def vllm_decoding(**overrides) -> dict:
    """The canonical vLLM frozen defaults (run-english-core-vllm.py:790-793)."""
    decoding = {
        "temperature": 0.0,
        "topP": 1.0,
        "topK": -1,
        "maxNewTokens": 220,
        "forcedChoiceMaxNewTokens": 8,
        "seed": 0,
        "speculativeConfig": None,
    }
    decoding.update(overrides)
    return decoding


def llamacpp_decoding(**overrides) -> dict:
    """The canonical llama.cpp frozen defaults (run-english-core-llamacpp.py:412-415)."""
    decoding = {
        "temperature": 0.0,
        "topP": 1.0,
        "topK": 0,
        "maxNewTokens": 220,
        "forcedChoiceMaxNewTokens": 8,
        "seed": 0,
    }
    decoding.update(overrides)
    return decoding


# ---------------------------------------------------------------------------
# 1. Cross-runtime parity: one logically equivalent configuration represented
#    natively by both backends.
# ---------------------------------------------------------------------------


def test_cross_runtime_parity() -> None:
    vllm = normalize_decoding(vllm_decoding(), "vllm")
    llama = normalize_decoding(llamacpp_decoding(), "llama.cpp-server")

    check(vllm.parameters["topK"].raw == -1, "vLLM raw topK must be preserved as -1")
    check(llama.parameters["topK"].raw == 0, "llama.cpp raw topK must be preserved as 0")
    check(vllm.mode("topK") == "disabled", "vLLM topK=-1 must normalize to topK-disabled")
    check(llama.mode("topK") == "disabled", "llama.cpp topK=0 must normalize to topK-disabled")
    check(vllm.parameters["topK"].raw != llama.parameters["topK"].raw,
          "raw backend values must not be coerced into one another")

    equivalent, reasons = decoding_equivalence(vllm, llama)
    check(equivalent, f"vLLM -1 and llama.cpp 0 must be logically equivalent; got {reasons}")


# ---------------------------------------------------------------------------
# 2. An actually active topK=40 stays distinct from disabled, on both backends.
#    llama.cpp's own server default is 40, so this is a real active value there.
# ---------------------------------------------------------------------------


def test_active_top_k_stays_distinct() -> None:
    for runtime, decoding in (
        ("vllm", vllm_decoding(topK=40)),
        ("llama.cpp-server", llamacpp_decoding(topK=40)),
    ):
        norm = normalize_decoding(decoding, runtime)
        check(norm.mode("topK") == "active",
              f"{runtime}: topK=40 must normalize to an active top-k, got {norm.mode('topK')!r}")
        check(norm.mode("topK") != "disabled", f"{runtime}: topK=40 must not read as disabled")

    disabled = normalize_decoding(vllm_decoding(), "vllm")
    active = normalize_decoding(vllm_decoding(topK=40), "vllm")
    equivalent, reasons = decoding_equivalence(disabled, active)
    check(not equivalent, "an active topK=40 must not be equivalent to a disabled top-k")
    check(any("topK" in reason for reason in reasons),
          f"topK difference must be the reported reason; got {reasons}")


# ---------------------------------------------------------------------------
# 3. Unknown sentinels fail closed.
# ---------------------------------------------------------------------------


def test_unknown_sentinels_fail_closed() -> None:
    # vLLM raises for top_k < -1, so -2 is not a sentinel in any sense.
    too_negative = normalize_decoding(vllm_decoding(topK=-2), "vllm")
    check(too_negative.mode("topK") == "unregistered_sentinel",
          f"vLLM topK=-2 must fail closed, got {too_negative.mode('topK')!r}")

    # llama.cpp documents only 0 as disabled; -1 is not a registered sentinel
    # for that runtime and must not be silently borrowed from vLLM.
    borrowed = normalize_decoding(llamacpp_decoding(topK=-1), "llama.cpp-server")
    check(borrowed.mode("topK") == "unregistered_sentinel",
          f"llama.cpp topK=-1 must fail closed, got {borrowed.mode('topK')!r}")

    # A non-integer sentinel is invalid, not disabled.
    stringy = normalize_decoding(vllm_decoding(topK="0"), "vllm")
    check(stringy.mode("topK") == "invalid", f"string topK must be invalid, got {stringy.mode('topK')!r}")

    # Unregistered runtime + negative top-k cannot establish disabled meaning.
    unknown_runtime = normalize_decoding(vllm_decoding(), "fixture-runtime")
    check(unknown_runtime.mode("topK") == "unregistered_negative_top_k",
          f"unregistered runtime + negative topK must fail closed, got {unknown_runtime.mode('topK')!r}")

    # Unregistered runtime + well-formed top-k is reported, never silently trusted.
    unregistered_active = normalize_decoding(llamacpp_decoding(topK=40), "fixture-runtime")
    check(not unregistered_active.runtime_registered,
          "an unregistered runtime must never be reported as registered")
    check(unregistered_active.mode("topK") == "unregistered_runtime",
          f"unregistered runtime topK must be unpinned, got {unregistered_active.mode('topK')!r}")

    # Cross-runtime parity must be impossible against an unregistered runtime.
    try:
        from english_core_runtime_semantics import comparable_sampling_key

        comparable_sampling_key(unregistered_active)
        check(False, "comparable_sampling_key must refuse an unregistered runtime")
    except ValueError:
        check(True, "")


# ---------------------------------------------------------------------------
# 4. Prompt-adaptation registry: both registered chat implementations satisfy
#    the logical chat contract; unknown and plain-mode masquerades do not.
# ---------------------------------------------------------------------------


def test_prompt_adaptation_registry() -> None:
    transformers = resolve_adaptation("transformers_apply_chat_template")
    # The llama.cpp runner records the dotted spelling (run-english-core-llamacpp.py:632).
    embedded = resolve_adaptation("llama.cpp_embedded_chat_template")
    embedded_underscore = resolve_adaptation("llama_cpp_embedded_chat_template")
    legacy = resolve_adaptation("chat_template")
    for name, resolution in (
        ("transformers", transformers),
        ("embedded", embedded),
        ("embedded-underscore", embedded_underscore),
        ("legacy", legacy),
    ):
        check(resolution.registered, f"{name} adapter must be registered")
        check(resolution.logical_class == "chat_template",
              f"{name} adapter must resolve to logical chat_template, got {resolution.logical_class!r}")
    check(transformers.raw == "transformers_apply_chat_template",
          "the exact raw adapter value must be preserved")
    check(embedded.raw == "llama.cpp_embedded_chat_template",
          "the exact raw adapter value must be preserved")

    unknown = resolve_adaptation("some_future_chat_adapter")
    check(not unknown.registered, "an unknown adaptation string must not be registered")
    check(unknown.logical_class is None, "an unknown adaptation string must resolve to no logical class")
    check(unknown.raw == "some_future_chat_adapter",
          "an unknown adaptation string must still be preserved verbatim for diagnosis")

    plain = resolve_adaptation("plain")
    check(plain.logical_class == "plain", "plain must resolve to the plain logical class")
    check(plain.logical_class != "chat_template", "plain must not masquerade as chat_template")

    missing = resolve_adaptations(["", None, 7])
    check(all(not r.registered for r in missing),
          "empty, null, and non-string adaptation values must all fail closed")


# ---------------------------------------------------------------------------
# 5. temperature / topP / seed / max-token / speculative coverage, bounded by
#    what the current decoding object can actually express.
# ---------------------------------------------------------------------------


def test_remaining_decoding_coverage() -> None:
    greedy = normalize_decoding(vllm_decoding(), "vllm")
    check(greedy.mode("temperature") == "greedy", "temperature 0 must be greedy")
    check("overrides" in greedy.parameters["temperature"].note,
          "vLLM greedy must record that it overrides topP/topK")
    check("effective mode under greedy is disabled" in greedy.parameters["topK"].note,
          "the requested topK reading must be annotated with its effective greedy value")

    stochastic = normalize_decoding(vllm_decoding(temperature=0.7), "vllm")
    check(stochastic.mode("temperature") == "stochastic", "temperature 0.7 must be stochastic")
    check(stochastic.parameters["topK"].note == "active top-k sentinel note"
          or "active" not in stochastic.parameters["topK"].mode,
          "a stochastic vLLM run must not claim the greedy override applied")

    unseeded = normalize_decoding(vllm_decoding(seed=None), "vllm")
    check(unseeded.mode("seed") == "unseeded", "a null seed must read as unseeded, not as seed 0")

    nucleus = normalize_decoding(vllm_decoding(topP=0.9), "vllm")
    check(nucleus.mode("topP") == "nucleus", "topP=0.9 must be nucleus filtering")
    unconstrained = normalize_decoding(vllm_decoding(topP=1.0), "vllm")
    check(unconstrained.mode("topP") == "unconstrained", "topP=1.0 must be unconstrained")
    zero_p = normalize_decoding(vllm_decoding(topP=0.0), "vllm")
    check(zero_p.mode("topP") == "runtime_dependent_zero",
          "topP=0 must be flagged runtime-dependent, not silently normalized")

    bad_budget = normalize_decoding(vllm_decoding(maxNewTokens=0), "vllm")
    check(bad_budget.mode("maxNewTokens") == "invalid", "maxNewTokens=0 must be invalid")

    speculative_on = normalize_decoding(
        vllm_decoding(speculativeConfig={"method": "mtp", "num_speculative_tokens": 1}), "vllm"
    )
    check(speculative_on.mode("speculativeDecoding") == "enabled",
          "a populated speculativeConfig must read as enabled")
    speculative_off = normalize_decoding(vllm_decoding(), "vllm")
    check(speculative_off.mode("speculativeDecoding") == "disabled",
          "speculativeConfig=null must read as disabled")

    # stop/EOS and llama.cpp speculative decoding cannot be expressed by the
    # current decoding object; the registry must say so and name the fields.
    summary = registry_summary()
    for notion in ("stopSequences", "eosTokenId", "speculativeDecoding"):
        check(notion in summary["unrecordedNotions"],
              f"the registry must record {notion} as an unexpressible notion")
        check("decoding." in summary["unrecordedNotions"][notion],
              f"the {notion} note must name the runner field that would be required")
    check("stopSequences" in greedy.unrecorded,
          "stop/EOS must appear as unrecorded on every normalization")


# ---------------------------------------------------------------------------
# 6. Registry identity is stable and self-describing.
# ---------------------------------------------------------------------------


def test_registry_identity() -> None:
    check(RUNTIME_SEMANTICS_VERSION == 1,
          f"registry version changed unexpectedly: {RUNTIME_SEMANTICS_VERSION}")
    summary = registry_summary()
    check(summary["runtimes"]["vllm"]["topKDisabledSentinels"] == [0, -1],
          "vLLM must register both 0 and -1 as disabled sentinels")
    check(summary["runtimes"]["llama.cpp-server"]["topKDisabledSentinels"] == [0],
          "llama.cpp must register 0 only")
    check(summary["runtimes"]["llama.cpp-server"]["topKActiveFloor"] == 1,
          "llama.cpp active top-k must start at 1 so 40 stays active")
    check(set(summary["adapters"]["llama.cpp_embedded_chat_template"]["runtimes"]) == {"llama.cpp-server"},
          "the embedded chat-template adapter belongs to llama.cpp only")
    check("llama_cpp_embedded_chat_template" in summary["adapters"],
          "the underscore spelling named in issue #63 must be registered too")
    check(summary["adapters"]["llama_cpp_embedded_chat_template"]["logicalClass"] == "chat_template",
          "the underscore spelling must resolve to the same logical class")


# ---------------------------------------------------------------------------
# 7. End-to-end through the real validator CLI: a fabricated canonical vLLM
#    result with topK=-1 must pass promotion, the same run with topK=-2 must
#    fail, and a Prism-style llama.cpp chat result must pass.
# ---------------------------------------------------------------------------


def _write_result(root: Path, name: str, run: dict) -> Path:
    path = root / name
    path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
    return path


def _fabricated_result(root: Path, *, runtime: str, top_k, adaptation: str, prompt_mode: str) -> dict:
    task = {"id": "fixture-1", "prompt": "Choose A or B.\nA. alpha\nB. beta\nAnswer only with the letter.",
            "generative": False}
    task_path = root / f"tasks-{runtime}-{top_k}.jsonl"
    task_bytes = (json.dumps(task) + "\n").encode("utf-8")
    task_path.write_bytes(task_bytes)

    chat = prompt_mode == "chat"
    outputs = [{
        "id": "fixture-1",
        "output": "A",
        "latencySeconds": 0.0,
        "promptAdaptation": adaptation,
        "promptAdaptationDetail": "reasoning_effort=none;enable_thinking=false" if chat else "none",
    }]
    raw_hash = hashlib.sha256(
        json.dumps(outputs, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    schema_sha256 = (
        hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest() if SCHEMA_PATH.is_file() else None
    )
    decoding = {
        "temperature": 0.0,
        "topP": 1.0,
        "topK": top_k,
        "maxNewTokens": 220,
        "forcedChoiceMaxNewTokens": 8,
        "seed": 0,
        "batchSize": 8,
    }
    if runtime == "vllm":
        decoding["speculativeConfig"] = None
    return {
        "schemaVersion": 1,
        "runId": f"fixture-{runtime}-{top_k}",
        "model": {
            "name": "fixture-model",
            "repoOrName": "fixture/model",
            "revision": "f" * 40,
            "artifactSha256": "a" * 64,
            "quantization": "bf16" if runtime == "vllm" else "Q4_K_M",
            "checkpointType": "instruct",
            "runtime": runtime,
            "runtimeVersion": "0.30.0" if runtime == "vllm" else "b10735",
            "tokenizerName": "fixture-tokenizer",
            "chatTemplate": "tokenizer.apply_chat_template" if (chat and runtime == "vllm")
                            else ("llama.cpp GGUF-embedded chat template" if chat else "none/plain"),
            "chatTemplateSha256": "b" * 64 if chat else None,
        },
        "hardware": {},
        "taskFile": str(task_path),
        "taskFileSha256": hashlib.sha256(task_bytes).hexdigest(),
        "taskCount": 1,
        "promptModeRequested": prompt_mode,
        "promptAdaptationModesObserved": [adaptation],
        "promptAdaptationDetailsObserved": ["reasoning_effort=none;enable_thinking=false" if chat else "none"],
        "decoding": decoding,
        "runtime": {},
        "outputs": outputs,
        "reproducibility": {
            "benchmarkRevision": "fixture-benchmark-revision",
            "rawOutputSha256": raw_hash,
            "resultSchemaVersion": 1,
            "resultSchemaSha256": schema_sha256,
            "notes": [],
        },
    }


def _run_validator(path: Path, *, promotion: bool = True) -> tuple[int, dict | None, str]:
    command = [sys.executable, str(VALIDATOR), str(path)]
    if promotion:
        command.append("--promotion")
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        report = None
    return proc.returncode, report, (proc.stdout + proc.stderr)


def test_validator_end_to_end() -> None:
    if not VALIDATOR.is_file() or not SCHEMA_PATH.is_file():
        check(False, "validator or result schema missing; cannot run the end-to-end check")
        return

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # A canonical vLLM run at its own frozen default must now pass promotion.
        vllm_ok = _write_result(
            root, "vllm-ok.json",
            _fabricated_result(root, runtime="vllm", top_k=-1, adaptation="chat_template", prompt_mode="chat"),
        )
        code, report, out = _run_validator(vllm_ok)
        check(code == 0, f"canonical vLLM topK=-1 must pass promotion; exit={code}\n{out}")
        if report:
            semantics = report["runtimeSemantics"]
            check(semantics["decoding"]["parameters"]["topK"]["raw"] == -1,
                  "the validator report must preserve the raw vLLM topK=-1")
            check(semantics["decoding"]["parameters"]["topK"]["mode"] == "disabled",
                  "the validator report must normalize vLLM topK=-1 to disabled")
            check(semantics["promptAdaptation"]["logicalClasses"] == ["chat_template"],
                  "the validator must resolve chat_template through the registry")
            check(semantics["runtimeSemanticsVersion"] == RUNTIME_SEMANTICS_VERSION,
                  "the report must record the registry version it judged against")
            check("registry" in semantics and semantics["registry"]["runtimes"],
                  "the report must carry the registry identity, not just a version integer")

        # A canonical Prism/llama.cpp chat run must pass the same contract.
        llama_ok = _write_result(
            root, "llama-ok.json",
            _fabricated_result(root, runtime="llama.cpp-server", top_k=0,
                               adaptation="llama.cpp_embedded_chat_template", prompt_mode="chat"),
        )
        code, report, out = _run_validator(llama_ok)
        check(code == 0,
              f"canonical llama.cpp topK=0 chat run must pass promotion; exit={code}\n{out}")
        if report:
            check(report["runtimeSemantics"]["decoding"]["parameters"]["topK"]["raw"] == 0,
                  "the validator report must preserve the raw llama.cpp topK=0")
            check(report["runtimeSemantics"]["promptAdaptation"]["logicalClasses"] == ["chat_template"],
                  "the embedded chat-template adapter must satisfy the logical chat contract")

        # An unknown sentinel must fail closed in the validator too.
        vllm_bad = _write_result(
            root, "vllm-bad.json",
            _fabricated_result(root, runtime="vllm", top_k=-2, adaptation="chat_template", prompt_mode="chat"),
        )
        code, report, out = _run_validator(vllm_bad)
        check(code != 0, "vLLM topK=-2 must fail promotion validation")
        if report:
            check(any("topK" in error for error in report["errors"]),
                  f"the failure must name topK; got {report['errors']}")

        # An unknown adaptation string must fail closed.
        unknown_adaptation = _write_result(
            root, "vllm-unknown-adapter.json",
            _fabricated_result(root, runtime="vllm", top_k=-1,
                               adaptation="mystery_chat_adapter", prompt_mode="chat"),
        )
        code, report, out = _run_validator(unknown_adaptation)
        check(code != 0, "an unknown adaptation string must fail promotion validation")
        if report:
            check(any("unregistered" in error for error in report["errors"]),
                  f"the failure must name the unregistered adapter; got {report['errors']}")

        # Plain mode may not masquerade as chat-template mode.
        masquerade = _write_result(
            root, "vllm-plain-masquerade.json",
            _fabricated_result(root, runtime="vllm", top_k=-1, adaptation="plain", prompt_mode="chat"),
        )
        code, report, out = _run_validator(masquerade)
        check(code != 0, "a plain adaptation must not satisfy a chat prompt mode")
        if report:
            check(any("masquerade" in error or "non-chat-template" in error
                      for error in report["errors"]),
                  f"the failure must name the masquerade; got {report['errors']}")

        # And the reverse: a chat adapter may not be recorded for a plain run.
        reverse = _write_result(
            root, "vllm-chat-as-plain.json",
            _fabricated_result(root, runtime="vllm", top_k=-1,
                               adaptation="chat_template", prompt_mode="plain"),
        )
        code, report, out = _run_validator(reverse)
        check(code != 0, "a chat_template adapter must not satisfy a plain prompt mode")

        # A run-level chat adaptation with a per-row plain value must fail closed.
        mixed = _fabricated_result(root, runtime="vllm", top_k=-1,
                                   adaptation="chat_template", prompt_mode="chat")
        mixed["outputs"][0]["promptAdaptation"] = "plain"
        mixed["reproducibility"]["rawOutputSha256"] = hashlib.sha256(
            json.dumps(mixed["outputs"], ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        mixed_path = _write_result(root, "vllm-mixed-rows.json", mixed)
        code, report, out = _run_validator(mixed_path)
        check(code != 0, "a per-row plain adaptation inside a chat run must fail closed")


def main() -> int:
    test_cross_runtime_parity()
    test_active_top_k_stays_distinct()
    test_unknown_sentinels_fail_closed()
    test_prompt_adaptation_registry()
    test_remaining_decoding_coverage()
    test_registry_identity()
    test_validator_end_to_end()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} of {CHECKS} checks failed", file=sys.stderr)
        for failure in FAILURES:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"OK: {CHECKS} runtime-semantics checks passed (registry v{RUNTIME_SEMANTICS_VERSION})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
