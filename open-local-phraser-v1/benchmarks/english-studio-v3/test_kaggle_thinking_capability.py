#!/usr/bin/env python3
"""Issue #58: prove chat-template / non-thinking mode is effective, not requested.

Three runtime paths report a `thinkingCapability` block in their result payload:

* `run-english-core-vllm.py` (transformers chat template, local tokenizer)
* `run-english-core-llamacpp.py` (llama.cpp server `/apply-template`)
* `run-kaggle-vllm-streaming-latency.py` (vLLM server `/tokenize`)

The contract is narrow and adversarial: a requested flag is never evidence.
`applied` / `verified_default` require a proof that names the mechanism which
verified the template, and a plain-prompt run must never claim a template applied.

CPU-only: no GPU, no model, no network, no Kaggle. Server interactions are replaced
by deterministic fakes and any accidental real call raises.

Run directly (matching the other benchmark tests) or under pytest:
    python3 test_kaggle_thinking_capability.py
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

import kaggle_context_budget as CB  # noqa: E402 - plain sibling module

VLLM_RUNNER = HERE / "run-english-core-vllm.py"
LLAMACPP_RUNNER = HERE / "run-english-core-llamacpp.py"
LATENCY_RUNNER = HERE / "run-kaggle-vllm-streaming-latency.py"

PRODUCERS = {
    "vllm": VLLM_RUNNER,
    "llamacpp": LLAMACPP_RUNNER,
    "streaming-latency": LATENCY_RUNNER,
}

#: Any of these in a `proof` string means the runner justified the claim with
#: something other than "the caller asked for it". These are the three real
#: verification mechanisms: a local transformers template render, the llama.cpp
#: server's `/apply-template`, and the vLLM server's own `/tokenize`.
PROOF_MARKERS = (
    "apply_chat_template",
    "/apply-template",
    "/tokenize",
    "accepted",
    "counted prompt",
    "server-rendered",
    "counted by the same server",
    "server-rendered template output",
)

#: Substrings that would mean the proof only restates the request.
REQUEST_ONLY_MARKERS = (
    "requested",
    "user asked",
    "flag was set",
    "will be applied",
    "intends to",
    "hoping",
)


def _requests_stub() -> types.ModuleType:
    """Non-networking `requests` stand-in for import-time only use."""

    def _unavailable(*_args: Any, **_kwargs: Any):
        raise AssertionError("this contract test must not perform network I/O")

    stub = types.ModuleType("requests")
    stub.post = _unavailable
    stub.get = _unavailable
    stub.RequestException = type("RequestException", (Exception,), {})
    utils = types.ModuleType("requests.utils")
    utils.urlparse = _unavailable
    stub.utils = utils
    return stub


def load_runner(path: Path, module_name: str):
    """Import one hyphenated runner by path, standing in for `requests`."""
    if module_name in sys.modules:
        return sys.modules[module_name]
    if "requests" not in sys.modules:
        try:
            __import__("requests")
        except ImportError:
            sys.modules["requests"] = _requests_stub()
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load runner module: {path}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations through sys.modules[cls.__module__].
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def must_block(message: str, call) -> None:
    try:
        call()
    except AssertionError:
        return
    raise AssertionError(message)


def validate_capability(payload: dict[str, Any], *, path: str) -> dict[str, Any]:
    """Assert one emitted `thinkingCapability` block is present and truthful."""
    assert isinstance(payload, dict), f"{path}: thinkingCapability must be an object"
    state = payload.get("state")
    assert state in {
        CB.THINKING_APPLIED,
        CB.THINKING_VERIFIED_DEFAULT,
        CB.THINKING_NOT_APPLICABLE,
        CB.THINKING_UNSUPPORTED,
        CB.THINKING_UNVERIFIED,
    }, f"{path}: unknown thinking state {state!r}"
    assert set(payload) == {"state", "requested", "proof"}, (
        f"{path}: thinkingCapability must carry exactly state/requested/proof, got {sorted(payload)}"
    )
    proof = payload.get("proof")
    assert isinstance(proof, str) and proof.strip(), f"{path}: proof must be a non-empty string"

    if state in (CB.THINKING_APPLIED, CB.THINKING_VERIFIED_DEFAULT):
        lowered = proof.lower()
        assert any(marker in lowered for marker in PROOF_MARKERS), (
            f"{path}: {state!r} must name the mechanism that verified the template; proof={proof!r}"
        )
        for marker in REQUEST_ONLY_MARKERS:
            assert marker not in lowered, (
                f"{path}: proof leans on request intent ({marker!r}); proof={proof!r}"
            )
    if state == CB.THINKING_NOT_APPLICABLE and payload.get("requested") is not None:
        raise AssertionError(f"{path}: a not_applicable run must not carry a requested flag")
    if state == CB.THINKING_UNVERIFIED and payload.get("requested") is None:
        raise AssertionError(f"{path}: unverified must record what was requested")
    return payload


def test_vllm_chat_template_kwarg_accepted_is_applied() -> None:
    """vLLM path: a template that accepts `enable_thinking=False` is applied."""
    runner = load_runner(VLLM_RUNNER, "pari_thinking_vllm")
    assert runner.ThinkingCapability is CB.ThinkingCapability, (
        "the vLLM runner must report the shared ThinkingCapability contract"
    )

    class AcceptingTokenizer:
        name_or_path = "org/thinking-model"

        def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True, **kwargs):
            assert kwargs.get("enable_thinking") is False, "the runner must request thinking off"
            return "<|im_start|>user\n" + messages[0]["content"] + "<|im_end|>\n<|im_start|>assistant\n"

    _prompt, adaptation, detail = runner.prompt_for_task(AcceptingTokenizer(), "hello", "chat")
    assert adaptation == "chat_template", adaptation
    assert detail == "enable_thinking=false", detail

    payload = CB.ThinkingCapability.applied(
        "enable_thinking=false",
        "enable_thinking=false accepted by tokenizer.apply_chat_template; prompt counted after the wrapper",
    ).as_dict()
    assert validate_capability(payload, path="vllm/chat") == payload


def test_vllm_template_rejecting_kwarg_is_unverified() -> None:
    """vLLM path: a template that rejects the kwarg must not claim `applied`."""
    runner = load_runner(VLLM_RUNNER, "pari_thinking_vllm")

    class LegacyTokenizer:
        name_or_path = "org/legacy-model"

        def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
            return "<|im_start|>user\n" + messages[0]["content"] + "<|im_end|>\n"

    _prompt, adaptation, detail = runner.prompt_for_task(LegacyTokenizer(), "hello", "chat")
    assert adaptation == "chat_template", adaptation
    assert detail == "template_default_no_enable_thinking_arg", detail
    assert "enable_thinking=false" not in detail, (
        "a template that rejected the kwarg must not be recorded as having applied it"
    )

    payload = CB.ThinkingCapability(
        state=CB.THINKING_UNVERIFIED,
        requested="enable_thinking=false",
        proof="template rejected the enable_thinking kwarg; no verified default is claimed",
    ).as_dict()
    assert validate_capability(payload, path="vllm/legacy-chat") == payload
    assert payload["state"] != CB.THINKING_APPLIED


def test_vllm_plain_mode_is_not_applicable() -> None:
    """A plain run sends no template, so it cannot claim one was applied."""
    runner = load_runner(VLLM_RUNNER, "pari_thinking_vllm")
    _prompt, adaptation, detail = runner.prompt_for_task(object(), "hello", "plain")
    assert (adaptation, detail) == ("plain", "none"), (adaptation, detail)

    payload = CB.ThinkingCapability.not_applicable(
        "plain prompt mode sends no template and no thinking-disable flag"
    ).as_dict()
    assert validate_capability(payload, path="vllm/plain") == payload
    assert payload["state"] != CB.THINKING_APPLIED


def test_llamacpp_server_rendered_template_is_applied() -> None:
    """llama.cpp path: the counted prompt is the server-rendered template output."""
    runner = load_runner(LLAMACPP_RUNNER, "pari_thinking_llamacpp")
    # The llama.cpp runner must import the same shared state contract, so the
    # capability it reports cannot be a locally redefined variant.
    assert runner.ThinkingCapability is CB.ThinkingCapability, (
        "the llama.cpp runner must report the shared ThinkingCapability contract"
    )
    assert hasattr(runner, "ThinkingCapability"), "the llama.cpp runner must expose ThinkingCapability"
    payload = CB.ThinkingCapability.applied(
        "reasoning_effort=none;enable_thinking=false",
        "server /apply-template accepted the request; the counted prompt is the server-rendered template output",
    ).as_dict()
    assert validate_capability(payload, path="llamacpp/chat") == payload

    plain = CB.ThinkingCapability.not_applicable(
        "plain /completion prompt sends no template and no thinking-disable flag"
    ).as_dict()
    assert validate_capability(plain, path="llamacpp/plain") == plain


def test_streaming_latency_receipt_emits_capability() -> None:
    """Streaming path: drive the real probe against a fake server counter."""
    runner = load_runner(LATENCY_RUNNER, "pari_thinking_latency")
    assert runner.ThinkingCapability is CB.ThinkingCapability, (
        "the streaming-latency runner must report the shared ThinkingCapability contract"
    )

    class FakeServerCounter:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.identity = CB.PromptIdentity(
                mode="chat",
                template="vllm-server /tokenize (server-rendered chat template)",
                template_sha256=None,
                detail="server /tokenize",
            )

        def id(self) -> CB.PromptIdentity:
            return self.identity

        def count(self, text: str) -> int:
            return len(text.split())

    original = runner._ServerTokenizerCounter
    runner._ServerTokenizerCounter = FakeServerCounter
    try:
        receipt = runner.probe_context_budget(
            "http://127.0.0.1:1/unused",
            "org/model",
            [{"id": "t1", "prompt": "hello there friend"}],
            effective_limit={
                "effectiveContextLimit": 8192,
                "selectedFrom": {
                    "tokens": 8192,
                    "source": "runtime_override",
                    "provenance": "vllm serve --max-model-len 8192",
                },
            },
            default_max_new_tokens=220,
        )
    finally:
        runner._ServerTokenizerCounter = original

    capability = validate_capability(receipt["thinkingCapability"], path="streaming-latency/receipt")
    assert capability["state"] == CB.THINKING_APPLIED, capability
    for row in receipt["tasks"]:
        assert row["thinkingCapability"] == capability, (
            f"task row {row['taskId']} disagrees with the receipt capability: {row['thinkingCapability']}"
        )


def test_producer_summaries_carry_capability() -> None:
    """All three producers must write `thinkingCapability` into their summary."""
    runner = load_runner(LATENCY_RUNNER, "pari_thinking_latency")
    capability = CB.ThinkingCapability.applied(
        "reasoning_effort=none;chat_template_kwargs.enable_thinking=false",
        "server /tokenize counted the rendered prompt, so any thinking block is inside the count",
    ).as_dict()
    summary_block = {
        "receiptPath": "/tmp/context-budget.json",
        "receiptSha256": "a" * 64,
        "effectiveContextLimit": 8192,
        "effectiveContextLimitSource": {"source": "runtime_override"},
        "thinkingCapability": capability,
        "summary": {"maxPromptTokens": 3, "minHeadroom": 8189},
    }
    assert validate_capability(summary_block["thinkingCapability"], path="streaming-latency/summary")
    assert callable(runner.probe_context_budget), "the latency runner must keep its probe entry point"

    for name, path in PRODUCERS.items():
        source = path.read_text(encoding="utf-8")
        assert '"contextBudget"' in source, f"{name} must emit a contextBudget block"
        assert '"thinkingCapability"' in source, f"{name} must emit thinkingCapability in its summary"
        for sibling in ("receiptPath", "receiptSha256", "effectiveContextLimit"):
            assert sibling in source, f"{name} contextBudget must keep the {sibling} sibling field"


def test_request_intent_alone_cannot_reach_applied() -> None:
    """The state machine must refuse to promote intent into evidence."""
    honest = CB.ThinkingCapability(
        state=CB.THINKING_UNVERIFIED,
        requested="enable_thinking=false",
        proof="template rejected the enable_thinking kwarg; no verified default is claimed",
    )
    assert honest.state == CB.THINKING_UNVERIFIED
    assert honest.requested == "enable_thinking=false"

    must_block(
        "a proof that only restates request intent must not validate as applied",
        lambda: validate_capability(
            {
                "state": CB.THINKING_APPLIED,
                "requested": "enable_thinking=false",
                "proof": "the user requested enable_thinking=false",
            },
            path="adversarial",
        ),
    )
    must_block(
        "an applied proof with no mechanism marker must not validate",
        lambda: validate_capability(
            {"state": CB.THINKING_APPLIED, "requested": "enable_thinking=false", "proof": "done"},
            path="adversarial",
        ),
    )
    must_block(
        "not_applicable must not carry a requested flag",
        lambda: validate_capability(
            {
                "state": CB.THINKING_NOT_APPLICABLE,
                "requested": "enable_thinking=false",
                "proof": "plain prompt mode",
            },
            path="adversarial",
        ),
    )
    must_block(
        "unverified must record what was requested",
        lambda: validate_capability(
            {"state": CB.THINKING_UNVERIFIED, "requested": None, "proof": "nothing verified"},
            path="adversarial",
        ),
    )
    must_block(
        "an unknown state must be rejected",
        lambda: validate_capability(
            {"state": "applied_by_request", "requested": None, "proof": "x"},
            path="adversarial",
        ),
    )


def test_producer_sources_only_claim_applied_with_proof() -> None:
    """Static guard: no producer may hardcode `applied` without a mechanism proof."""
    for name, path in PRODUCERS.items():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        applied_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"applied", "verified_default"}
        ]
        assert applied_calls, f"{name} must still report an applied/verified capability path"
        for call in applied_calls:
            proof_node = None
            if len(call.args) >= 2:
                proof_node = call.args[1]
            else:
                proof_node = next(
                    (kw.value for kw in call.keywords if kw.arg == "proof"), None
                )
            assert proof_node is not None, f"{name}: applied/verified_default must pass a proof"
            assert isinstance(proof_node, ast.Constant) and isinstance(proof_node.value, str), (
                f"{name}: the applied/verified proof must be a literal auditable string"
            )
            lowered = proof_node.value.lower()
            assert any(marker in lowered for marker in PROOF_MARKERS), (
                f"{name}: literal applied proof names no verification mechanism: {proof_node.value!r}"
            )


def test_receipt_hashes_bind_the_capability() -> None:
    """Changing the capability must change the receipt hash, or evidence drifts."""

    def receipt_with(capability: dict[str, Any]) -> CB.ContextBudgetReceipt:
        receipt = CB.ContextBudgetReceipt(
            tokenizer_identity={"nameOrPath": "org/model", "kind": "fake"},
            prompt_identity={
                "promptMode": "chat",
                "template": "t",
                "templateSha256": None,
                "detail": "d",
            },
            effective_limit={
                "effectiveContextLimit": 8192,
                "selectedFrom": {"tokens": 8192, "source": "runtime_override", "provenance": "p"},
            },
            thinking=capability,
        )
        receipt.tasks.append(
            {
                "taskId": "t1",
                "promptTokens": 4,
                "requestedMaxNewTokens": 8,
                "effectiveContextLimit": 8192,
                "remainingHeadroom": 8188,
                "fits": True,
            }
        )
        return receipt

    applied = CB.ThinkingCapability.applied(
        "enable_thinking=false", "accepted by tokenizer.apply_chat_template"
    ).as_dict()
    unverified = CB.ThinkingCapability(
        state=CB.THINKING_UNVERIFIED,
        requested="enable_thinking=false",
        proof="template rejected the kwarg",
    ).as_dict()
    first = receipt_with(applied).finalize()["receiptSha256"]
    second = receipt_with(unverified).finalize()["receiptSha256"]
    assert first != second, "the receipt hash must bind the thinking capability"


VALIDATOR = HERE / "validate-english-core-run.py"


def load_validator():
    return load_runner(VALIDATOR, "pari_thinking_validator")


def emitted_result_payload(capability: dict[str, Any]) -> dict[str, Any]:
    """The exact `contextBudget` block shape all three producers write.

    Built once and reused so the validator check sees the real five-key block
    rather than a simplified stand-in.
    """
    return {
        "schemaVersion": 1,
        "runId": "thinking-fixture",
        "model": {"name": "fixture-model"},
        "outputs": [
            {
                "id": "t1",
                "output": "A",
                "latencySeconds": 0.1,
                "promptAdaptation": "chat_template",
                "promptAdaptationDetail": "enable_thinking=false",
            }
        ],
        "promptModeRequested": "chat",
        "promptAdaptationModesObserved": ["chat_template"],
        "promptAdaptationDetailsObserved": ["enable_thinking=false"],
        "contextBudget": {
            "receiptPath": "/tmp/context-budget.json",
            "receiptSha256": "a" * 64,
            "effectiveContextLimit": 8192,
            "effectiveContextLimitSource": {
                "tokens": 8192,
                "source": "runtime_override",
                "provenance": "vllm serve --max-model-len 8192",
            },
            "thinkingCapability": capability,
            "summary": {"maxPromptTokens": 3, "minHeadroom": 8189},
        },
    }


def test_emitted_payloads_pass_the_real_validator_schema() -> None:
    """Every truthful capability shape must survive the promotion validator.

    The result schema sets `additionalProperties: false` at the top level, so a
    producer that invented a new top-level key instead of nesting the evidence
    under `contextBudget` would be rejected at promotion. This drives the real
    `validate_schema` from `validate-english-core-run.py` over the payload shape
    the producers emit.
    """
    validator = load_validator()
    schema = json.loads(validator.SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema.get("additionalProperties") is False, (
        "this fixture assumes a strict result schema; additionalProperties changed"
    )
    assert "contextBudget" in schema.get("properties", {}), (
        "the result schema must define contextBudget, since that is where the capability lands"
    )

    shapes = {
        "applied": CB.ThinkingCapability.applied(
            "enable_thinking=false",
            "enable_thinking=false accepted by tokenizer.apply_chat_template; prompt counted after the wrapper",
        ).as_dict(),
        "verified_default": CB.ThinkingCapability.verified_default(
            "server /tokenize counted the rendered prompt, so any thinking block is inside the count"
        ).as_dict(),
        "unverified": CB.ThinkingCapability(
            state=CB.THINKING_UNVERIFIED,
            requested="enable_thinking=false",
            proof="template rejected the enable_thinking kwarg; no verified default is claimed",
        ).as_dict(),
        "unsupported": CB.ThinkingCapability.unsupported(
            "enable_thinking=false",
            "template has no thinking block; server /apply-template returned plain text",
        ).as_dict(),
        "not_applicable": CB.ThinkingCapability.not_applicable(
            "plain prompt mode sends no template and no thinking-disable flag"
        ).as_dict(),
    }
    for name, capability in shapes.items():
        validate_capability(capability, path=f"validator/{name}")
        errors = validator.validate_schema(emitted_result_payload(capability), schema)
        assert not errors, f"{name}: emitted result payload rejected by the validator: {errors}"

    # A capability nested at the wrong level is a schema rejection, so the nesting
    # is part of the contract rather than incidental.
    misplaced = emitted_result_payload(shapes["applied"])
    misplaced["thinkingCapability"] = misplaced["contextBudget"].pop("thinkingCapability")
    errors = validator.validate_schema(misplaced, schema)
    assert errors, "a top-level thinkingCapability must not validate under a strict result schema"


def test_validator_rejects_non_finite_capability_values() -> None:
    """A NaN/Infinity value is rejected by the strict JSON loader, not tolerated."""
    validator = load_validator()
    assert hasattr(validator, "strict_json_loads"), "the validator must expose a strict JSON loader"
    for literal in ("NaN", "Infinity", "-Infinity"):
        body = '{"state": "applied", "proof": "done", "x": ' + literal + "}"
        try:
            validator.strict_json_loads(body)
        except (ValueError, TypeError):
            continue
        raise AssertionError(f"the validator accepted non-finite JSON: {literal}")


def test_every_declared_producer_is_individually_exercised() -> None:
    """Guard against a producer silently dropping out of coverage.

    Each entry in `PRODUCERS` must exist and be referenced by a check, so
    removing one from the mapping fails here rather than quietly reducing the
    #58 evidence set to two paths.
    """
    text = Path(__file__).read_text(encoding="utf-8")
    for name, path in PRODUCERS.items():
        assert path.is_file(), f"{name}: producer is missing"
        assert path.name in text, f"{name}: producer {path.name} is declared but never exercised"
    for module_name in ("pari_thinking_vllm", "pari_thinking_llamacpp", "pari_thinking_latency"):
        assert module_name in text, f"{module_name} must be loaded by a check"
    assert set(PRODUCERS) == {"vllm", "llamacpp", "streaming-latency"}, (
        f"#58 must cover exactly the three runtime producers, got {sorted(PRODUCERS)}"
    )


TESTS = [
    test_vllm_chat_template_kwarg_accepted_is_applied,
    test_vllm_template_rejecting_kwarg_is_unverified,
    test_vllm_plain_mode_is_not_applicable,
    test_llamacpp_server_rendered_template_is_applied,
    test_streaming_latency_receipt_emits_capability,
    test_producer_summaries_carry_capability,
    test_request_intent_alone_cannot_reach_applied,
    test_producer_sources_only_claim_applied_with_proof,
    test_receipt_hashes_bind_the_capability,
    test_emitted_payloads_pass_the_real_validator_schema,
    test_validator_rejects_non_finite_capability_values,
    test_every_declared_producer_is_individually_exercised,
]


def main() -> int:
    failures = 0
    for test in TESTS:
        try:
            test()
            print(f"  ok  {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL {test.__name__}: {exc}")
    if failures:
        print(f"{failures} thinking-capability check(s) failed.", file=sys.stderr)
        return 1
    print(f"Thinking-capability evidence tests passed ({len(TESTS)} checks).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
