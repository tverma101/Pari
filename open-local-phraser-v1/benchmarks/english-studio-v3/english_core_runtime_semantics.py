"""Versioned runtime-neutral decoding and prompt-adaptation semantics.

GitHub issue #63. One registry consumed by ``validate-english-core-run.py``,
the #60 result-schema self-check, and the #62 cross-runtime parity tests.

The registry does two things and nothing else:

1. It maps a *backend-native* decoding value onto a *logical* sampling mode,
   because the disabled/default sentinel for a parameter differs by runtime
   (vLLM ``topK`` uses ``-1`` or ``0``; llama.cpp and MLX use ``0``). The
   exact raw value is always preserved alongside the logical mode, so no
   backend is forced to report a value it did not actually send.
2. It maps a *concrete* prompt-adaptation adapter onto a *logical* class
   (``chat_template`` / ``plain``), so a registered implementation of
   ``chat_template`` satisfies the contract regardless of which runtime
   produced it, while an unknown adaptation string fails closed.

Everything here is derived from the current result schema and the pinned
runner defaults. Where the current ``decoding`` block cannot express a
notion (notably stop/EOS and llama.cpp speculative decoding), the registry
reports it as ``unrecorded`` and names the runner field that would be
required, rather than inventing a value the outputs do not prove.

Evidence for the native sentinels (verified against the pinned upstreams, not
recalled):

* vLLM 0.30.0 ``vllm/sampling_params.py``: ``top_k: int = 0`` default; the
  validator raises ``"top_k must be 0 (disable), or at least 1"`` only for
  ``top_k < -1``, with the in-source comment "quietly accept -1 as disabled,
  but prefer 0". ``SamplingParams.__post_init__`` additionally forces
  ``top_p = 1.0`` and ``top_k = 0`` whenever ``temperature < _SAMPLING_EPS``
  (greedy), so a negative top-k can never reach the sampler under greedy. The
  request-level path agrees: ``vllm/v1/worker/gpu_input_batch.py`` registers a
  request for top-k only when ``0 < top_k < vocab_size`` and substitutes
  ``vocab_size`` otherwise, which the top-k sampler treats as a no-op.
* llama.cpp ``common/arg.cpp`` / ``tools/server/README.md``: "top-k sampling
  (default: 40, 0 = disabled)"; the server's own default is 40, so ``topK=40``
  on llama.cpp is a real, active top-k and must stay distinct from disabled.
* mlx-lm ``mlx_lm/sample_utils.py``: top-k is applied only under
  ``if top_k > 0``, so ``0`` means disabled; top-p only under
  ``0 < top_p < 1.0``; ``temp == 0`` uses argmax (greedy).

This module is stdlib-only and deterministic. It never raises on unknown
input from a result file: it returns a structured ``unregistered``/
``unrecorded`` state so the caller decides the severity. Raising is reserved
for genuine registry bugs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


# Bumped only when the mapping semantics below change. Reported in the
# validator report and asserted by the parity tests so a semantic change
# cannot land silently.
RUNTIME_SEMANTICS_VERSION = 1


# ---------------------------------------------------------------------------
# Runtime identities
# ---------------------------------------------------------------------------
# Keys are the exact ``model.runtime`` strings the in-tree runners record
# (run-english-core-vllm.py -> "vllm", run-english-core-llamacpp.py ->
# "llama.cpp-server", run-english-core-mlx.py -> "mlx-lm"). A result whose
# runtime is not listed here is *not* an error, but its sentinel meaning is
# unpinned: negative/ambiguous top-k fails closed, everything else is
# reported as an unregistered runtime.

_RUNTIMES: dict[str, dict[str, Any]] = {
    "vllm": {
        "displayName": "vLLM",
        "topKDisabledSentinels": (0, -1),
        "topKActiveFloor": 1,
        "topPUnconstrained": 1.0,
        "greedyTemperatureEpsilon": 1e-5,
        "greedyOverridesTopKAndTopP": True,
        "supportsSpeculativeDecoding": True,
        "recordsStopSequences": False,
        "evidence": (
            "vllm v0.30.0 sampling_params.py: top_k default 0; only top_k < -1 "
            "raises; -1 accepted as disabled (prefer 0); greedy forces top_k=0. "
            "v1/worker/gpu_input_batch.py:409-414 adds a request to top_k_reqs "
            "only when 0 < top_k < vocab_size, and any other value (including -1) "
            "is replaced by vocab_size, which the top-k sampler treats as no-op."
        ),
    },
    "llama.cpp-server": {
        "displayName": "llama.cpp server",
        "topKDisabledSentinels": (0,),
        "topKActiveFloor": 1,
        "topPUnconstrained": 1.0,
        "greedyTemperatureEpsilon": 0.0,
        "greedyOverridesTopKAndTopP": False,
        "supportsSpeculativeDecoding": False,
        "recordsStopSequences": False,
        "evidence": (
            "llama.cpp common/arg.cpp + tools/server/README.md: --top-k "
            "'default: 40, 0 = disabled'; server default top_k is 40 (active)."
        ),
    },
    "mlx-lm": {
        "displayName": "MLX LM",
        "topKDisabledSentinels": (0,),
        "topKActiveFloor": 1,
        "topPUnconstrained": 1.0,
        "greedyTemperatureEpsilon": 0.0,
        "greedyOverridesTopKAndTopP": False,
        "supportsSpeculativeDecoding": False,
        "recordsStopSequences": False,
        "evidence": (
            "mlx-lm sample_utils.make_sampler: top_k applied only when "
            "top_k > 0 (0 disables); top_p only when 0 < top_p < 1.0; temp==0 "
            "is argmax (greedy)."
        ),
    },
}


# ---------------------------------------------------------------------------
# Prompt-adaptation adapters
# ---------------------------------------------------------------------------
# Logical class -> concrete adapter. The adapter string is the exact value a
# runner writes into ``promptAdaptationModesObserved`` / ``promptAdaptation``.
# ``chat_template`` is itself also a registered concrete adapter because the
# vLLM and MLX runners record the bare logical string for the
# ``tokenizer.apply_chat_template`` path; mapping it to the transformers
# adapter keeps the concrete identity recoverable from the raw value.

_ADAPTERS: dict[str, dict[str, Any]] = {
    # Logical chat_template implementations.
    "transformers_apply_chat_template": {
        "logicalClass": "chat_template",
        "runtimes": ("vllm", "mlx-lm"),
        "evidence": (
            "transformers tokenizer.apply_chat_template(add_generation_prompt=True); "
            "vLLM and MLX runners use this path and record the bare 'chat_template' "
            "string (run-english-core-vllm.py:371,376; run-english-core-mlx.py:223)."
        ),
    },
    # Exact string recorded by run-english-core-llamacpp.py:632 (dot, not
    # underscore) and by the Prism wrapper under #62.
    "llama.cpp_embedded_chat_template": {
        "logicalClass": "chat_template",
        "runtimes": ("llama.cpp-server",),
        "evidence": (
            "GGUF-embedded chat template applied by the llama.cpp server through "
            "the OpenAI-compatible API (/apply-template); run-english-core-llamacpp.py "
            "records 'llama.cpp_embedded_chat_template'."
        ),
    },
    # Underscore spelling named in the #63 issue text. Registered explicitly as
    # its own adapter identity rather than a silent alias, so a result that
    # records it is still validated against a concrete known implementation.
    "llama_cpp_embedded_chat_template": {
        "logicalClass": "chat_template",
        "runtimes": ("llama.cpp-server",),
        "evidence": (
            "underscore spelling of the llama.cpp embedded chat-template adapter "
            "named in GitHub issue #63; same registered llama.cpp implementation "
            "as 'llama.cpp_embedded_chat_template'"
        ),
    },
    # Legacy / convenience concrete aliases that resolve to a registered class.
    "chat_template": {
        "logicalClass": "chat_template",
        "runtimes": ("vllm", "mlx-lm"),
        "evidence": "bare logical string recorded by the transformers path; see transformers_apply_chat_template.",
    },
    # Logical plain implementations.
    "plain": {
        "logicalClass": "plain",
        "runtimes": ("vllm", "llama.cpp-server", "mlx-lm"),
        "evidence": "raw task prompt sent with no chat template; all three runners record the literal 'plain'.",
    },
    "plain_fallback": {
        "logicalClass": "plain",
        "runtimes": ("vllm",),
        "evidence": "run-english-core-vllm.py:380 falls back to the raw text when apply_chat_template raises.",
    },
}


_LOGICAL_CLASSES = ("plain", "chat_template")


# Decoding fields the current ``decoding`` object can express, versus notions
# it cannot. Anything here that cannot be expressed is reported as
# ``unrecorded`` and names the runner field that would be required.
_UNRECORDED_NOTIONS: dict[str, str] = {
    "stopSequences": (
        "decoding has no stop-sequence field; a runner would have to add "
        "decoding.stop / decoding.stopTokenIds (and the EOS-ignore flag) before "
        "stop/EOS behaviour can be compared across runtimes"
    ),
    "eosTokenId": (
        "decoding has no EOS-token identity field; a runner would have to add "
        "decoding.eosTokenId so per-runtime EOS semantics are reproducible"
    ),
    "speculativeDecoding": (
        "only vLLM records decoding.speculativeConfig; llama.cpp and MLX record "
        "no speculative field, so speculative settings are comparable only when "
        "both sides explicitly declare them"
    ),
}


@dataclass(frozen=True)
class LogicalMode:
    """One parameter's runtime-neutral reading, with the raw value preserved."""

    parameter: str
    raw: Any
    mode: str
    runtime: str
    registered: bool = True
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "parameter": self.parameter,
            "raw": self.raw,
            "mode": self.mode,
            "runtime": self.runtime,
            "registered": self.registered,
        }
        if self.note:
            payload["note"] = self.note
        return payload


@dataclass(frozen=True)
class AdaptationResolution:
    """A concrete adapter string resolved to its logical class."""

    raw: str
    adapter: str | None
    logical_class: str | None
    registered: bool
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "raw": self.raw,
            "adapter": self.adapter,
            "logicalClass": self.logical_class,
            "registered": self.registered,
        }
        if self.note:
            payload["note"] = self.note
        return payload


@dataclass(frozen=True)
class DecodingNormalization:
    """Runtime-neutral view of a whole ``decoding`` object."""

    runtime: str
    runtime_registered: bool
    parameters: dict[str, LogicalMode] = field(default_factory=dict)
    unrecorded: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "runtime": self.runtime,
            "runtimeRegistered": self.runtime_registered,
            "parameters": {key: mode.as_dict() for key, mode in sorted(self.parameters.items())},
            "unrecorded": dict(sorted(self.unrecorded.items())),
        }

    def mode(self, parameter: str) -> str | None:
        entry = self.parameters.get(parameter)
        return entry.mode if entry else None


def runtime_spec(runtime: str | None) -> dict[str, Any] | None:
    """Return the registered spec for ``runtime`` or None when unregistered."""
    if not isinstance(runtime, str):
        return None
    return _RUNTIMES.get(runtime.strip())


def registered_runtimes() -> tuple[str, ...]:
    return tuple(sorted(_RUNTIMES))


def resolve_adaptation(raw: Any) -> AdaptationResolution:
    """Resolve a concrete adapter string to (adapter, logical class).

    Unknown, empty, or non-string values return ``registered=False`` so the
    caller fails closed. The exact raw value is preserved verbatim.
    """
    if not isinstance(raw, str) or not raw.strip():
        return AdaptationResolution(
            raw=raw if isinstance(raw, str) else repr(raw),
            adapter=None,
            logical_class=None,
            registered=False,
            note="prompt adaptation value is missing or not a non-empty string",
        )
    entry = _ADAPTERS.get(raw)
    if entry is None:
        return AdaptationResolution(
            raw=raw,
            adapter=None,
            logical_class=None,
            registered=False,
            note=(
                f"unknown prompt adaptation adapter {raw!r}; register it in "
                "english_core_runtime_semantics._ADAPTERS before it can satisfy a logical class"
            ),
        )
    return AdaptationResolution(
        raw=raw,
        adapter=raw,
        logical_class=entry["logicalClass"],
        registered=True,
        note=entry["evidence"],
    )


def resolve_adaptations(raw_values: Any) -> list[AdaptationResolution]:
    if not isinstance(raw_values, (list, tuple)):
        value = [] if raw_values is None else [raw_values]
    else:
        value = list(raw_values)
    return [resolve_adaptation(item) for item in value]


def _logical_top_p(raw: Any, spec: dict[str, Any] | None, runtime: str) -> LogicalMode:
    if spec is None:
        return LogicalMode("topP", raw, "unregistered_runtime", runtime, registered=False,
                           note="runtime is not in the registry; top-p meaning is unpinned")
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return LogicalMode("topP", raw, "invalid", runtime, note="topP must be a number")
    value = float(raw)
    if value < 0 or value > 1:
        return LogicalMode("topP", raw, "invalid", runtime, note="topP must be within [0, 1]")
    if value == float(spec["topPUnconstrained"]):
        return LogicalMode("topP", raw, "unconstrained", runtime,
                           note="topP=1.0 applies no nucleus filter in any registered runtime")
    if value == 0:
        # vLLM rejects top_p==0 ("must be in (0, 1]") while llama.cpp / MLX treat
        # it as unconstrained; the meaning is runtime-dependent, so do not
        # pretend it is portable.
        return LogicalMode("topP", raw, "runtime_dependent_zero", runtime,
                           note="topP=0 is rejected by vLLM but treated as unconstrained by llama.cpp/MLX")
    return LogicalMode("topP", raw, "nucleus", runtime, note=f"nucleus filtering at p={value}")


def _logical_top_k(raw: Any, spec: dict[str, Any] | None, runtime: str) -> LogicalMode:
    if spec is None:
        if isinstance(raw, int) and not isinstance(raw, bool) and raw < 0:
            return LogicalMode("topK", raw, "unregistered_negative_top_k", runtime, registered=False,
                               note=(
                                   "negative top-k is only interpretable with a registered runtime's "
                                   "disabled sentinel; this runtime is unregistered, so the value fails closed"
                               ))
        return LogicalMode("topK", raw, "unregistered_runtime", runtime, registered=False,
                           note="runtime is not in the registry; top-k meaning is unpinned")
    if not isinstance(raw, int) or isinstance(raw, bool):
        return LogicalMode("topK", raw, "invalid", runtime, note="topK must be an integer")
    if raw in spec["topKDisabledSentinels"]:
        return LogicalMode("topK", raw, "disabled", runtime,
                           note=(
                               f"topK={raw} is this runtime's registered disabled sentinel "
                               f"{list(spec['topKDisabledSentinels'])}; raw value preserved"
                           ))
    if raw < spec["topKActiveFloor"]:
        return LogicalMode("topK", raw, "unregistered_sentinel", runtime,
                           note=(
                               f"topK={raw} is not a registered sentinel "
                               f"{list(spec['topKDisabledSentinels'])} and is below the active floor "
                               f"{spec['topKActiveFloor']}; fails closed"
                           ))
    return LogicalMode("topK", raw, "active", runtime, note=f"active top-k with k={raw}")


def _logical_temperature(raw: Any, spec: dict[str, Any] | None, runtime: str) -> LogicalMode:
    if spec is None:
        return LogicalMode("temperature", raw, "unregistered_runtime", runtime, registered=False,
                           note="runtime is not in the registry; temperature meaning is unpinned")
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        return LogicalMode("temperature", raw, "invalid", runtime, note="temperature must be a number")
    value = float(raw)
    if value < 0:
        return LogicalMode("temperature", raw, "invalid", runtime, note="temperature must be >= 0")
    if value <= float(spec["greedyTemperatureEpsilon"]):
        note = "zero/epsilon temperature selects greedy decoding"
        if spec["greedyOverridesTopKAndTopP"]:
            note += "; this runtime also overrides topP->1.0 and topK->0 under greedy"
        return LogicalMode("temperature", raw, "greedy", runtime, note=note)
    return LogicalMode("temperature", raw, "stochastic", runtime, note=f"sampling at temperature={value}")


def _logical_seed(raw: Any, runtime: str) -> LogicalMode:
    if raw is None:
        return LogicalMode("seed", raw, "unseeded", runtime,
                           note="no seed recorded; generation is not reproducible from this result")
    if not isinstance(raw, int) or isinstance(raw, bool):
        return LogicalMode("seed", raw, "invalid", runtime, note="seed must be an integer or null")
    return LogicalMode("seed", raw, "seeded", runtime, note=f"generation seeded with {raw}")


def _logical_max_tokens(raw: Any, parameter: str, runtime: str) -> LogicalMode:
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 1:
        return LogicalMode(parameter, raw, "invalid", runtime, note=f"{parameter} must be a positive integer")
    return LogicalMode(parameter, raw, "budget", runtime, note=f"{parameter}={raw} token budget")


def _logical_speculative(decoding: Mapping[str, Any], spec: dict[str, Any] | None, runtime: str) -> LogicalMode:
    if "speculativeConfig" not in decoding:
        if spec is not None and spec["supportsSpeculativeDecoding"]:
            return LogicalMode("speculativeDecoding", None, "unrecorded", runtime,
                               note=(
                                   "speculative decoding is available on this runtime but the "
                                   "result does not declare it: "
                                   + _UNRECORDED_NOTIONS["speculativeDecoding"]
                               ))
        return LogicalMode("speculativeDecoding", None, "disabled", runtime,
                           note=(
                               "this runtime exposes no speculative decoding field, so absent "
                               "means speculative decoding was not requested"
                           ))
    config = decoding["speculativeConfig"]
    if config is None:
        return LogicalMode("speculativeDecoding", None, "disabled", runtime,
                           note=(
                               "speculativeConfig explicitly null (no speculative decoding); "
                               "same logical mode as a runtime with no speculative field"
                           ))
    if not isinstance(config, Mapping):
        return LogicalMode("speculativeDecoding", config, "invalid", runtime,
                           note="speculativeConfig must be an object or null")
    return LogicalMode("speculativeDecoding", dict(config), "enabled", runtime,
                       note=f"speculative decoding enabled: {dict(config)!r}")


def normalize_decoding(decoding: Mapping[str, Any] | None, runtime: str | None) -> DecodingNormalization:
    """Normalize a result's ``decoding`` object against the runtime registry.

    The raw ``decoding`` object is never mutated; every LogicalMode carries the
    exact raw value it was derived from.
    """
    if not isinstance(decoding, Mapping):
        decoding = {}
    runtime_name = runtime.strip() if isinstance(runtime, str) and runtime.strip() else "<missing>"
    spec = runtime_spec(runtime)
    normalization = DecodingNormalization(
        runtime=runtime_name,
        runtime_registered=spec is not None,
    )
    normalization.parameters["topP"] = _logical_top_p(decoding.get("topP"), spec, runtime_name)
    normalization.parameters["topK"] = _logical_top_k(decoding.get("topK"), spec, runtime_name)
    normalization.parameters["temperature"] = _logical_temperature(decoding.get("temperature"), spec, runtime_name)
    normalization.parameters["seed"] = _logical_seed(decoding.get("seed"), runtime_name)
    normalization.parameters["maxNewTokens"] = _logical_max_tokens(
        decoding.get("maxNewTokens"), "maxNewTokens", runtime_name
    )
    normalization.parameters["forcedChoiceMaxNewTokens"] = _logical_max_tokens(
        decoding.get("forcedChoiceMaxNewTokens"), "forcedChoiceMaxNewTokens", runtime_name
    )
    normalization.parameters["speculativeDecoding"] = _logical_speculative(decoding, spec, runtime_name)

    # Notions the current decoding object cannot express.
    normalization.unrecorded["stopSequences"] = _UNRECORDED_NOTIONS["stopSequences"]
    normalization.unrecorded["eosTokenId"] = _UNRECORDED_NOTIONS["eosTokenId"]

    # Requested vs effective: a runtime that collapses top-k/top-p under greedy
    # makes the recorded value inert. The requested reading above is kept
    # (topK=40 stays distinct from disabled, per issue #63) and the effective
    # reading is recorded alongside it so an inert value is never mistaken for
    # proof that the filter ran.
    if spec is not None and spec["greedyOverridesTopKAndTopP"] and normalization.mode("temperature") == "greedy":
        for parameter, effective in (("topK", "disabled"), ("topP", "unconstrained")):
            entry = normalization.parameters[parameter]
            normalization.parameters[parameter] = LogicalMode(
                parameter=entry.parameter,
                raw=entry.raw,
                mode=entry.mode,
                runtime=entry.runtime,
                registered=entry.registered,
                note=(
                    f"{entry.note}; effective mode under greedy is {effective} because "
                    f"{spec['displayName']} forces topK/topP when temperature is at or below "
                    f"{spec['greedyTemperatureEpsilon']}"
                ),
            )
    return normalization


def comparable_sampling_key(normalization: DecodingNormalization) -> tuple[Any, ...]:
    """A key for asserting two runs requested the same logical sampling.

    Only the *logical* modes participate. Raw backend values deliberately do
    not, because vLLM ``-1`` and llama.cpp ``0`` are the same request. Raises
    ValueError for an unregistered runtime so cross-runtime parity can never
    be asserted against unpinned sentinel meaning.
    """
    if not normalization.runtime_registered:
        raise ValueError(
            f"runtime {normalization.runtime!r} is not in the runtime-semantics registry; "
            "cross-runtime parity cannot be asserted"
        )
    return (
        normalization.mode("topK"),
        normalization.mode("topP"),
        normalization.mode("temperature"),
        normalization.mode("seed"),
        normalization.mode("maxNewTokens"),
        normalization.mode("forcedChoiceMaxNewTokens"),
        normalization.mode("speculativeDecoding"),
    )


def decoding_equivalence(left: DecodingNormalization, right: DecodingNormalization) -> tuple[bool, list[str]]:
    """Compare two normalizations on logical sampling only.

    Returns ``(equivalent, reasons)``. Unregistered runtimes are never
    equivalent; the raw ``topK`` values are reported alongside the verdict so a
    caller can show that ``-1`` and ``0`` were preserved but agreed logically.
    """
    reasons: list[str] = []
    for label, norm in (("left", left), ("right", right)):
        if not norm.runtime_registered:
            reasons.append(f"{label} runtime {norm.runtime!r} is not registered")
    if reasons:
        return False, reasons
    left_key = comparable_sampling_key(left)
    right_key = comparable_sampling_key(right)
    if left_key == right_key:
        return True, []
    names = ["topK", "topP", "temperature", "seed", "maxNewTokens", "forcedChoiceMaxNewTokens", "speculativeDecoding"]
    for name, a, b in zip(names, left_key, right_key):
        if a != b:
            reasons.append(f"{name}: left mode {a!r} != right mode {b!r}")
    return False, reasons


def registry_summary() -> dict[str, Any]:
    """A stable, serializable description of the registry for reports/tests."""
    return {
        "runtimeSemanticsVersion": RUNTIME_SEMANTICS_VERSION,
        "runtimes": {
            name: {
                "displayName": spec["displayName"],
                "topKDisabledSentinels": list(spec["topKDisabledSentinels"]),
                "topKActiveFloor": spec["topKActiveFloor"],
                "supportsSpeculativeDecoding": spec["supportsSpeculativeDecoding"],
            }
            for name, spec in sorted(_RUNTIMES.items())
        },
        "adapters": {
            name: {"logicalClass": entry["logicalClass"], "runtimes": list(entry["runtimes"])}
            for name, entry in sorted(_ADAPTERS.items())
        },
        "logicalClasses": list(_LOGICAL_CLASSES),
        "unrecordedNotions": dict(sorted(_UNRECORDED_NOTIONS.items())),
    }
