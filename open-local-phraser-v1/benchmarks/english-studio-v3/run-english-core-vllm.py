#!/usr/bin/env python3
"""Run a frozen Pari English Core JSONL screen with vLLM on CUDA.

This runner does inference only. It never opens lane answer files or invokes a
model-as-judge. Each completed chunk is atomically checkpointed to the result
JSON so an interrupted Kaggle session leaves recoverable work.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import inspect
import json
import os
import platform
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from word_studio_output_parser import (
    BULLET_RE,
    OPTIONS_ARRAY_PREFIX,
    ROUTE_ALTERNATIVES,
    CandidateLedger,
    comparison_key,
    diagnose,
    partial_option_values as parser_partial_option_values,
    unescape_json_string as parser_unescape_json_string,
    normalize,
    parse_options,
    partial_candidate_count,
)
from kaggle_context_budget import (
    ContextBudgetReceipt,
    ContextUnqualified,
    LimitCandidate,
    ThinkingCapability,
    TransformersTokenizerCounter,
    build_task_budget_row,
    classify_output_cap_exhaustion,
    detect_silent_truncation,
    enforce_budget,
    resolve_effective_context_limit,
    resolve_task_max_new_tokens,
)

HERE = Path(__file__).resolve().parent
DEFAULT_TASKS = HERE / "english-core-fixed-screen.jsonl"
# Issue #60: the canonical result document's schema identity. Emitted on every
# fresh run and preserved on resume; the strict promotion validator reads it.
RESULT_SCHEMA_VERSION = 1
# The promotion validator compares this hash against the exact schema bytes it
# validated, so the producer records the schema it was written against instead
# of asking a human to remember which revision of the schema a run used.
RESULT_SCHEMA_PATH = HERE / "english-core-result-schema.json"


# ---------------------------------------------------------------------------
# Shared progressive useful-option timing contract (Issue #29).

# This block is the single source of truth for first-1/3/10 usable-candidate
# timing. run-english-core-llamacpp.py, run-kaggle-vllm-candidate.py and
# run-kaggle-vllm-streaming-latency.py load it from here by path so the vLLM,
# llama.cpp and latency-probe paths cannot drift apart. Candidate semantics come
# only from the frozen word_studio_output_parser contract: this code never
# re-decides what a candidate is, it only timestamps candidates it accepts.
# ---------------------------------------------------------------------------

PROGRESSIVE_SCHEMA_VERSION = 1
USABLE_OPTION_THRESHOLDS = (1, 3, 10)
PROGRESSIVE_FIELD_BY_THRESHOLD = {
    1: "firstCandidateLatencySeconds",
    3: "firstThreeCandidatesLatencySeconds",
    10: "firstTenCandidatesLatencySeconds",
}
NEWLINE = chr(10)
# A candidate can only complete on one of these characters in every parser mode:
# a closing JSON quote, a closing bracket/brace, or a line break.
CANDIDATE_COMPLETION_MARKS = frozenset(('"', NEWLINE, "]", "}"))


def unescape_json_string(value: str) -> str:
    """Kept as a module-level name; the shared parser owns the implementation."""
    return parser_unescape_json_string(value)


def partial_option_values(raw: str) -> tuple[list[str], str]:
    """Recover the identities of the candidates completed so far.

    Delegates to word_studio_output_parser.partial_option_values, which is the
    shared implementation every streaming runner uses. That helper only recovers
    string-typed JSON entries and understands fenced output, so identity recovery
    cannot diverge from the frozen parser contract.
    """
    return parser_partial_option_values(raw)


class ProgressiveOptionTracker:
    """Monotonic first-1/3/10 unique usable-candidate timing for one response.

    A threshold advances only for candidates the frozen Word Studio contract
    accepts: non-empty, not commentary/prose, not an unchanged copy of the source,
    and not a normalized duplicate of an already-counted candidate. Raw
    completed-candidate counts stay separate from the usable count, a threshold is
    timestamped exactly once, and thresholds never reached stay null.
    """

    def __init__(
        self,
        *,
        source: str | None = None,
        requested: int = 10,
        applicable: bool = True,
        route: str = ROUTE_ALTERNATIVES,
        protected: Any = None,
    ) -> None:
        self.source = source
        self.requested = requested
        self.applicable = applicable
        self.route = route
        self._ledger = CandidateLedger(
            source=source, requested=requested, route=route, protected=protected
        )
        self.started = time.monotonic()
        self.chunk_index = 0
        self.observations = 0
        self.raw_completed_count = 0
        self.identified_count = 0
        self.usable_unique_count = 0
        self.duplicate_count = 0
        self.near_duplicate_count = 0
        self.commentary_count = 0
        self.unchanged_source_count = 0
        self.protected_corruption_count = 0
        self.visually_empty_candidate_count = 0
        self.extraction_mismatch_count = 0
        self.parser_modes: list[str] = []
        self._seen: set[str] = set()
        self._accepted: list[str] = []
        self._crossings: dict[int, dict[str, Any]] = {}
        self.last_observed_at: float | None = None

    def accept_candidate(self, value: str) -> None:
        """Apply the frozen diagnostics contract to one completed candidate.

        Admission is delegated to CandidateLedger, the same object offline
        `diagnose` uses, so streamed first-1/3/10 thresholds and offline
        usableUniqueCount cannot disagree about duplicates, commentary,
        unchanged-source copies or protected-content corruption.
        """
        verdict = self._ledger.add(value)
        reason = verdict.reason
        if reason == "commentary":
            self.commentary_count += 1
        elif reason == "unchanged_source":
            self.unchanged_source_count += 1
        elif reason == "duplicate":
            self.duplicate_count += 1
        elif reason == "protected_corruption":
            self.protected_corruption_count += 1
        elif reason == "near_duplicate":
            self.near_duplicate_count += 1
        elif reason == "visually_empty":
            self.visually_empty_candidate_count += 1
        if not verdict.usable:
            return
        self._seen.add(verdict.key)
        self._accepted.append(value)
        self.usable_unique_count += 1

    def observe(self, delta: str, accumulated: str) -> None:
        """Record one streamed chunk. accumulated is the full response text so far."""
        self.observations += 1
        self.chunk_index += 1
        self.last_observed_at = time.monotonic()
        if not self.applicable:
            return
        if not CANDIDATE_COMPLETION_MARKS.intersection(str(delta or "")):
            return
        self.scan(accumulated, self.last_observed_at)

    def scan(self, accumulated: str, now: float) -> None:
        """Apply the parser contract to the accumulated text at a known instant."""
        return self._scan(accumulated, now, final=False)

    def _scan(self, accumulated: str, now: float, *, final: bool) -> None:
        frozen_count = partial_candidate_count(accumulated)
        values, mode = partial_option_values(accumulated)
        if final:
            options, final_mode = parse_options(accumulated)
            if options:
                values, mode = options, final_mode
        if len(values) > frozen_count:
            # The frozen counter stays authoritative: identity recovery can never
            # report more candidates than the frozen parser has accepted.
            self.extraction_mismatch_count += 1
            values = values[:frozen_count]
        self.raw_completed_count = max(self.raw_completed_count, frozen_count)
        if not self.parser_modes or self.parser_modes[-1] != mode:
            self.parser_modes.append(mode)
        for value in values[self.identified_count:]:
            self.identified_count += 1
            self.accept_candidate(value)
        elapsed = round(now - self.started, 6)
        for threshold in USABLE_OPTION_THRESHOLDS:
            if threshold in self._crossings or self.usable_unique_count < threshold:
                continue
            snapshot = diagnose(
                NEWLINE.join("- " + value for value in self._accepted[:threshold]),
                source=self.source,
                requested=self.requested,
            )
            self._crossings[threshold] = {
                "threshold": threshold,
                "field": PROGRESSIVE_FIELD_BY_THRESHOLD[threshold],
                "chunkIndex": self.chunk_index,
                "elapsedSeconds": elapsed,
                "uniqueUsableCount": self.usable_unique_count,
                "rawCompletedCount": self.raw_completed_count,
                "parserMode": mode,
                "statuses": snapshot["statuses"],
            }

    def finish(self, final_text: str) -> None:
        """Close the stream at the last observed instant.

        A candidate that completes exactly with the final chunk (for example the
        last line of a newline list, which has no trailing newline) is timestamped
        with that chunk's arrival. Nothing is regenerated and no candidate that the
        stream never delivered is counted.
        """
        if not self.applicable:
            return
        self._scan(final_text, self.last_observed_at or self.started, final=True)

    def final_diagnostics(self, final_text: str) -> dict[str, Any]:
        return diagnose(
            final_text,
            source=self.source,
            requested=self.requested,
            route=self.route,
            protected=self._ledger.protected,
        )

    def result(self, final_text: str = "") -> dict[str, Any]:
        """Return the shared schema: threshold fields plus the evidence block."""
        fields: dict[str, Any] = {}
        for threshold, field in PROGRESSIVE_FIELD_BY_THRESHOLD.items():
            crossing = self._crossings.get(threshold)
            fields[field] = crossing["elapsedSeconds"] if crossing else None
        evidence = {
            "schemaVersion": PROGRESSIVE_SCHEMA_VERSION,
            "applicable": self.applicable,
            "clock": "time.monotonic",
            "thresholds": list(USABLE_OPTION_THRESHOLDS),
            "requestedCount": self.requested,
            "route": self._ledger.route,
            "rawCompletedCandidateCount": self.raw_completed_count,
            "uniqueUsableCandidateCount": self.usable_unique_count,
            "duplicateCandidateCount": self.duplicate_count,
            "nearDuplicateCandidateCount": self.near_duplicate_count,
            "commentaryCandidateCount": self.commentary_count,
            "unchangedSourceCandidateCount": self.unchanged_source_count,
            "protectedContentCorruptionCount": self.protected_corruption_count,
            "visuallyEmptyCandidateCount": self.visually_empty_candidate_count,
            "identityExtractionMismatchCount": self.extraction_mismatch_count,
            "streamChunkCount": self.chunk_index,
            "parserModesObserved": list(self.parser_modes),
            "crossings": [self._crossings[key] for key in sorted(self._crossings)],
            "unmetThresholds": [t for t in USABLE_OPTION_THRESHOLDS if t not in self._crossings],
        }
        return {
            **fields,
            "progressiveOptionTiming": evidence,
            "diagnostics": self.final_diagnostics(final_text) if self.applicable else None,
        }


def summarize_progressive_option_timing(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate progressive timing across output rows without inventing values."""
    applicable = [row for row in rows if (row.get("progressiveOptionTiming") or {}).get("applicable")]
    crossed: dict[str, int] = {}
    null_preserved: dict[str, int] = {}
    for field in PROGRESSIVE_FIELD_BY_THRESHOLD.values():
        hit = sum(1 for row in applicable if isinstance(row.get(field), (int, float)))
        crossed[field] = hit
        null_preserved[field] = len(applicable) - hit
    return {
        "schemaVersion": PROGRESSIVE_SCHEMA_VERSION,
        "thresholds": list(USABLE_OPTION_THRESHOLDS),
        "fields": list(PROGRESSIVE_FIELD_BY_THRESHOLD.values()),
        "applicableRows": len(applicable),
        "inapplicableRows": len(rows) - len(applicable),
        "crossedRowCounts": crossed,
        "nullPreservedRowCounts": null_preserved,
        "uniqueUsableCandidateCounts": [
            (row.get("progressiveOptionTiming") or {}).get("uniqueUsableCandidateCount")
            for row in applicable
        ],
    }


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str | None) -> str | None:
    return sha256_bytes(text.encode("utf-8")) if text else None


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def resolve_path(value: str | None) -> Path:
    if value is None:
        return DEFAULT_TASKS
    path = Path(value)
    if not path.is_absolute():
        local = HERE / path
        if local.exists():
            return local.resolve()
        path = Path.cwd() / path
    return path.resolve()


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            # Issue #60: allow_nan=False keeps NaN/Infinity out of the result
            # document. Python would otherwise write bare `NaN`, which is not
            # JSON and which the strict promotion loader rejects; failing here
            # is better than emitting a file that silently cannot be validated.
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def prompt_for_task(tokenizer: Any, text: str, mode: str) -> tuple[str, str, str]:
    if mode == "plain":
        return text, "plain", "none"
    messages = [{"role": "user", "content": text}]
    try:
        try:
            prompt = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            return prompt, "chat_template", "enable_thinking=false"
        except TypeError:
            prompt = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            return prompt, "chat_template", "template_default_no_enable_thinking_arg"
    except Exception:
        if mode == "chat":
            raise
        return text, "plain_fallback", "chat_template_failed"


def model_context_limit_candidates(
    tokenizer: Any,
    config: Any,
    *,
    model: str,
    revision: str,
    runtime_max_model_len: int,
) -> list[LimitCandidate]:
    """Collect every *provable* applicable context limit for this configuration.

    Each candidate carries provenance so the receipt can be audited later. The
    vLLM ``--max-model-len`` override is always included; the model's advertised
    limits are read from the pinned ``config.json`` at the same commit the
    weights and tokenizer came from, never from the model card.
    """
    candidates = [
        LimitCandidate(
            tokens=int(runtime_max_model_len),
            source="runtime_override",
            provenance=f"vllm --max-model-len {runtime_max_model_len}",
        )
    ]
    tokenizer_max = getattr(tokenizer, "model_max_length", None)
    # HF sets model_max_length to a sentinel (very large int) when unknown; only a
    # plausible finite value is a real advertised limit.
    if (
        isinstance(tokenizer_max, int)
        and not isinstance(tokenizer_max, bool)
        and 0 < tokenizer_max < 1_000_000_000
    ):
        candidates.append(
            LimitCandidate(
                tokens=int(tokenizer_max),
                source="model_advertised",
                provenance=f"tokenizer.model_max_length from {model}@{revision}",
            )
        )
    config_max = getattr(config, "max_position_embeddings", None)
    if isinstance(config_max, int) and not isinstance(config_max, bool) and 0 < config_max < 1_000_000_000:
        candidates.append(
            LimitCandidate(
                tokens=int(config_max),
                source="model_config_max_position_embeddings",
                provenance=f"config.max_position_embeddings from {model}@{revision}",
            )
        )
    rope = getattr(config, "rope_scaling", None)
    rope_factor = None
    if isinstance(rope, dict):
        raw = rope.get("factor")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            rope_factor = float(raw)
    if rope_factor is not None and rope_factor > 1 and isinstance(config_max, int) and config_max > 0:
        candidates.append(
            LimitCandidate(
                tokens=int(config_max * rope_factor),
                source="rope_scaling",
                provenance=f"config.json rope_scaling factor {rope_factor} over max_position_embeddings {config_max}",
            )
        )
    return candidates


def hash_hub_artifact_manifest(model_id: str, revision: str) -> tuple[str, str, list[dict[str, Any]]]:
    """Hash the pinned Hub file inventory and immutable blob identities."""
    from huggingface_hub import HfApi

    info = HfApi().model_info(model_id, revision=revision, files_metadata=True)
    rows: list[dict[str, Any]] = []
    for sibling in info.siblings or []:
        lfs = getattr(sibling, "lfs", None)
        lfs_oid = getattr(lfs, "oid", None) if lfs else None
        blob_id = getattr(sibling, "blob_id", None) or getattr(sibling, "blobId", None)
        rows.append({
            "path": getattr(sibling, "rfilename", ""),
            "blobId": blob_id,
            "lfsSha256": lfs_oid,
            "size": getattr(sibling, "size", None),
        })
    rows.sort(key=lambda row: row["path"])
    payload = json.dumps(
        {"repo": model_id, "commit": info.sha, "files": rows},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return info.sha, sha256_bytes(payload), rows


def elapsed_metric(metrics: Any, start_field: str, end_field: str) -> float | None:
    if metrics is None:
        return None
    start = getattr(metrics, start_field, None)
    end = getattr(metrics, end_field, None)
    if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end >= start:
        return round(float(end - start), 6)
    return None


def hardware_record() -> dict[str, Any]:
    record: dict[str, Any] = {
        "machine": platform.machine(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "gpu": [],
    }
    try:
        import torch

        record["torchVersion"] = torch.__version__
        record["cudaVersion"] = torch.version.cuda
        if torch.cuda.is_available():
            for index in range(torch.cuda.device_count()):
                prop = torch.cuda.get_device_properties(index)
                record["gpu"].append({
                    "index": index,
                    "name": prop.name,
                    "totalMemoryBytes": int(prop.total_memory),
                    "computeCapability": f"{prop.major}.{prop.minor}",
                })
    except Exception as exc:
        record["gpuInspectionError"] = f"{type(exc).__name__}: {exc}"
    try:
        record["nvidiaSmi"] = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=10,
        ).strip().splitlines()
    except Exception as exc:
        record["nvidiaSmiError"] = f"{type(exc).__name__}: {exc}"
    return record


def validate_resume(
    existing: dict[str, Any],
    *,
    ids: list[str],
    task_hash: str,
    model_repo: str,
    revision: str,
    prompt_mode: str,
    expected_decoding: dict[str, Any],
    benchmark_revision: str,
    expected_context_budget_sha256: str | None = None,
) -> int:
    model = existing.get("model") or {}
    decoding = existing.get("decoding") or {}
    repro = existing.get("reproducibility") or {}
    comparisons = {
        "model.repoOrName": (model.get("repoOrName"), model_repo),
        "model.revision": (model.get("revision"), revision),
        "taskFileSha256": (existing.get("taskFileSha256"), task_hash),
        "taskCount": (existing.get("taskCount"), len(ids)),
        "promptModeRequested": (existing.get("promptModeRequested"), prompt_mode),
        "benchmarkRevision": (repro.get("benchmarkRevision"), benchmark_revision),
    }
    if expected_context_budget_sha256 is not None:
        # Issue #45: a resumed run must be measured under the same proven
        # context budget, not merely the same model and prompt mode.
        comparisons["contextBudget.receiptSha256"] = (
            ((existing.get("contextBudget") or {}).get("receiptSha256")),
            expected_context_budget_sha256,
        )
    for key, expected in expected_decoding.items():
        comparisons[f"decoding.{key}"] = (decoding.get(key), expected)
    mismatches = [f"{key}: existing={actual!r} expected={expected!r}" for key, (actual, expected) in comparisons.items() if actual != expected]
    if mismatches:
        raise SystemExit("Resume identity mismatch; refusing to mix configurations:\n" + "\n".join(mismatches))
    outputs = existing.get("outputs")
    if not isinstance(outputs, list):
        raise SystemExit("Resume result outputs must be an array")
    output_ids = [row.get("id") if isinstance(row, dict) else None for row in outputs]
    expected_prefix = ids[: len(output_ids)]
    if output_ids != expected_prefix:
        raise SystemExit("Resume requires outputs to be the exact unique task-ID prefix; gaps/reordering/duplicates are forbidden")
    return len(outputs)


def streaming_backend(vllm_module: Any) -> tuple[Any, Any]:
    """Resolve the installed vLLM's in-process incremental streaming engine.

    vLLM exposes generation two ways: the synchronous `LLM.generate` batch helper,
    which returns only final RequestOutputs (no incremental output), and an async
    engine that yields a RequestOutput per decode step so `.delta` is the true
    incremental text. First-1/3/10 usable-candidate timing requires the latter, so
    we prefer `AsyncLLM`/`AsyncEngineArgs` when available and fall back to
    `AsyncLLMEngine`. This changes no model identity, prompt, tokenizer, template,
    quantization or benchmark content; it only chooses the streaming interface the
    pinned prebuilt wheel ships.
    """
    if not hasattr(vllm_module, "AsyncEngineArgs"):
        return None, None
    # `AsyncLLM` is the V1 engine that the pinned vLLM 0.30.0 wheel ships. It owns
    # its own background loop, so it can be created and used from sync code. The V0
    # `AsyncLLMEngine` only binds to the running loop that created it, so it is not
    # accepted here; a build without `AsyncLLM` records the limitation instead of
    # silently falling back to the offline batch path.
    async_llm = getattr(vllm_module, "AsyncLLM", None)
    if async_llm is not None:
        return "AsyncLLM", async_llm
    return None, None


def build_streaming_engine_args(
    vllm_module: Any,
    *,
    model: str,
    revision: str,
    engine_kwargs: dict[str, Any],
) -> Any:
    """Build AsyncEngineArgs, keeping only arguments this build actually declares."""
    args_cls = vllm_module.AsyncEngineArgs
    accepted = set(inspect.signature(args_cls).parameters)
    # `LLM.generate` batches and detokenizes in-process; the async engine takes the
    # same core identity arguments. Keep the mapping minimal and version-tolerant.
    filtered = {key: value for key, value in engine_kwargs.items() if key in accepted}
    filtered["model"] = model
    filtered["revision"] = revision
    return args_cls(**filtered)


def create_streaming_engine(vllm_module: Any, kind: str, engine_args: Any) -> Any:
    if kind == "AsyncLLM":
        return vllm_module.AsyncLLM.from_engine_args(engine_args)
    return vllm_module.AsyncLLMEngine.from_engine_args(engine_args)


async def shutdown_streaming_engine(engine: Any) -> None:
    """Release the streaming engine's background loop before the process exits."""
    shutdown = getattr(getattr(engine, "shutdown", None), "__call__", None)
    if shutdown is None:
        return
    result = shutdown()
    if inspect.isawaitable(result):
        await result


def is_word_studio_generative(task: dict[str, Any]) -> bool:
    """Progressive useful-option timing applies only to Word Studio generative rows."""
    return str(task.get("suite") or "").startswith("word_studio_") or bool(task.get("wordStudio"))


def word_studio_source(task: dict[str, Any]) -> str | None:
    return task.get("selectedText") or task.get("sourceText") or None


def word_studio_requested(task: dict[str, Any]) -> int:
    try:
        return int(task.get("requestedCount") or 10)
    except (TypeError, ValueError):
        return 10


def offline_progressive_block(
    reason: str,
    *,
    applicable: bool = False,
    text: str = "",
    source: str | None = None,
    requested: int = 10,
) -> dict[str, Any]:
    """Explicitly null progressive fields for a non-streaming run.

    Offline batch `llm.generate` returns only final RequestOutputs, so there is no
    true progressive output to timestamp. We record the limitation instead of
    estimating first-1/3/10 from the final text. Final parse diagnostics are still
    reported for Word Studio rows so the completed candidate set is preserved as
    evidence. Rows that are not Word Studio generative have no usable-option
    concept at all, so they stay explicitly inapplicable.
    """
    diagnostics = (
        diagnose(text, source=source, requested=requested)
        if applicable and text
        else None
    )
    return {
        **{
            field: None
            for field in PROGRESSIVE_FIELD_BY_THRESHOLD.values()
        },
        "progressiveOptionTiming": {
            "schemaVersion": PROGRESSIVE_SCHEMA_VERSION,
            "applicable": applicable,
            "supported": False,
            "reason": reason,
            "clock": "time.monotonic",
            "thresholds": list(USABLE_OPTION_THRESHOLDS),
            "crossings": [],
            "unmetThresholds": list(USABLE_OPTION_THRESHOLDS),
            "rawCompletedCandidateCount": None if diagnostics is None else diagnostics["parsedCount"],
            "uniqueUsableCandidateCount": None if diagnostics is None else diagnostics["uniqueNormalizedCount"],
            "duplicateCandidateCount": None if diagnostics is None else diagnostics["duplicateCount"],
            "commentaryCandidateCount": None if diagnostics is None else diagnostics["commentaryCandidateCount"],
            "unchangedSourceCandidateCount": None if diagnostics is None else diagnostics["unchangedSourceCount"],
            "streamChunkCount": 0,
            "parserModesObserved": [] if diagnostics is None else [diagnostics["parserMode"]],
        },
        "diagnostics": diagnostics,
    }


async def _stream_one(
    engine: Any,
    request_id: str,
    prompt: str,
    sampling: Any,
    tracker: ProgressiveOptionTracker,
) -> dict[str, Any]:
    """Consume one request's incremental RequestOutputs into a progressive row."""
    started = time.monotonic()
    first_token_seconds: float | None = None
    chunks: list[str] = []
    finish_reason = None
    completion_tokens = 0
    stream = engine.generate(prompt, sampling, request_id=request_id)
    if inspect.isawaitable(stream):
        stream = await stream
    async for request_output in stream:
        outputs = list(getattr(request_output, "outputs", []) or [])
        first_choice = outputs[0] if outputs else None
        if first_choice is None:
            continue
        if getattr(first_choice, "finish_reason", None):
            finish_reason = first_choice.finish_reason
        if getattr(first_choice, "token_ids", None):
            completion_tokens = len(first_choice.token_ids)
        delta = str(getattr(first_choice, "delta", "") or "")
        if not delta:
            continue
        if first_token_seconds is None:
            first_token_seconds = time.monotonic() - started
        chunks.append(delta)
        tracker.observe(delta, "".join(chunks))
    finished = time.monotonic()
    text = "".join(chunks)
    tracker.finish(text)
    if first_token_seconds is None:
        first_token_seconds = finished - started
    row = {
        "latencySeconds": round(finished - started, 6),
        "firstTokenLatencySeconds": round(first_token_seconds, 6),
        "completionTokenCount": completion_tokens,
        "finishReason": finish_reason,
        "output": text,
        "streamChunkCount": len(chunks),
        "streamDeltaSha256": sha256_text(text),
    }
    row.update(tracker.result(text))
    return row


async def _stream_batch(
    engine: Any,
    tasks: list[dict[str, Any]],
    prompts: list[str],
    sampling: list[Any],
    streaming: str,
) -> list[dict[str, Any]]:
    """Stream a batch of prompts, computing progressive timing per Word Studio row."""

    async def run(index: int, task: dict[str, Any]) -> dict[str, Any]:
        tracker = ProgressiveOptionTracker(
            source=word_studio_source(task),
            requested=word_studio_requested(task),
            applicable=is_word_studio_generative(task),
        )
        streamed = await _stream_one(
            engine, task["id"], prompts[index], sampling[index], tracker
        )
        row = {"id": task["id"]}
        row.update(streamed)
        if not tracker.applicable:
            # Forced-choice / non-Word-Studio rows have no usable-option concept;
            # keep the fields null rather than pretending thresholds apply.
            row["firstCandidateLatencySeconds"] = None
            row["firstThreeCandidatesLatencySeconds"] = None
            row["firstTenCandidatesLatencySeconds"] = None
            row["progressiveOptionTiming"]["applicable"] = False
        return row

    if streaming == "sequential":
        rows = []
        for index, task in enumerate(tasks):
            rows.append(await run(index, task))
        return rows
    return list(await asyncio.gather(*[run(index, task) for index, task in enumerate(tasks)]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model", help="Hugging Face model repository ID")
    ap.add_argument("result_file", type=Path)
    ap.add_argument("--tasks", default=None)
    ap.add_argument("--revision", required=True, help="Immutable Hugging Face commit SHA")
    ap.add_argument("--benchmark-revision", required=True, help="Git commit containing the benchmark")
    ap.add_argument("--model-name", default=None)
    ap.add_argument("--checkpoint-type", choices=["base", "instruct", "chat", "specialized", "unknown"], default="instruct")
    ap.add_argument("--quantization", default="bf16", help="Explicit evaluated artifact quantization")
    ap.add_argument("--prompt-mode", choices=["chat", "plain"], required=True)
    ap.add_argument("--max-model-len", type=int, default=8192)
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.88)
    ap.add_argument("--tensor-parallel-size", type=int, default=1)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--max-tokens", type=int, default=220)
    ap.add_argument("--choice-max-tokens", type=int, default=8)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--top-p", type=float, default=1.0)
    ap.add_argument("--top-k", type=int, default=-1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--limit", type=int, default=None, help="Smoke-test cap; capped runs are marked incomplete")
    ap.add_argument("--trust-remote-code", action="store_true")
    ap.add_argument("--dtype", choices=["auto", "half", "bfloat16"], default="half")
    ap.add_argument("--language-model-only", action="store_true", help="Skip unused multimodal towers for supported models")
    ap.add_argument("--speculative-method", choices=["mtp", "qwen3_next_mtp"], default=None)
    ap.add_argument("--speculative-tokens", type=int, default=1)
    ap.add_argument("--resume", action="store_true", help="continue an exact-prefix atomic checkpoint under the same configuration")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument(
        "--streaming",
        choices=["off", "concurrent", "sequential"],
        default="off",
        help=(
            "progressive first-1/3/10 useful-option timing via the vLLM async engine; "
            "'off' keeps the canonical offline batch path and records the limitation explicitly"
        ),
    )
    args = ap.parse_args()

    if args.resume and args.overwrite:
        raise SystemExit("--resume and --overwrite are mutually exclusive")
    if args.streaming != "off" and args.resume:
        raise SystemExit("--streaming cannot resume an offline batch checkpoint; write a new result path")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", args.revision):
        raise SystemExit("--revision must be an immutable 40-character Hugging Face commit SHA")
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", args.benchmark_revision):
        raise SystemExit("--benchmark-revision must be a Git commit SHA")
    if args.batch_size < 1 or args.tensor_parallel_size < 1 or args.max_model_len < 512:
        raise SystemExit("batch size, tensor parallel size and max model length must be positive and reasonable")
    if not 0.1 <= args.gpu_memory_utilization <= 0.98:
        raise SystemExit("--gpu-memory-utilization must be in [0.1, 0.98]")
    if args.speculative_tokens < 1:
        raise SystemExit("--speculative-tokens must be >= 1")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be >= 1")

    result_path = args.result_file.resolve()
    if result_path.exists() and not (args.overwrite or args.resume):
        raise SystemExit(f"Refusing to overwrite existing result {result_path}; choose a new path, --resume, or --overwrite")
    if args.resume and not result_path.is_file():
        raise SystemExit(f"--resume requested but checkpoint does not exist: {result_path}")
    task_path = resolve_path(args.tasks)
    if not task_path.is_file():
        raise SystemExit(f"Missing task file: {task_path}. Build the requested task screen first.")
    task_bytes = task_path.read_bytes()
    task_hash = sha256_bytes(task_bytes)
    tasks = [json.loads(line) for line in task_bytes.decode("utf-8").splitlines() if line.strip()]
    if args.limit is not None:
        tasks = tasks[: args.limit]
    ids = [task.get("id") for task in tasks]
    if not tasks or any(not value for value in ids) or len(ids) != len(set(ids)):
        raise SystemExit("Tasks must be non-empty and have unique, non-empty IDs")
    if any(not isinstance(task.get("prompt"), str) or not task["prompt"] for task in tasks):
        raise SystemExit("Every task must have a non-empty prompt")

    try:
        import torch
        from transformers import AutoConfig, AutoTokenizer
        from vllm import LLM, SamplingParams
    except Exception as exc:
        raise SystemExit(f"Importing pinned inference dependencies failed: {type(exc).__name__}: {exc}") from exc
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is not available; this runner is CUDA-only and will not silently fall back to CPU")

    resolved_revision, artifact_hash, artifact_files = hash_hub_artifact_manifest(args.model, args.revision)
    tokenizer = AutoTokenizer.from_pretrained(
        args.model,
        revision=resolved_revision,
        trust_remote_code=args.trust_remote_code,
    )
    prompts: list[str] = []
    adaptations: set[str] = set()
    adaptation_details: set[str] = set()
    for task in tasks:
        prompt, adaptation, detail = prompt_for_task(tokenizer, task["prompt"], args.prompt_mode)
        prompts.append(prompt)
        adaptations.add(adaptation)
        adaptation_details.add(detail)

    # Issue #45: exact context-budget preflight. This runs before the model is
    # loaded, so an over-budget request can never be silently cropped by the
    # runtime and re-reported as English quality. An unprovable tokenizer or
    # template fails closed as context_unqualified.
    try:
        model_config = AutoConfig.from_pretrained(
            args.model,
            revision=resolved_revision,
            trust_remote_code=args.trust_remote_code,
        )
    except Exception as exc:
        raise SystemExit(
            "context_unqualified: could not load the pinned model config, so the "
            f"effective context limit cannot be proven: {type(exc).__name__}: {exc}"
        ) from exc
    try:
        effective_limit = resolve_effective_context_limit(
            model_context_limit_candidates(
                tokenizer,
                model_config,
                model=args.model,
                revision=resolved_revision,
                runtime_max_model_len=args.max_model_len,
            )
        )
    except ContextUnqualified as exc:
        raise SystemExit(f"context_unqualified: {exc.reason}: {exc.detail}") from exc

    counter = TransformersTokenizerCounter(
        tokenizer,
        args.prompt_mode,
        next(iter(sorted(adaptation_details)), "none"),
    )
    if args.prompt_mode == "plain":
        thinking_state = ThinkingCapability.not_applicable(
            "plain prompt mode sends no template and no thinking-disable flag"
        )
    elif "enable_thinking=false" in adaptation_details:
        # The runner passed enable_thinking=false AND the rendered prompt is the
        # exact string that will be encoded. For models whose template ignores
        # the kwarg the rendered prompt simply contains no opening think block,
        # which is observable; a template that keeps it would be visible in the
        # row's raw output and is still classified as unclosed_thinking_block.
        thinking_state = ThinkingCapability.applied(
            "enable_thinking=false",
            "enable_thinking=false accepted by tokenizer.apply_chat_template; prompt counted after the wrapper",
        )
    else:
        # The template does not accept the kwarg. Nothing proved a default; say so.
        thinking_state = ThinkingCapability(
            state="unverified",
            requested="enable_thinking=false",
            proof="template rejected the enable_thinking kwarg; no verified default is claimed",
        )

    context_receipt = ContextBudgetReceipt(
        tokenizer_identity={
            "nameOrPath": getattr(tokenizer, "name_or_path", args.model),
            "kind": "transformers.AutoTokenizer",
            "repoOrName": args.model,
            "revision": resolved_revision,
            "specialTokenHandling": "add_special_tokens=True (matches vLLM string-prompt encoding)",
        },
        prompt_identity=counter.id().as_dict(),
        effective_limit=effective_limit,
        thinking=thinking_state.as_dict(),
    )
    task_max_new_tokens: list[int] = []
    for task, prompt in zip(tasks, prompts, strict=True):
        requested = resolve_task_max_new_tokens(
            task,
            default_max_new_tokens=args.max_tokens,
            default_forced_choice_max_new_tokens=args.choice_max_tokens,
        )
        task_max_new_tokens.append(requested)
        row = build_task_budget_row(
            task_id=str(task["id"]),
            prompt_text=prompt,
            counter=counter,
            max_new_tokens=requested,
            effective_limit=effective_limit,
            thinking=thinking_state,
            reasoning_budget_required=args.prompt_mode == "chat",
        )
        context_receipt.tasks.append(row)
        if not row["fits"]:
            context_receipt.violations.append(str(task["id"]))
    try:
        context_budget = enforce_budget(context_receipt)
    except ContextUnqualified as exc:
        raise SystemExit(
            "context_unqualified: "
            f"{exc.reason}: refusing to generate with an over-budget request; "
            f"violating_task_ids={sorted(exc.detail.get('violatingTaskIds', []))}"
        ) from exc
    context_budget_path = result_path.with_suffix(f"{result_path.suffix}.context-budget.json")
    context_budget_path.write_text(
        json.dumps(context_budget, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    print(
        "context_budget_qualified "
        f"effective_limit={effective_limit['effectiveContextLimit']} "
        f"max_prompt_tokens={context_budget['summary']['maxPromptTokens']} "
        f"min_headroom={context_budget['summary']['minHeadroom']} "
        f"receipt={context_budget_path}",
        flush=True,
    )

    speculative_config = None
    if args.speculative_method:
        speculative_config = {
            "method": args.speculative_method,
            "num_speculative_tokens": args.speculative_tokens,
        }
    llm_kwargs: dict[str, Any] = {
        "model": args.model,
        "revision": resolved_revision,
        "tokenizer": args.model,
        "tokenizer_revision": resolved_revision,
        "trust_remote_code": args.trust_remote_code,
        "dtype": args.dtype,
        "tensor_parallel_size": args.tensor_parallel_size,
        "max_model_len": args.max_model_len,
        "gpu_memory_utilization": args.gpu_memory_utilization,
        "seed": args.seed,
        "disable_log_stats": False,
    }
    if args.language_model_only:
        llm_kwargs["language_model_only"] = True
    if speculative_config is not None:
        llm_kwargs["speculative_config"] = speculative_config

    expected_decoding = {
        "temperature": args.temperature,
        "topP": args.top_p,
        "topK": args.top_k,
        "maxNewTokens": args.max_tokens,
        "forcedChoiceMaxNewTokens": args.choice_max_tokens,
        "seed": args.seed,
        "batchSize": args.batch_size,
        "tensorParallelSize": args.tensor_parallel_size,
        "dtype": args.dtype,
        "languageModelOnly": args.language_model_only,
        "speculativeConfig": speculative_config,
    }

    print(f"task_file={task_path} task_count={len(tasks)} sha256={task_hash}", flush=True)
    print(f"loading model={args.model} revision={resolved_revision} tp={args.tensor_parallel_size} speculative={speculative_config}", flush=True)
    load_started = time.monotonic()
    streaming_kind = None
    streaming_reason = None
    if args.streaming != "off":
        import vllm as vllm_module

        streaming_kind, streaming_cls = streaming_backend(vllm_module)
        if streaming_cls is None:
            streaming_reason = (
                "installed vLLM build exposes neither AsyncLLM nor AsyncLLMEngine; "
                "true incremental output is unavailable"
            )
            print(f"progressive timing unavailable: {streaming_reason}", flush=True)
    llm = None
    stream_engine = None
    if streaming_kind is not None:
        engine_args = build_streaming_engine_args(
            vllm_module,
            model=args.model,
            revision=resolved_revision,
            engine_kwargs=llm_kwargs,
        )
        stream_engine = create_streaming_engine(vllm_module, streaming_kind, engine_args)
    else:
        llm = LLM(**llm_kwargs)
    cold_load_seconds = time.monotonic() - load_started
    progressive_supported = stream_engine is not None

    model_name = args.model_name or args.model.rsplit("/", 1)[-1]
    chat_template = getattr(tokenizer, "chat_template", None)
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if args.resume:
        run = json.loads(result_path.read_text(encoding="utf-8"))
        # Issue #60: schema identity must survive a resume. A checkpoint written
        # before the field existed gets the current version stamped on; a
        # checkpoint that declares a different version is a hard mismatch, not
        # something to silently rewrite.
        existing_schema = run.get("schemaVersion")
        if existing_schema is None:
            run["schemaVersion"] = RESULT_SCHEMA_VERSION
        elif existing_schema != RESULT_SCHEMA_VERSION:
            raise SystemExit(
                "Resume identity mismatch; checkpoint schemaVersion="
                f"{existing_schema!r} but this runner emits {RESULT_SCHEMA_VERSION}"
            )
        existing_repro_schema = (run.get("reproducibility") or {}).get("resultSchemaVersion")
        if existing_repro_schema is None:
            run.setdefault("reproducibility", {})["resultSchemaVersion"] = RESULT_SCHEMA_VERSION
        elif existing_repro_schema != RESULT_SCHEMA_VERSION:
            raise SystemExit(
                "Resume identity mismatch; checkpoint reproducibility.resultSchemaVersion="
                f"{existing_repro_schema!r} but this runner emits {RESULT_SCHEMA_VERSION}"
            )
        # The recorded schema hash must still describe the schema on disk.
        # Resuming across a schema change would produce one document claiming
        # two different schemas, so it is refused rather than reconciled.
        current_schema_sha = (
            sha256_bytes(RESULT_SCHEMA_PATH.read_bytes()) if RESULT_SCHEMA_PATH.is_file() else None
        )
        checkpoint_schema_sha = (run.get("reproducibility") or {}).get("resultSchemaSha256")
        if checkpoint_schema_sha is not None and checkpoint_schema_sha != current_schema_sha:
            raise SystemExit(
                "Resume identity mismatch; the result schema changed since this checkpoint was "
                f"written (checkpoint={checkpoint_schema_sha} current={current_schema_sha})"
            )
        run.setdefault("reproducibility", {})["resultSchemaSha256"] = current_schema_sha
        start_index = validate_resume(
            run,
            ids=ids,
            task_hash=task_hash,
            model_repo=args.model,
            revision=resolved_revision,
            prompt_mode=args.prompt_mode,
            expected_decoding=expected_decoding,
            benchmark_revision=args.benchmark_revision,
            expected_context_budget_sha256=context_budget["receiptSha256"],
        )
        if start_index == len(tasks):
            print(f"resume checkpoint already contains all {len(tasks)} requested tasks; no generation needed", flush=True)
            return
        runtime = run.setdefault("runtime", {})
        previous_streaming = runtime.get("streamingMode")
        if previous_streaming is not None and previous_streaming != args.streaming:
            raise SystemExit(
                "Resume identity mismatch; refusing to mix measurement modes: "
                f"streaming existing={previous_streaming!r} requested={args.streaming!r}"
            )
        runtime["streamingMode"] = args.streaming
        prior_wall = float(runtime.get("wallSecondsSoFar") or runtime.get("totalWallSeconds") or 0.0)
        runtime.setdefault("resumeSegments", []).append({
            "timestamp": created_at,
            "startIndex": start_index,
            "coldLoadSeconds": round(cold_load_seconds, 6),
            "previousWallSeconds": round(prior_wall, 6),
        })
        run["status"] = "running"
        run["complete"] = False
        run["completedCount"] = start_index
        run["reproducibility"]["rawOutputSha256"] = None
        atomic_write_json(result_path, run)
    else:
        start_index = 0
        prior_wall = 0.0
        run = {
            "runId": f"english-core-{model_name}-{uuid.uuid4().hex[:8]}",
            "schemaVersion": RESULT_SCHEMA_VERSION,
            "timestamp": created_at,
            "status": "running",
            "complete": False,
            "model": {
                "name": model_name,
                "repoOrName": args.model,
                "revision": resolved_revision,
                "artifactSha256": artifact_hash,
                "artifactIdentityType": "sha256_of_sorted_pinned_huggingface_blob_inventory",
                "artifactFiles": len(artifact_files),
                "quantization": args.quantization,
                "checkpointType": args.checkpoint_type,
                "runtime": "vllm",
                "runtimeVersion": package_version("vllm"),
                "tokenizerName": getattr(tokenizer, "name_or_path", args.model),
                "chatTemplate": "tokenizer.apply_chat_template" if "chat_template" in adaptations else "none/plain",
                "chatTemplateSha256": sha256_text(chat_template if isinstance(chat_template, str) else None),
            },
            "hardware": hardware_record(),
            "taskFile": str(task_path),
            "taskFileSha256": task_hash,
            "taskCount": len(tasks),
            "sourceTaskCount": len([line for line in task_bytes.decode("utf-8").splitlines() if line.strip()]),
            "promptModeRequested": args.prompt_mode,
            "promptAdaptationModesObserved": sorted(adaptations),
            "promptAdaptationDetailsObserved": sorted(adaptation_details),
            "decoding": expected_decoding,
            "contextBudget": {
                "receiptPath": str(context_budget_path),
                "receiptSha256": context_budget["receiptSha256"],
                "effectiveContextLimit": effective_limit["effectiveContextLimit"],
                "effectiveContextLimitSource": effective_limit["selectedFrom"],
                "thinkingCapability": thinking_state.as_dict(),
                "summary": context_budget["summary"],
            },
            "runtime": {
                "coldLoadSeconds": round(cold_load_seconds, 6),
                "cudaVisibleDevices": os.environ.get("CUDA_VISIBLE_DEVICES"),
                "resumeSegments": [],
                "streamingMode": args.streaming,
                "progressiveOptionTiming": {
                    "schemaVersion": PROGRESSIVE_SCHEMA_VERSION,
                    "thresholds": list(USABLE_OPTION_THRESHOLDS),
                    "fields": list(PROGRESSIVE_FIELD_BY_THRESHOLD.values()),
                    "supported": progressive_supported,
                    "streamingApi": streaming_kind,
                    "clock": "time.monotonic",
                    "limitation": None if progressive_supported else streaming_reason,
                    "notes": [
                        "First-1/3/10 usable-option latencies are crossed once each from incremental decoded text fed to the frozen Word Studio parser.",
                        "Cold model load is reported separately as coldLoadSeconds and is excluded from per-request latencies.",
                        "Unreached thresholds stay null; malformed or short output is never regenerated to obtain a timing value.",
                    ],
                },
            },
            "outputs": [],
            "reproducibility": {
                "benchmarkRevision": args.benchmark_revision,
                "resultSchemaVersion": RESULT_SCHEMA_VERSION,
                # Issue #60: hash of the exact schema bytes this run was written
                # against. Null only when the schema file is absent, which the
                # promotion validator already refuses; it never guesses one.
                "resultSchemaSha256": (
                    sha256_bytes(RESULT_SCHEMA_PATH.read_bytes())
                    if RESULT_SCHEMA_PATH.is_file()
                    else None
                ),
                "rawOutputSha256": None,
                "notes": [
                    "artifactSha256 hashes the canonical inventory of immutable Hub blobs and file sizes at the resolved commit; it is not a second bytewise hash of every downloaded weight tensor.",
                    "Run output contains no gold answers and this runner never opens answer-key files.",
                    "Raw model text is preserved exactly; leading <think> blocks are NOT stripped because protocol leakage is a benchmark observation.",
                    "Per-request TTFT and completion latency are taken from vLLM RequestOutput metrics when exposed by the installed version; unavailable values remain null.",
                    "For a smoke run with --limit, taskCount is the attempted prefix and complete remains false; it cannot be promoted as the fixed screen.",
                    "MTP is opt-in. An unsupported method/configuration fails explicitly; there is no silent fallback to ordinary decoding.",
                    "Resume is permitted only for the exact task-ID prefix under identical model, task hash, prompt mode, decoding, runtime topology, and benchmark revision.",
                    "Issue #45: prompt token counts come from the pinned tokenizer after every chat-template wrapper, the effective context limit is the minimum of every provable limit, and the budget receipt is hashed into run.contextBudget before any generation.",
                    "A task whose declared maxNewTokens is honored verbatim may still stop at the cap; that is recorded as output_budget_truncation rather than a shallow-candidate observation.",
                ],
            },
        }
        atomic_write_json(result_path, run)

    segment_started = time.monotonic()
    sampling_batches = list(run.get("runtime", {}).get("batchWallSeconds") or [])
    for start in range(start_index, len(tasks), args.batch_size):
        stop = min(start + args.batch_size, len(tasks))
        batch_tasks = tasks[start:stop]
        batch_prompts = prompts[start:stop]
        sampling = [
            SamplingParams(
                temperature=args.temperature,
                top_p=args.top_p,
                top_k=args.top_k,
                # Issue #45: the frozen task's own maxNewTokens is authoritative.
                # Using a single global default here would silently shrink a
                # protocol/product budget and then report the resulting short
                # output as model behaviour.
                max_tokens=task_max_new_tokens[start + offset],
                seed=args.seed,
            )
            for offset, task in enumerate(batch_tasks)
        ]
        batch_started = time.monotonic()
        if stream_engine is not None:
            streamed_rows = asyncio.run(
                _stream_batch(
                    stream_engine,
                    batch_tasks,
                    batch_prompts,
                    sampling,
                    "sequential" if args.streaming == "sequential" else "concurrent",
                )
            )
            batch_wall = time.monotonic() - batch_started
            for offset, (task, row) in enumerate(zip(batch_tasks, streamed_rows, strict=True)):
                row["promptAdaptation"] = "chat_template" if args.prompt_mode == "chat" else "plain"
                row["promptAdaptationDetail"] = next(iter(adaptation_details), "none")
                row["latencySource"] = "client_monotonic_stream"
                budget_row = context_receipt.tasks[start + offset]
                row["promptTokens"] = budget_row["promptTokens"]
                row["requestedMaxNewTokens"] = budget_row["requestedMaxNewTokens"]
                row["outputBudget"] = classify_output_cap_exhaustion(
                    finish_reason=row.get("finishReason"),
                    completion_tokens=row.get("completionTokenCount"),
                    expected_limit=budget_row["requestedMaxNewTokens"],
                )
                run["outputs"].append(row)
            sampling_batches.append(round(batch_wall, 6))
            run["completedCount"] = len(run["outputs"])
            segment_wall = time.monotonic() - segment_started
            run["runtime"]["wallSecondsSoFar"] = round(prior_wall + segment_wall, 6)
            run["runtime"]["lastBatchWallSeconds"] = round(batch_wall, 6)
            run["runtime"]["batchWallSeconds"] = sampling_batches
            atomic_write_json(result_path, run)
            print(
                f"completed {len(run['outputs'])}/{len(tasks)}; streamed batch={batch_wall:.2f}s; checkpoint={result_path}",
                flush=True,
            )
            continue

        request_outputs = llm.generate(batch_prompts, sampling_params=sampling, use_tqdm=False)
        batch_wall = time.monotonic() - batch_started
        if len(request_outputs) != len(batch_tasks):
            raise RuntimeError(f"vLLM returned {len(request_outputs)} outputs for {len(batch_tasks)} inputs")
        for offset, (task, request_output) in enumerate(zip(batch_tasks, request_outputs, strict=True)):
            choices = list(request_output.outputs)
            raw_generated = [str(choice.text) for choice in choices]
            metrics = getattr(request_output, "metrics", None)
            first_choice = choices[0] if choices else None
            finish_reason = getattr(first_choice, "finish_reason", None) if first_choice is not None else None
            output_text = raw_generated[0] if raw_generated else ""
            completion_token_count = len(first_choice.token_ids) if first_choice is not None else 0
            # Issue #45: vLLM never crops a prompt, so a mismatch between the
            # preflight count and the count the runtime actually encoded would
            # mean the budgeted string is not the consumed string.
            runtime_prompt_tokens = getattr(request_output, "prompt_token_ids", None)
            runtime_prompt_token_count = (
                len(runtime_prompt_tokens)
                if isinstance(runtime_prompt_tokens, list)
                else None
            )
            task_index = start + offset
            budget_row = (
                context_receipt.tasks[task_index] if 0 <= task_index < len(context_receipt.tasks) else None
            )
            truncation = detect_silent_truncation(
                prompt_tokens_preflight=budget_row["promptTokens"] if budget_row else -1,
                prompt_tokens_runtime=runtime_prompt_token_count,
            )
            if truncation["silentTruncationSuspected"]:
                raise RuntimeError(
                    "refusing to report a run whose runtime prompt token count differs from the "
                    f"preflight budget: {truncation}"
                )
            cap = classify_output_cap_exhaustion(
                finish_reason=finish_reason,
                completion_tokens=completion_token_count,
                expected_limit=resolve_task_max_new_tokens(
                    task,
                    default_max_new_tokens=args.max_tokens,
                    default_forced_choice_max_new_tokens=args.choice_max_tokens,
                ),
            )
            block = offline_progressive_block(
                streaming_reason
                or "offline llm.generate returns final RequestOutputs only; no incremental decode stream",
                applicable=is_word_studio_generative(task),
                text=output_text,
                source=word_studio_source(task),
                requested=word_studio_requested(task),
            )
            row = {
                "id": task["id"],
                "output": output_text,
                "latencySeconds": elapsed_metric(metrics, "arrival_time", "finished_time"),
                "firstTokenLatencySeconds": elapsed_metric(metrics, "arrival_time", "first_token_time"),
                "promptAdaptation": "chat_template" if args.prompt_mode == "chat" else "plain",
                "promptAdaptationDetail": next(iter(adaptation_details), "none"),
                "completionTokenCount": completion_token_count,
                "finishReason": finish_reason,
                "requestedMaxNewTokens": cap["expectedLimit"],
                "promptTokens": budget_row["promptTokens"] if budget_row else None,
                "silentTruncation": truncation,
                "outputBudget": cap,
                "latencySource": "vllm_request_metrics",
                **block,
            }
            if len(raw_generated) > 1:
                row["alternatives"] = raw_generated
            run["outputs"].append(row)
        sampling_batches.append(round(batch_wall, 6))
        run["completedCount"] = len(run["outputs"])
        segment_wall = time.monotonic() - segment_started
        run["runtime"]["wallSecondsSoFar"] = round(prior_wall + segment_wall, 6)
        run["runtime"]["lastBatchWallSeconds"] = round(batch_wall, 6)
        run["runtime"]["batchWallSeconds"] = sampling_batches
        atomic_write_json(result_path, run)
        print(f"completed {len(run['outputs'])}/{len(tasks)}; batch={batch_wall:.2f}s; checkpoint={result_path}", flush=True)

    # Issue #60: the raw-output hash must be reproducible by the strict
    # validator, which hashes with sorted_keys=True, ensure_ascii=False,
    # default separators and allow_nan=False. Match it exactly.
    outputs_canonical = json.dumps(
        run["outputs"], ensure_ascii=False, sort_keys=True, allow_nan=False
    ).encode("utf-8")
    run["status"] = "completed" if len(run["outputs"]) == len(tasks) and args.limit is None else "incomplete"
    run["complete"] = run["status"] == "completed"
    run["completedCount"] = len(run["outputs"])
    run["runtime"]["totalWallSeconds"] = round(prior_wall + (time.monotonic() - segment_started), 6)
    run["runtime"]["wallSecondsSoFar"] = run["runtime"]["totalWallSeconds"]
    run["runtime"]["progressiveOptionTimingSummary"] = summarize_progressive_option_timing(run["outputs"])
    run["reproducibility"]["rawOutputSha256"] = sha256_bytes(outputs_canonical)
    atomic_write_json(result_path, run)
    print(f"done status={run['status']} result={result_path} output_sha256={run['reproducibility']['rawOutputSha256']}", flush=True)
    if stream_engine is not None:
        asyncio.run(shutdown_streaming_engine(stream_engine))


if __name__ == "__main__":
    main()
