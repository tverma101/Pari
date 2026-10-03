#!/usr/bin/env python3
"""Exact tokenizer/template context-budget preflight (P0 benchmark issue #45).

This module is the single shared contract for "does this frozen task fit this
configuration's real context window?". Every canonical runner calls it before
any generation and refuses to start when the answer cannot be proven.

Design rules that are deliberate, not incidental:

* Token counts are *exact*. They come from the pinned HF tokenizer (vLLM path)
  or from the running server's own ``/tokenize`` endpoint (llama.cpp path),
  which is the same ``tokenize_input_prompts(..., add_special=true,
  parse_special=true)`` call the inference path uses. Nothing here estimates
  with character counts, bytes, or a different tokenizer.
* Prompt-mode identity is counted *after* every template/system/user wrapper.
  Raw task text fitting proves nothing on its own.
* The effective context limit is the **minimum** of every applicable limit,
  each with provenance, not the most optimistic one.
* A requested thinking/template flag is never treated as proof that the flag
  was applied. Thinking/template capability is reported as an explicit state
  (see :class:`ThinkingCapability`) that defaults to unverified.
* When the exact tokenizer or template cannot be proven, the caller fails
  closed as ``context_unqualified``. There is no silent truncation, no silent
  fallback tokenizer, and no silent crop of the frozen task.

Runners own their own import wiring; this file never imports transformers,
torch, vLLM, or llama.cpp so it stays importable by the CPU-only structural
self-checks and by the pure-Python unit tests.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = 1

# States for how the chat template / thinking-disable request was *proven* to be
# in effect. `requested` alone is never `applied`.
THINKING_APPLIED = "applied"
THINKING_VERIFIED_DEFAULT = "verified_default"
THINKING_NOT_APPLICABLE = "not_applicable"
THINKING_UNSUPPORTED = "unsupported"
THINKING_UNVERIFIED = "unverified"

_LIMIT_SOURCES = (
    "model_advertised",
    "model_config_max_position_embeddings",
    "rope_scaling",
    "runtime_override",
    "server_api",
    "quantization_or_runtime_restriction",
)


class ContextUnqualified(RuntimeError):
    """Raised when an exact context-budget proof is impossible.

    Callers must surface this as a structured ``context_unqualified`` outcome,
    never as a warning, because continuing would produce a silent crop or a
    rejected-at-runtime request whose failure is not English quality.
    """

    def __init__(self, reason: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or {}

    def as_receipt(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "state": "context_unqualified",
            "reason": self.reason,
            "detail": self.detail,
        }


def sha256_text(text: str | None) -> str | None:
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Effective context limit: minimum of applicable limits, with provenance.


@dataclass(frozen=True)
class LimitCandidate:
    """One applicable context limit and where it came from."""

    tokens: int
    source: str
    provenance: str

    def as_dict(self) -> dict[str, Any]:
        return {"tokens": int(self.tokens), "source": self.source, "provenance": self.provenance}


def resolve_effective_context_limit(candidates: Iterable[LimitCandidate]) -> dict[str, Any]:
    """Pick the minimum applicable limit; refuse when none can be proven.

    An empty candidate set is *not* "assume the model default". It means the
    effective limit is unproven, which fails closed.
    """
    materialized = [
        c
        for c in candidates
        if isinstance(c.tokens, int) and not isinstance(c.tokens, bool) and c.tokens > 0
    ]
    if not materialized:
        raise ContextUnqualified(
            "effective_context_limit_unproven",
            detail={"limits": [c.as_dict() for c in candidates]},
        )
    winner = min(materialized, key=lambda c: c.tokens)
    return {
        "effectiveContextLimit": int(winner.tokens),
        "selectedFrom": winner.as_dict(),
        # Ties are surfaced so a reader can see that the minimum is corroborated
        # rather than a single surprising number.
        "tiedSources": sorted(
            c.as_dict()["source"] for c in materialized if c.tokens == winner.tokens
        ),
        "applicableLimits": sorted(
            (c.as_dict() for c in materialized),
            key=lambda d: (d["tokens"], d["source"]),
        ),
        "policy": "minimum_applicable_limit",
    }


# ---------------------------------------------------------------------------
# Thinking / chat-template capability, reported honestly.


@dataclass(frozen=True)
class ThinkingCapability:
    """Truthful state of a thinking-disable / template request.

    ``requested`` records what the runner asked for. ``state`` only advances to
    ``applied``/``verified_default`` when something actually proved it, which is
    what keeps a flag from being laundered into evidence.
    """

    state: str = THINKING_UNVERIFIED
    requested: str | None = None
    proof: str | None = None

    @classmethod
    def not_applicable(cls, reason: str) -> "ThinkingCapability":
        return cls(state=THINKING_NOT_APPLICABLE, requested=None, proof=reason)

    @classmethod
    def verified_default(cls, proof: str) -> "ThinkingCapability":
        return cls(state=THINKING_VERIFIED_DEFAULT, requested=None, proof=proof)

    @classmethod
    def applied(cls, requested: str, proof: str) -> "ThinkingCapability":
        return cls(state=THINKING_APPLIED, requested=requested, proof=proof)

    @classmethod
    def unsupported(cls, requested: str | None, proof: str) -> "ThinkingCapability":
        return cls(state=THINKING_UNSUPPORTED, requested=requested, proof=proof)

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "requested": self.requested,
            "proof": self.proof,
        }


# ---------------------------------------------------------------------------
# Exact counting. Each backend proves identity of (tokenizer, template, mode).


@dataclass(frozen=True)
class PromptIdentity:
    """Identity of the prompt mode/template used, plus its hash."""

    mode: str
    template: str
    template_sha256: str | None
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "promptMode": self.mode,
            "template": self.template,
            "templateSha256": self.template_sha256,
            "detail": self.detail,
        }


class _Counter:
    """Common counter surface: count text, describe identity."""

    identity: PromptIdentity

    def count(self, text: str) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    def id(self) -> PromptIdentity:
        return self.identity


class TransformersTokenizerCounter(_Counter):
    """Exact count from the pinned HF tokenizer vLLM will use.

    vLLM tokenizes a ``str`` prompt with ``add_special_tokens=True`` and
    ``parse_special=True``, which is exactly ``tokenizer.encode(text)``. For
    chat mode the count is taken *after* ``apply_chat_template`` with
    ``add_generation_prompt=True``, so template overhead is included rather than
    assumed to be zero.

    Note: when ``apply_chat_template(tokenize=False)`` already emitted a BOS and
    the tokenizer also injects BOS via ``add_special_tokens=True``, this counts
    the resulting double-BOS because that is what the runtime actually feeds the
    model. Reproducing the quirk is the point; hiding it would understate the
    true prompt length.
    """

    def __init__(self, tokenizer: Any, mode: str, template_detail: str) -> None:
        self.tokenizer = tokenizer
        raw_template = getattr(tokenizer, "chat_template", None)
        self.identity = PromptIdentity(
            mode=mode,
            template="tokenizer.apply_chat_template" if mode == "chat" else "none/plain",
            template_sha256=sha256_text(raw_template) if isinstance(raw_template, str) else None,
            detail=template_detail,
        )

    def count(self, text: str) -> int:
        # add_special_tokens=True matches vLLM's default string-prompt encoding.
        return len(self.tokenizer.encode(text, add_special_tokens=True))


class LlamaCppServerCounter(_Counter):
    """Exact count via the running llama.cpp server's own ``/tokenize``.

    The inference path calls ``tokenize_input_prompts(vocab, mctx, prompt,
    add_special=true, parse_special=true)``; this counter mirrors that with
    ``add_special=True, parse_special=True`` so the count is the same code path,
    not a re-implementation. Chat identity is the server's ``/apply-template``
    output for the same messages + template kwargs, which routes through the
    same ``oaicompat_chat_params_parse`` as ``/v1/chat/completions``.
    """

    def __init__(self, *, tokenize: Any, apply_template: Any, mode: str, detail: str) -> None:
        self._tokenize = tokenize
        self._apply_template = apply_template
        self.identity = PromptIdentity(
            mode=mode,
            template="llama.cpp /apply-template" if mode == "chat" else "none/plain",
            # The server exposes the template through GET /props; the runner
            # hashes that string separately, so no hash is claimed here rather
            # than hashing a rendered prompt and calling it the template.
            template_sha256=None,
            detail=detail,
        )

    def render_chat(self, text: str) -> str:
        return self._apply_template(text)

    def count(self, text: str) -> int:
        tokens = self._tokenize(text)
        if not isinstance(tokens, list):
            raise ContextUnqualified(
                "server_tokenize_unavailable",
                detail={"response_type": type(tokens).__name__},
            )
        return len(tokens)


# ---------------------------------------------------------------------------
# The receipt: exact, per-task, provenance-bound, and the source of truth that
# gets bound into run provenance.


@dataclass
class ContextBudgetReceipt:
    """Accumulates per-task context-budget evidence for one configuration."""

    schema_version: int = SCHEMA_VERSION
    tokenizer_identity: dict[str, Any] = field(default_factory=dict)
    prompt_identity: dict[str, Any] = field(default_factory=dict)
    effective_limit: dict[str, Any] = field(default_factory=dict)
    thinking: dict[str, Any] = field(default_factory=dict)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)

    @property
    def qualified(self) -> bool:
        return not self.violations

    def summary(self) -> dict[str, Any]:
        prompt_tokens = [t["promptTokens"] for t in self.tasks]
        headrooms = [t["remainingHeadroom"] for t in self.tasks]
        ordered = sorted(prompt_tokens)
        return {
            "maxPromptTokens": max(prompt_tokens) if prompt_tokens else None,
            "p50PromptTokens": _percentile(ordered, 0.50),
            "p95PromptTokens": _percentile(ordered, 0.95),
            "minHeadroom": min(headrooms) if headrooms else None,
            "violationCount": len(self.violations),
            "violatingTaskIds": sorted(self.violations),
            "contextLimitSource": (self.effective_limit.get("selectedFrom") or {}),
        }

    def as_receipt(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "state": "context_qualified" if self.qualified else "context_unqualified",
            "tokenizer": self.tokenizer_identity,
            "promptMode": self.prompt_identity,
            "effectiveContextLimit": self.effective_limit,
            "thinkingCapability": self.thinking,
            "tasks": self.tasks,
            "violatingTaskIds": sorted(self.violations),
            "summary": self.summary(),
            "receiptSha256": None,  # filled by finalize()
        }

    def finalize(self) -> dict[str, Any]:
        """Return the receipt with a stable hash over its evidence payload."""
        receipt = self.as_receipt()
        payload = {k: v for k, v in receipt.items() if k != "receiptSha256"}
        receipt["receiptSha256"] = canonical_json_sha256(payload)
        return receipt


def _percentile(ordered: Sequence[int], q: float) -> int | None:
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[idx]


def build_task_budget_row(
    *,
    task_id: str,
    prompt_text: str,
    counter: _Counter,
    max_new_tokens: int,
    effective_limit: dict[str, Any],
    thinking: ThinkingCapability,
    reasoning_budget_required: bool = False,
) -> dict[str, Any]:
    """Compute one task's exact prompt/headroom/budget row and its verdict."""
    prompt_tokens = counter.count(prompt_text)
    limit = int(effective_limit["effectiveContextLimit"])
    requested = int(max_new_tokens)
    remaining = limit - prompt_tokens
    fits = prompt_tokens + requested <= limit
    row = {
        "taskId": task_id,
        "promptMode": counter.id().mode,
        "templateSha256": counter.id().template_sha256,
        "promptTokens": prompt_tokens,
        "requestedMaxNewTokens": requested,
        "effectiveContextLimit": limit,
        "remainingHeadroom": remaining,
        "fits": fits,
        "reasoningBudgetRelevant": reasoning_budget_required,
        "thinkingCapability": thinking.as_dict(),
    }
    if not fits:
        # The single most important distinction: this is a *request* that does
        # not fit, not a model that produced poor output. Reject before any
        # generation so a runtime crop can never be mistaken for quality.
        row["violation"] = "prompt_plus_max_new_tokens_exceeds_effective_context"
        row["overflowTokens"] = prompt_tokens + requested - limit
    return row


def enforce_budget(receipt: ContextBudgetReceipt) -> dict[str, Any]:
    """Raise :class:`ContextUnqualified` if any task row is over budget."""
    if receipt.violations:
        over = [t for t in receipt.tasks if not t.get("fits", True)]
        detail = {
            "violatingTaskIds": sorted(receipt.violations),
            "example": over[0] if over else None,
        }
        raise ContextUnqualified(
            "context_budget_overflow",
            detail=detail,
        )
    return receipt.finalize()


# ---------------------------------------------------------------------------
# Request-shape guards: honor protocol maxNewTokens, refuse silent truncation.


def resolve_task_max_new_tokens(
    task: dict[str, Any],
    *,
    default_max_new_tokens: int,
    default_forced_choice_max_new_tokens: int,
) -> int:
    """Per-task generation budget, preferring the frozen task's declaration.

    Protocol/product tasks carry their own ``maxNewTokens``; honoring it (rather
    than a single global default) is what keeps the requested budget honest and
    keeps output-cap truncation distinguishable from voluntary short output.
    """
    declared = task.get("maxNewTokens")
    if isinstance(declared, int) and not isinstance(declared, bool) and declared > 0:
        return int(declared)
    if task.get("generative"):
        return int(default_max_new_tokens)
    return int(default_forced_choice_max_new_tokens)


def detect_silent_truncation(
    *,
    prompt_tokens_preflight: int,
    prompt_tokens_runtime: int | None,
    server_reported_truncated: bool | None = None,
) -> dict[str, Any]:
    """Flag any evidence that the runtime cropped or re-tokenized the prompt.

    Two independent signals are checked:

    * a server that reports its prompt as ``truncated`` (llama.cpp), or
    * a runtime prompt-token count that differs from the preflight count,
      which would mean the string we budgeted is not the string consumed.

    Both are treated as disqualifying; neither is auto-corrected.
    """
    signals: list[str] = []
    if server_reported_truncated is True:
        signals.append("server_reported_truncated")
    if (
        isinstance(prompt_tokens_runtime, int)
        and not isinstance(prompt_tokens_runtime, bool)
        and prompt_tokens_runtime != prompt_tokens_preflight
    ):
        signals.append("runtime_prompt_token_count_mismatch")
    return {
        "silentTruncationSuspected": bool(signals),
        "signals": signals,
        "promptTokensPreflight": prompt_tokens_preflight,
        "promptTokensRuntime": prompt_tokens_runtime,
    }


def classify_output_cap_exhaustion(
    *,
    finish_reason: str | None,
    completion_tokens: int | None,
    expected_limit: int | None,
) -> dict[str, Any]:
    """Label a generation that ended on an output/context cap as truncation.

    This keeps "the model chose to output few candidates" (voluntary) separate
    from "the runtime stopped at max_tokens/context" (truncation), which is the
    distinction issue #45 requires for product tasks.
    """
    cap_hit = finish_reason in {"length", "max_tokens", "token_limit"}
    suspected = (
        finish_reason is None
        and isinstance(completion_tokens, int)
        and isinstance(expected_limit, int)
        and completion_tokens >= expected_limit
    )
    return {
        "capExhausted": bool(cap_hit or suspected),
        "classification": "output_budget_truncation" if (cap_hit or suspected) else "voluntary_output",
        "finishReason": finish_reason,
        "completionTokens": completion_tokens,
        "expectedLimit": expected_limit,
    }
