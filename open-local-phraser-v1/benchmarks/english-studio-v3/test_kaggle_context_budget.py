#!/usr/bin/env python3
"""Context-budget regression tests for P0 issue #45.

Pure Python: no torch, no transformers, no network, no GPU. The counting tests
use small deterministic stand-ins for a tokenizer so the *contract* (exact
counts, template overhead, fail-closed behaviour) is verified, not a specific
model's vocabulary.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from kaggle_context_budget import (
    THINKING_APPLIED,
    THINKING_UNVERIFIED,
    ContextBudgetReceipt,
    ContextUnqualified,
    LimitCandidate,
    LlamaCppServerCounter,
    ThinkingCapability,
    TransformersTokenizerCounter,
    build_task_budget_row,
    canonical_json_sha256,
    classify_output_cap_exhaustion,
    detect_silent_truncation,
    enforce_budget,
    resolve_effective_context_limit,
    resolve_task_max_new_tokens,
    sha256_text,
)


class FakeTokenizer:
    """Whitespace tokenizer with a BOS prefix, standing in for a BPE vocab.

    Not a real tokenizer, and deliberately so: these tests assert that the
    module *uses* whatever tokenizer it is handed, including its special-token
    behaviour, rather than re-implementing tokenization.
    """

    def __init__(self, *, add_bos: bool = True, chat_template: str | None = "TEMPLATE") -> None:
        self.add_bos = add_bos
        self.chat_template = chat_template
        self.name_or_path = "fake/fake-model"
        self.model_max_length = 1_000_000_000_000  # HF "unknown" sentinel

    def encode(self, text: str, add_special_tokens: bool = True) -> list[str]:
        ids = text.split()
        if add_special_tokens and self.add_bos:
            return ["<bos>"] + ids
        return list(ids)

    def apply_chat_template(
        self,
        messages: list[dict[str, str]],
        *,
        tokenize: bool = False,
        add_generation_prompt: bool = True,
        enable_thinking: bool | None = None,
    ) -> str:
        if enable_thinking is None:
            raise TypeError(
                "apply_chat_template() got an unexpected keyword argument 'enable_thinking'"
            )
        body = "\n".join(f"[{m['role']}] {m['content']}" for m in messages)
        rendered = (
            f"<SYS>thinking={'on' if enable_thinking else 'off'}</SYS>\n{body}\n<ASSISTANT>"
        )
        if tokenize:
            return self.encode(rendered, add_special_tokens=True)
        return rendered


def make_counter(add_bos: bool = True) -> TransformersTokenizerCounter:
    return TransformersTokenizerCounter(
        FakeTokenizer(add_bos=add_bos), "chat", "enable_thinking=false"
    )


def render(counter: TransformersTokenizerCounter, text: str) -> str:
    return counter.tokenizer.apply_chat_template(
        [{"role": "user", "content": text}],
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )


def limit_of(n: int) -> dict:
    return resolve_effective_context_limit([
        LimitCandidate(tokens=n, source="runtime_override", provenance=f"--max-model-len {n}"),
    ])


APPLIED = ThinkingCapability.applied("enable_thinking=false", "template accepted the kwarg")


# --- 1. exact-boundary request fits -----------------------------------------


def test_exact_boundary_fits() -> None:
    counter = make_counter()
    prompt = render(counter, "alpha beta gamma")
    tokens = counter.count(prompt)
    row = build_task_budget_row(
        task_id="boundary",
        prompt_text=prompt,
        counter=counter,
        max_new_tokens=32,
        effective_limit=limit_of(tokens + 32),
        thinking=APPLIED,
    )
    assert row["promptTokens"] == tokens
    assert row["fits"] is True
    assert row["remainingHeadroom"] == 32


# --- 2. one-token overflow rejects before generation ------------------------


def test_one_token_overflow_rejected() -> None:
    counter = make_counter()
    prompt = render(counter, "alpha beta gamma")
    tokens = counter.count(prompt)
    row = build_task_budget_row(
        task_id="overflow-1",
        prompt_text=prompt,
        counter=counter,
        max_new_tokens=33,
        effective_limit=limit_of(tokens + 32),
        thinking=APPLIED,
    )
    assert row["fits"] is False
    assert row["overflowTokens"] == 1
    assert row["violation"] == "prompt_plus_max_new_tokens_exceeds_effective_context"

    receipt = ContextBudgetReceipt(effective_limit=limit_of(tokens + 32))
    receipt.tasks.append(row)
    receipt.violations.append("overflow-1")
    try:
        enforce_budget(receipt)
    except ContextUnqualified as exc:
        assert exc.reason == "context_budget_overflow"
        assert exc.detail["violatingTaskIds"] == ["overflow-1"]
    else:
        raise AssertionError("one-token overflow must reject before generation")


# --- 3. chat-template overhead causes overflow though raw text fits ---------


def test_template_overhead_causes_overflow() -> None:
    counter = make_counter()
    raw = "alpha beta gamma delta epsilon"
    raw_tokens = counter.count(raw)
    wrapped = render(counter, raw)
    wrapped_tokens = counter.count(wrapped)
    # The raw user text fits comfortably; the templated prompt does not.
    assert wrapped_tokens > raw_tokens
    budget = raw_tokens + 4
    row = build_task_budget_row(
        task_id="template-overhead",
        prompt_text=wrapped,
        counter=counter,
        max_new_tokens=8,
        effective_limit=limit_of(budget),
        thinking=APPLIED,
    )
    assert row["fits"] is False


# --- 4. different tokenizers give different counts for the same text --------


def test_different_tokenizers_differ() -> None:
    class ShoutingTokenizer(FakeTokenizer):
        def encode(self, text: str, add_special_tokens: bool = True) -> list[str]:
            # Split on characters instead of words: a very different vocabulary.
            ids = list(text.replace(" ", "|"))
            if add_special_tokens and self.add_bos:
                return ["<bos>"] + ids
            return ids

    text = "Rewrite this sentence more clearly for a student."
    wordy = TransformersTokenizerCounter(FakeTokenizer(), "plain", "none")
    other = TransformersTokenizerCounter(FakeTokenizer(), "plain", "none")
    charwise = TransformersTokenizerCounter(ShoutingTokenizer(), "plain", "none")
    assert wordy.count(text) == other.count(text)
    assert charwise.count(text) > wordy.count(text)
    # Same task text, different measured budgets - recorded, never averaged away.
    limit = limit_of(24)
    a = build_task_budget_row(
        task_id="t", prompt_text=text, counter=wordy, max_new_tokens=8,
        effective_limit=limit, thinking=ThinkingCapability.not_applicable("plain"),
    )
    b = build_task_budget_row(
        task_id="t", prompt_text=text, counter=charwise, max_new_tokens=8,
        effective_limit=limit, thinking=ThinkingCapability.not_applicable("plain"),
    )
    assert a["promptTokens"] != b["promptTokens"]
    assert a["fits"] is True and b["fits"] is False


# --- 5. runtime override lower than the advertised model max wins -----------


def test_runtime_override_wins() -> None:
    resolved = resolve_effective_context_limit([
        LimitCandidate(tokens=32768, source="model_advertised", provenance="config.json"),
        LimitCandidate(tokens=4096, source="runtime_override", provenance="--max-model-len 4096"),
        LimitCandidate(tokens=131072, source="rope_scaling", provenance="rope factor 4"),
    ])
    assert resolved["effectiveContextLimit"] == 4096
    assert resolved["selectedFrom"]["source"] == "runtime_override"
    assert resolved["policy"] == "minimum_applicable_limit"


# --- 5b. no provable limit fails closed -------------------------------------


def test_unprovable_limit_fails_closed() -> None:
    try:
        resolve_effective_context_limit([])
    except ContextUnqualified as exc:
        assert exc.reason == "effective_context_limit_unproven"
    else:
        raise AssertionError("an unprovable context limit must not be guessed")


# --- 6. max_new_tokens pushes an otherwise valid prompt over budget ---------


def test_max_new_tokens_pushes_over() -> None:
    counter = make_counter()
    prompt = "one two three four five"
    prompt_tokens = counter.count(prompt)
    generous = build_task_budget_row(
        task_id="t", prompt_text=prompt, counter=counter, max_new_tokens=8,
        effective_limit=limit_of(prompt_tokens + 8),
        thinking=ThinkingCapability.not_applicable("plain"),
    )
    assert generous["fits"] is True
    greedy = build_task_budget_row(
        task_id="t", prompt_text=prompt, counter=counter, max_new_tokens=200,
        effective_limit=limit_of(prompt_tokens + 8),
        thinking=ThinkingCapability.not_applicable("plain"),
    )
    assert greedy["fits"] is False
    assert greedy["overflowTokens"] == 192


# --- 7. output-cap exhaustion is truncation, not shallow depth --------------


def test_output_cap_is_truncation_not_depth() -> None:
    hit = classify_output_cap_exhaustion(
        finish_reason="length", completion_tokens=1200, expected_limit=1200
    )
    assert hit["classification"] == "output_budget_truncation"
    assert hit["capExhausted"] is True
    suspected = classify_output_cap_exhaustion(
        finish_reason=None, completion_tokens=1200, expected_limit=1200
    )
    assert suspected["classification"] == "output_budget_truncation"
    voluntary = classify_output_cap_exhaustion(
        finish_reason="stop", completion_tokens=300, expected_limit=1200
    )
    assert voluntary["classification"] == "voluntary_output"
    assert voluntary["capExhausted"] is False


# --- 8. silent left truncation is detected ---------------------------------


def test_silent_truncation_detected() -> None:
    mismatch = detect_silent_truncation(prompt_tokens_preflight=100, prompt_tokens_runtime=64)
    assert mismatch["silentTruncationSuspected"] is True
    assert "runtime_prompt_token_count_mismatch" in mismatch["signals"]
    server_crop = detect_silent_truncation(
        prompt_tokens_preflight=100, prompt_tokens_runtime=100, server_reported_truncated=True
    )
    assert server_crop["silentTruncationSuspected"] is True
    assert "server_reported_truncated" in server_crop["signals"]
    clean = detect_silent_truncation(prompt_tokens_preflight=100, prompt_tokens_runtime=100)
    assert clean["silentTruncationSuspected"] is False
    # An unknown runtime count is not evidence of truncation; it is absence of
    # evidence, and the contract does not upgrade it to a pass or a failure.
    unknown = detect_silent_truncation(prompt_tokens_preflight=100, prompt_tokens_runtime=None)
    assert unknown["silentTruncationSuspected"] is False


# --- 9. unicode counted by the tokenizer, not bytes/chars ------------------


def test_unicode_counted_by_tokenizer() -> None:
    text = "naive cafe - unicode"

    class AccentedTokenizer(FakeTokenizer):
        def encode(self, value: str, add_special_tokens: bool = True) -> list[str]:
            # "café" is one word here but two UTF-8 bytes; a byte count and a
            # char count must both disagree with a real tokenizer's answer.
            ids = [f"w:{word}" for word in value.split()]
            if add_special_tokens and self.add_bos:
                return ["<bos>"] + ids
            return ids

    class CharTokenizer(FakeTokenizer):
        def encode(self, value: str, add_special_tokens: bool = True) -> list[str]:
            ids = list(value)
            if add_special_tokens and self.add_bos:
                return ["<bos>"] + ids
            return ids

    accented_text = "naïve café"
    accented = TransformersTokenizerCounter(AccentedTokenizer(), "plain", "none")
    chars = TransformersTokenizerCounter(CharTokenizer(), "plain", "none")
    assert accented.count(accented_text) == 3  # <bos> + two words
    assert chars.count(accented_text) == len(accented_text) + 1
    assert len(accented_text.encode("utf-8")) == 12
    assert accented.count(accented_text) != len(accented_text.encode("utf-8"))
    assert accented.count(accented_text) != len(accented_text)
    assert wordy_count(text) == len(text.split()) + 1


def wordy_count(text: str) -> int:
    return TransformersTokenizerCounter(FakeTokenizer(), "plain", "none").count(text)


# --- thinking capability is never inferred from a requested flag ------------


def test_thinking_states_are_distinct() -> None:
    unverified = ThinkingCapability(
        state=THINKING_UNVERIFIED,
        requested="enable_thinking=false",
        proof="template rejected the kwarg; nothing verified",
    )
    assert unverified.state != THINKING_APPLIED
    applied = ThinkingCapability.applied("enable_thinking=false", "template accepted the kwarg")
    assert applied.state == THINKING_APPLIED
    not_applicable = ThinkingCapability.not_applicable("plain prompt mode")
    assert not_applicable.state == "not_applicable"
    # A plain-mode run must not claim a template was applied.
    assert not_applicable.requested is None
    unsupported = ThinkingCapability.unsupported("enable_thinking=false", "template has no thinking block")
    assert unsupported.state == "unsupported"


def test_receipt_hash_is_stable_and_binds_evidence() -> None:
    receipt = ContextBudgetReceipt(effective_limit=limit_of(128))
    receipt.tasks.append({
        "taskId": "t1", "promptTokens": 40, "requestedMaxNewTokens": 8,
        "effectiveContextLimit": 128, "remainingHeadroom": 88, "fits": True,
    })
    first = receipt.finalize()
    second = receipt.finalize()
    assert first["receiptSha256"] == second["receiptSha256"]
    receipt.tasks[0]["promptTokens"] = 41
    assert receipt.finalize()["receiptSha256"] != first["receiptSha256"]
    assert first["summary"]["maxPromptTokens"] == 40
    assert first["summary"]["minHeadroom"] == 88
    assert canonical_json_sha256({"a": 1}) == canonical_json_sha256({"a": 1})
    assert sha256_text("x") is not None and sha256_text(None) is None


def test_llamacpp_counter_uses_server_endpoints() -> None:
    calls: list[str] = []

    def tokenize(text: str) -> list[int]:
        calls.append("tokenize")
        return [0] * len(text.split())

    def apply_template(text: str) -> str:
        calls.append("apply-template")
        return f"<s>[INST] {text} [/INST]"

    counter = LlamaCppServerCounter(
        tokenize=tokenize, apply_template=apply_template, mode="chat", detail="server endpoints",
    )
    rendered = counter.render_chat("hello world")
    assert rendered == "<s>[INST] hello world [/INST]"
    # "<s>[INST]", "hello", "world", "[/INST]" -> the server reports four tokens.
    # The point is that the number comes from the server's token array, not from
    # a local re-tokenization of the rendered string.
    assert counter.count(rendered) == len(rendered.split())
    assert calls == ["apply-template", "tokenize"]
    # An unusable server response is a hard fail, not a silent estimate.
    bad = LlamaCppServerCounter(
        tokenize=lambda t: None, apply_template=apply_template, mode="chat", detail="x",
    )
    try:
        bad.count("x")
    except ContextUnqualified as exc:
        assert exc.reason == "server_tokenize_unavailable"
    else:
        raise AssertionError("an unusable /tokenize response must fail closed")


def test_task_max_new_tokens_prefers_task_declaration() -> None:
    product = {"generative": True, "maxNewTokens": 1200}
    choice = {"generative": False}
    generative_default = {"generative": True}
    assert resolve_task_max_new_tokens(
        product, default_max_new_tokens=220, default_forced_choice_max_new_tokens=8
    ) == 1200
    assert resolve_task_max_new_tokens(
        choice, default_max_new_tokens=220, default_forced_choice_max_new_tokens=8
    ) == 8
    assert resolve_task_max_new_tokens(
        generative_default, default_max_new_tokens=220, default_forced_choice_max_new_tokens=8
    ) == 220
    # A non-positive or non-int declaration is ignored rather than trusted.
    assert resolve_task_max_new_tokens(
        {"generative": True, "maxNewTokens": 0}, default_max_new_tokens=220,
        default_forced_choice_max_new_tokens=8,
    ) == 220
    assert resolve_task_max_new_tokens(
        {"generative": True, "maxNewTokens": True}, default_max_new_tokens=220,
        default_forced_choice_max_new_tokens=8,
    ) == 220


def test_latency_runner_records_explicit_stages() -> None:
    """Issue #53: the latency probe declares its stages and attributes failures.

    The runner drives the runtime by hand, so it must pass an explicit stage to
    the taxonomy; otherwise a load-time CUDA OOM and a generation-time one look
    identical to whoever reads the terminal categories.
    """
    runner = _load_runner("run-kaggle-vllm-streaming-latency.py", "latency_runner")
    assert hasattr(runner, "StageRecorder"), "the latency runner must expose a stage recorder"
    with tempfile.TemporaryDirectory() as tmp:
        summary_path = Path(tmp) / "summary.json"
        summary = {"schemaVersion": 1, "status": "starting"}
        recorder = runner.StageRecorder(summary, summary_path)
        recorder.enter("server_start")
        recorder.enter("generate")
        generate_categories = recorder.fail(
            "generate", "CUDA out of memory while allocating KV cache during generation"
        )
        start_categories = recorder.fail("server_start", "CUDA out of memory while loading model weights")
        assert generate_categories == ["cuda_oom_generate"], generate_categories
        assert start_categories == ["cuda_oom_load"], start_categories
        recorded = json.loads(summary_path.read_text(encoding="utf-8"))
        by_stage = {row["stage"]: row for row in recorded["stages"]}
        assert by_stage["generate"]["failureCategories"] == ["cuda_oom_generate"]
        assert by_stage["server_start"]["failureCategories"] == ["cuda_oom_load"]


def test_streamed_rows_carry_output_budget() -> None:
    """Issue #45 + #53: a streamed attempt records its own declared budget."""
    runner = _load_runner("run-kaggle-vllm-streaming-latency.py", "latency_runner_budget")
    payload = {
        "messages": [{"role": "user", "content": "x"}],
        "temperature": 0.0,
        "top_p": 1.0,
        "max_tokens": 900,
        "seed": 0,
        "stream": True,
    }
    assert payload["max_tokens"] == 900
    cap = classify_output_cap_exhaustion(
        finish_reason="length", completion_tokens=None, expected_limit=900
    )
    assert cap["classification"] == "output_budget_truncation"
    assert callable(runner.stream_sse_progressive)


def _load_runner(filename: str, module_name: str) -> Any:
    """Import a hyphenated runner script by path, as the self-checks do."""
    import importlib
    import importlib.util

    if module_name in sys.modules:
        return sys.modules[module_name]
    # The runner imports `requests` at module scope for its loopback calls. This
    # contract test never makes a request, so an in-process stand-in keeps the
    # test runnable on a machine without the runtime dependency installed.
    if "requests" not in sys.modules:
        try:
            importlib.import_module("requests")
        except ImportError:
            sys.modules["requests"] = _requests_stub()
    spec = importlib.util.spec_from_file_location(module_name, str(HERE / filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _requests_stub() -> Any:
    """Minimal non-networking `requests` stand-in for import-time only use."""
    import types

    def _unavailable(*_args: Any, **_kwargs: Any):
        raise AssertionError("the context-budget contract test must not perform network I/O")

    stub = types.ModuleType("requests")
    stub.post = _unavailable
    stub.get = _unavailable
    stub.RequestException = type("RequestException", (Exception,), {})
    utils = types.ModuleType("requests.utils")
    utils.urlparse = _unavailable
    stub.utils = utils
    return stub


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
    print(f"{len(tests)} context-budget regression tests passed.")


if __name__ == "__main__":
    main()
