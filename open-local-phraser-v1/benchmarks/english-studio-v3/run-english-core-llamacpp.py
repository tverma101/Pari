#!/usr/bin/env python3
"""Run a frozen task JSONL against a local llama.cpp-compatible server.

Use for GGUF checkpoints such as Bonsai. The server must already be running
locally; this client sends no data outside the configured loopback endpoint.
It never opens answer keys or invokes a judge.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import platform
import re
import subprocess
import tempfile
import time
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import requests

from kaggle_context_budget import (
    ContextBudgetReceipt,
    ContextUnqualified,
    LimitCandidate,
    LlamaCppServerCounter,
    ThinkingCapability,
    build_task_budget_row,
    classify_output_cap_exhaustion,
    detect_silent_truncation,
    enforce_budget,
    resolve_effective_context_limit,
    resolve_task_max_new_tokens,
)
from kaggle_server_identity import served_model_identity

SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
# Issue #60: canonical result-document schema identity, identical to the vLLM
# runner's so both paths are promoted against one schema version.
RESULT_SCHEMA_VERSION = 1
RESULT_SCHEMA_PATH = Path(__file__).resolve().parent / "english-core-result-schema.json"


def load_progressive_contract() -> Any:
    """Load the canonical progressive timing contract from the core vLLM runner.

    Runner filenames are hyphenated CLI scripts and cannot be imported by name, so
    the core runner is loaded by path. It is the single source of truth for the
    shared first-1/3/10 usable-candidate schema; this runner adds no second parser
    or second definition of what a usable candidate is.
    """
    import importlib.util

    path = Path(__file__).resolve().parent / "run-english-core-vllm.py"
    spec = importlib.util.spec_from_file_location("pari_english_core_vllm_runner", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load the shared progressive timing contract from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROGRESSIVE = load_progressive_contract()
ProgressiveOptionTracker = PROGRESSIVE.ProgressiveOptionTracker


def verify_server_identity(
    endpoint: str,
    args: argparse.Namespace,
    *,
    nonce: str | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Prove the answering loopback server serves the intended model before traffic.

    `/health` alone is never enough. OpenAI-compatible llama.cpp/Prism servers
    expose `/v1/models`, so the served-model name is checked and the raw response
    is preserved. Runtimes that cannot answer are recorded as unproven rather than
    treated as qualified; run `--allow-unproven-served-model` to accept that
    explicitly, in which case the receipt says so.
    """
    expected = args.model_repo
    identity = served_model_identity(endpoint, expected, headers=headers)
    evidence: dict[str, Any] = {
        "schemaVersion": 1,
        "endpoint": endpoint.rstrip("/"),
        "runNonce": nonce,
        "expectedModel": expected,
        "checkedAt": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "servedModelIdentity": identity,
        "identityProofRequired": not getattr(args, "allow_unproven_served_model", False),
    }
    matched = identity.get("identityMatched")
    if matched is True:
        evidence["status"] = "proven"
    elif not evidence["identityProofRequired"]:
        evidence["status"] = "unproven_allowed"
        evidence["reason"] = (
            f"served-model identity not proven for {expected!r}; "
            f"served={identity.get('servedModelIds')}; run marked identity-unproven"
        )
    else:
        evidence["status"] = identity.get("identityStatus") or "identity_unavailable"
        evidence["reason"] = (
            f"served-model identity not proven: expected={expected!r} "
            f"served={identity.get('servedModelIds')}"
        )
    return evidence


def identity_guard_ok(evidence: dict[str, Any]) -> bool:
    """A response may enter the result only if the server identity was proven."""
    return evidence.get("status") == "proven"


def _post_json(endpoint: str, route: str, payload: dict[str, Any], timeout: float = 60.0) -> Any:
    response = requests.post(endpoint.rstrip("/") + route, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def server_tokenize(endpoint: str, content: str) -> list[Any]:
    """Exact tokenization through the running server's own `/tokenize`.

    `add_special=True, parse_special=True` mirrors the llama.cpp inference path
    (`tokenize_input_prompts(vocab, mctx, prompt, true, true, ...)`), so this is
    the runtime's own count rather than a re-implementation or an estimate.
    """
    body = _post_json(
        endpoint,
        "/tokenize",
        {"content": content, "add_special": True, "parse_special": True, "with_pieces": False},
    )
    tokens = body.get("tokens") if isinstance(body, dict) else None
    if not isinstance(tokens, list):
        raise ContextUnqualified(
            "server_tokenize_unavailable",
            detail={"route": "/tokenize", "response_type": type(body).__name__},
        )
    return tokens


def server_apply_template(endpoint: str, content: str, args: argparse.Namespace) -> str:
    """Render the chat prompt through the server's `/apply-template`.

    `/apply-template` and `/v1/chat/completions` both route through
    `oaicompat_chat_params_parse`, so this returns the same prompt string the
    runtime will encode. The same reasoning/thinking-disable fields are sent so
    the rendered prompt matches the benchmark request exactly.
    """
    body = _post_json(
        endpoint,
        "/apply-template",
        {
            "model": args.model_repo,
            "messages": [{"role": "user", "content": content}],
            "reasoning_effort": "none",
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )
    prompt = body.get("prompt") if isinstance(body, dict) else None
    if not isinstance(prompt, str) or not prompt:
        raise ContextUnqualified(
            "server_apply_template_unavailable",
            detail={"route": "/apply-template", "prompt_type": type(prompt).__name__},
        )
    return prompt


def server_context_limit_candidates(
    endpoint: str,
    server_props: dict[str, Any],
    *,
    runtime_ctx_size: int | None,
) -> list[LimitCandidate]:
    """Collect every provable context limit advertised by the live server."""
    candidates: list[LimitCandidate] = []
    if isinstance(runtime_ctx_size, int) and runtime_ctx_size > 0:
        candidates.append(
            LimitCandidate(
                tokens=runtime_ctx_size,
                source="runtime_override",
                provenance=f"configured --ctx-size {runtime_ctx_size}",
            )
        )
    default_settings = server_props.get("default_generation_settings")
    if isinstance(default_settings, dict):
        n_ctx = default_settings.get("n_ctx")
        if isinstance(n_ctx, int) and n_ctx > 0:
            candidates.append(
                LimitCandidate(
                    tokens=n_ctx,
                    source="server_api",
                    provenance="GET /props default_generation_settings.n_ctx (effective per-slot context)",
                )
            )
    total_slots = server_props.get("total_slots")
    if isinstance(default_settings, dict):
        n_ctx = default_settings.get("n_ctx")
        if isinstance(n_ctx, int) and n_ctx > 0 and isinstance(total_slots, int) and total_slots > 1:
            # With --parallel>1 the context is split across slots, so a slot can
            # hold fewer tokens than the reported total. Over-reporting headroom
            # here is exactly the optimistic-number bug issue #45 forbids.
            candidates.append(
                LimitCandidate(
                    tokens=n_ctx // total_slots,
                    source="server_api",
                    provenance=(
                        f"n_ctx {n_ctx} divided across total_slots {total_slots} "
                        "(per-slot context for a concurrent request)"
                    ),
                )
            )
    return candidates


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            # Issue #60: allow_nan=False keeps NaN/Infinity out of the result
            # document; Python would otherwise emit bare `NaN`, which is not
            # JSON and which the strict promotion loader rejects.
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


def generate_one(
    endpoint: str,
    prompt: str,
    max_tokens: int,
    args: argparse.Namespace,
    track_word_studio: bool = False,
    source: str | None = None,
    requested: int = 10,
) -> dict[str, Any]:
    started = time.monotonic()
    tracker = ProgressiveOptionTracker(source=source, requested=requested, applicable=track_word_studio)
    if args.prompt_mode == "chat":
        route = "/v1/chat/completions"
        payload = {
            "model": args.model_repo,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": args.temperature,
            "top_p": args.top_p,
            "top_k": args.top_k,
            "seed": args.seed,
            "stream": True,
            "stream_options": {"include_usage": True},
            "reasoning_effort": "none",
            "chat_template_kwargs": {"enable_thinking": False},
        }
    else:
        route = "/completion"
        payload = {
            "prompt": prompt,
            "n_predict": max_tokens,
            "temperature": args.temperature,
            "top_p": args.top_p,
            "top_k": args.top_k,
            "seed": args.seed,
            "stream": True,
            "cache_prompt": False,
        }
    response = requests.post(
        endpoint.rstrip("/") + route,
        json=payload,
        stream=True,
        timeout=(30, args.request_timeout),
    )
    response.raise_for_status()
    first_token_seconds = None
    chunks: list[str] = []
    token_count = 0
    final_metrics: dict[str, Any] = {}
    for raw_line in response.iter_lines(decode_unicode=True):
        if not raw_line:
            continue
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        if not line.startswith("data:"):
            continue
        payload_text = line[len("data:") :].strip()
        if payload_text == "[DONE]":
            break
        try:
            piece = json.loads(payload_text)
        except json.JSONDecodeError:
            continue
        choices = piece.get("choices") or []
        choice0 = choices[0] if choices else {}
        delta = choice0.get("delta", {}) if choices else {}
        content = delta.get("content") or piece.get("content") or piece.get("response") or ""
        finish_reason = choice0.get("finish_reason") if isinstance(choice0, dict) else None
        if finish_reason:
            final_metrics["finish_reason"] = finish_reason
        if content:
            now = time.monotonic()
            if first_token_seconds is None:
                first_token_seconds = now - started
            chunks.append(content)
            tracker.observe(content, "".join(chunks))
        tokens = piece.get("tokens")
        if isinstance(tokens, list):
            token_count += len(tokens)
        for key in (
            "timings", "tokens_predicted", "tokens_evaluated", "stop", "usage",
            "stopped_limit", "stopped_eos", "stop_type", "truncated",
        ):
            if key in piece:
                final_metrics[key] = piece[key]
    response.close()
    finished = time.monotonic()
    if first_token_seconds is None:
        first_token_seconds = finished - started
    if token_count == 0:
        token_count = int(final_metrics.get("tokens_predicted") or 0)
    finish_reason = final_metrics.get("finish_reason")
    if not finish_reason and final_metrics.get("stopped_limit"):
        finish_reason = "length"
    elif not finish_reason and final_metrics.get("stop"):
        finish_reason = "stop"
    text = "".join(chunks).strip()
    row = {
        "text": text,
        "latencySeconds": round(finished - started, 6),
        "firstTokenLatencySeconds": round(first_token_seconds, 6),
        "completionTokenCount": token_count,
        "finishReason": finish_reason,
        "serverMetrics": final_metrics,
        # Issue #45 inputs: llama.cpp reports tokens_evaluated (prompt tokens the
        # server actually encoded) and a `truncated` flag when the context window
        # was exceeded. Both are compared against preflight below.
        "promptTokensEvaluated": final_metrics.get("tokens_evaluated"),
        "serverTruncated": final_metrics.get("truncated"),
        "streamChunkCount": len(chunks),
        "streamDeltaSha256": sha256_bytes("".join(chunks).encode("utf-8")),
    }
    if track_word_studio:
        tracker.finish(text)
        row.update(tracker.result(text))
    else:
        row.update({
            "firstCandidateLatencySeconds": None,
            "firstThreeCandidatesLatencySeconds": None,
            "firstTenCandidatesLatencySeconds": None,
            "progressiveOptionTiming": {
                "schemaVersion": PROGRESSIVE.PROGRESSIVE_SCHEMA_VERSION,
                "applicable": False,
                "thresholds": list(PROGRESSIVE.USABLE_OPTION_THRESHOLDS),
                "crossings": [],
                "unmetThresholds": list(PROGRESSIVE.USABLE_OPTION_THRESHOLDS),
            },
            "diagnostics": None,
        })
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model_repo")
    ap.add_argument("model_path", type=Path, help="Exact downloaded GGUF file")
    ap.add_argument("result_file", type=Path)
    ap.add_argument("--tasks", type=Path, required=True)
    ap.add_argument("--revision", required=True, help="Immutable 40-character HF commit SHA")
    ap.add_argument("--benchmark-revision", required=True, help="Git commit containing benchmark")
    ap.add_argument("--model-name", default=None)
    ap.add_argument("--runtime-build", required=True, help="Pinned llama.cpp commit plus CUDA build flags")
    ap.add_argument("--quantization", default="Q1_0")
    ap.add_argument("--checkpoint-type", choices=["base", "instruct", "chat", "specialized", "unknown"], default="instruct")
    ap.add_argument("--prompt-mode", choices=["chat", "plain"], required=True)
    ap.add_argument("--endpoint", default="http://127.0.0.1:8080")
    ap.add_argument(
        "--ctx-size",
        type=int,
        default=None,
        help=(
            "context size the server was started with (llama.cpp --ctx-size). "
            "Recorded as a context-limit source for issue #45; omit when unknown."
        ),
    )
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--top-p", type=float, default=1.0)
    ap.add_argument("--top-k", type=int, default=0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-tokens", type=int, default=220)
    ap.add_argument("--choice-max-tokens", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--request-timeout", type=float, default=180.0)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument(
        "--allow-unproven-served-model",
        action="store_true",
        help=(
            "continue when the server cannot prove the served model identity; the run is "
            "recorded as identity-unproven instead of silently treated as qualified"
        ),
    )
    ap.add_argument(
        "--run-nonce",
        default=None,
        help="benchmark run nonce recorded with the server identity proof",
    )
    args = ap.parse_args()

    if not re.fullmatch(r"[0-9a-fA-F]{40}", args.revision):
        raise SystemExit("--revision must be a 40-character immutable Hugging Face commit SHA")
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", args.benchmark_revision):
        raise SystemExit("--benchmark-revision must be a Git commit SHA")
    if args.batch_size < 1 or args.max_tokens < 1 or args.choice_max_tokens < 1:
        raise SystemExit("batch size and token limits must be positive")
    if not args.model_path.is_file():
        raise SystemExit(f"Missing GGUF file: {args.model_path}")
    endpoint_host = requests.utils.urlparse(args.endpoint).hostname
    if endpoint_host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("Only a loopback llama.cpp endpoint is allowed; prompts must not be sent to a remote API")
    result_path = args.result_file.resolve()
    if result_path.exists() and not args.overwrite:
        raise SystemExit(f"Refusing to overwrite existing result {result_path}")

    task_bytes = args.tasks.read_bytes()
    all_tasks = [json.loads(line) for line in task_bytes.decode("utf-8").splitlines() if line.strip()]
    tasks = all_tasks[: args.limit] if args.limit is not None else all_tasks
    ids = [task.get("id") for task in tasks]
    if not tasks or any(not task_id for task_id in ids) or len(ids) != len(set(ids)):
        raise SystemExit("Tasks must be non-empty and have unique, non-empty IDs")
    if any(not isinstance(task.get("prompt"), str) or not task["prompt"] for task in tasks):
        raise SystemExit("Every task must have a non-empty prompt")

    run_nonce = args.run_nonce or uuid.uuid4().hex
    health = requests.get(args.endpoint.rstrip("/") + "/health", timeout=10)
    health.raise_for_status()
    # Issue #42: `/health` is necessary but not sufficient. Prove the answering
    # server serves the intended model before any benchmark traffic, and keep the
    # raw `/v1/models` response in the run receipt.
    identity_evidence = verify_server_identity(args.endpoint, args, nonce=run_nonce)
    if not identity_guard_ok(identity_evidence):
        if identity_evidence.get("identityProofRequired"):
            raise SystemExit(
                "refusing benchmark traffic from an unproven server: "
                f"{identity_evidence.get('reason')}"
            )
        print(f"WARNING server identity unproven: {identity_evidence.get('reason')}", flush=True)
    prompts = [task["prompt"] for task in tasks]

    model_path = args.model_path.resolve()
    artifact_hash = sha256_file(model_path)
    server_version = None
    server_props: dict[str, Any] = {}
    try:
        props = requests.get(args.endpoint.rstrip("/") + "/props", timeout=10).json()
        if isinstance(props, dict):
            server_props = props
            server_version = server_props.get("build_info") or server_props.get("version")
    except Exception:
        pass
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    embedded_template = server_props.get("chat_template") or server_props.get("default_chat_template")

    # Issue #45: exact context-budget preflight against the *running* server,
    # before a single generation request. The server's own /tokenize is the only
    # acceptable counter for a GGUF vocabulary; estimating from characters or
    # borrowing the HF tokenizer would be a different tokenizer than the one
    # that will actually run.
    try:
        effective_limit = resolve_effective_context_limit(
            server_context_limit_candidates(
                args.endpoint,
                server_props,
                runtime_ctx_size=args.ctx_size,
            )
        )
        counter = LlamaCppServerCounter(
            tokenize=lambda text: server_tokenize(args.endpoint, text),
            apply_template=lambda text: server_apply_template(args.endpoint, text, args),
            mode=args.prompt_mode,
            detail=(
                "server /apply-template + /tokenize(add_special=true, parse_special=true)"
                if args.prompt_mode == "chat"
                else "none"
            ),
        )
        # Hash the server's own template string so the receipt identifies the
        # template that produced the counted prompts, not just the mode name.
        if args.prompt_mode == "chat" and isinstance(embedded_template, str):
            counter.identity = replace(
                counter.identity,
                template_sha256=hashlib.sha256(embedded_template.encode("utf-8")).hexdigest(),
            )
        if args.prompt_mode == "plain":
            thinking_state = ThinkingCapability.not_applicable(
                "plain /completion prompt sends no template and no thinking-disable flag"
            )
        else:
            # `/apply-template` ran with reasoning_effort=none and
            # chat_template_kwargs.enable_thinking=false. If the server had
            # rejected those, it would have errored; a server that ignores them
            # still yields the rendered prompt we counted, so the state is
            # "applied to the counted prompt" and never "verified default".
            thinking_state = ThinkingCapability.applied(
                "reasoning_effort=none;enable_thinking=false",
                "server /apply-template accepted the request; the counted prompt is the server-rendered template output",
            )
        context_receipt = ContextBudgetReceipt(
            tokenizer_identity={
                "nameOrPath": f"{args.model_repo} (server-side GGUF vocabulary)",
                "kind": "llama.cpp-server /tokenize",
                "repoOrName": args.model_repo,
                "revision": args.revision,
                "specialTokenHandling": "add_special=true;parse_special=true (matches server inference tokenization)",
            },
            prompt_identity=counter.id().as_dict(),
            effective_limit=effective_limit,
            thinking=thinking_state.as_dict(),
        )
        task_max_new_tokens: list[int] = []
        for task in tasks:
            requested = resolve_task_max_new_tokens(
                task,
                default_max_new_tokens=args.max_tokens,
                default_forced_choice_max_new_tokens=args.choice_max_tokens,
            )
            task_max_new_tokens.append(requested)
            budget_prompt = (
                counter.render_chat(task["prompt"]) if args.prompt_mode == "chat" else task["prompt"]
            )
            row = build_task_budget_row(
                task_id=str(task["id"]),
                prompt_text=budget_prompt,
                counter=counter,
                max_new_tokens=requested,
                effective_limit=effective_limit,
                thinking=thinking_state,
                reasoning_budget_required=args.prompt_mode == "chat",
            )
            context_receipt.tasks.append(row)
            if not row["fits"]:
                context_receipt.violations.append(str(task["id"]))
        context_budget = enforce_budget(context_receipt)
    except ContextUnqualified as exc:
        raise SystemExit(
            f"context_unqualified: {exc.reason}: {exc.detail}; refusing to generate "
            "with an unproven or over-budget request"
        ) from exc
    except requests.RequestException as exc:
        raise SystemExit(
            f"context_unqualified: context_budget_probe_failed: {type(exc).__name__}: {exc}"
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

    run: dict[str, Any] = {
        "runId": f"english-core-{args.model_name or model_path.stem}-{uuid.uuid4().hex[:8]}",
        "schemaVersion": RESULT_SCHEMA_VERSION,
        "runNonce": run_nonce,
        "timestamp": created_at,
        "status": "running",
        "complete": False,
        "model": {
            "name": args.model_name or model_path.stem,
            "repoOrName": args.model_repo,
            "revision": args.revision,
            "artifactSha256": artifact_hash,
            "artifactIdentityType": "sha256_of_exact_downloaded_gguf_file",
            "quantization": args.quantization,
            "checkpointType": args.checkpoint_type,
            "runtime": "llama.cpp-server",
            "runtimeVersion": f"{server_version or 'unknown'}; {args.runtime_build}",
            "tokenizerName": f"{args.model_repo} (embedded GGUF vocabulary)",
            "chatTemplate": "llama.cpp GGUF-embedded chat template" if args.prompt_mode == "chat" else "none/plain",
            "chatTemplateSha256": hashlib.sha256(str(embedded_template).encode()).hexdigest()
            if embedded_template
            else None,
        },
        "hardware": {
            "machine": platform.machine(),
            "os": platform.platform(),
            "python": platform.python_version(),
            "nvidiaSmi": subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip().splitlines(),
        },
        "taskFile": str(args.tasks.resolve()),
        "taskFileSha256": sha256_bytes(task_bytes),
        "taskCount": len(tasks),
        "sourceTaskCount": len(all_tasks),
        "promptModeRequested": args.prompt_mode,
        "promptAdaptationModesObserved": ["llama.cpp_embedded_chat_template" if args.prompt_mode == "chat" else "plain"],
        "promptAdaptationDetailsObserved": ["reasoning_effort=none;enable_thinking=false" if args.prompt_mode == "chat" else "none"],
        "decoding": {
            "temperature": args.temperature,
            "topP": args.top_p,
            "topK": args.top_k,
            "maxNewTokens": args.max_tokens,
            "forcedChoiceMaxNewTokens": args.choice_max_tokens,
            "seed": args.seed,
            "batchSize": args.batch_size,
            "serverEndpoint": args.endpoint,
        },
        "runtime": {
            "llamaCppProps": server_version,
            "serverIdentity": identity_evidence,
            "serverIdentityProven": identity_guard_ok(identity_evidence),
        },
        "contextBudget": {
            "receiptPath": str(context_budget_path),
            "receiptSha256": context_budget["receiptSha256"],
            "effectiveContextLimit": effective_limit["effectiveContextLimit"],
            "effectiveContextLimitSource": effective_limit["selectedFrom"],
            "thinkingCapability": thinking_state.as_dict(),
            "summary": context_budget["summary"],
        },
        "outputs": [],
        "reproducibility": {
            "benchmarkRevision": args.benchmark_revision,
            "resultSchemaVersion": RESULT_SCHEMA_VERSION,
            # Issue #60: hash of the exact schema bytes this run was written
            # against; null only when the schema file is absent, which the
            # promotion validator already refuses.
            "resultSchemaSha256": (
                sha256_bytes(RESULT_SCHEMA_PATH.read_bytes()) if RESULT_SCHEMA_PATH.is_file() else None
            ),
            "rawOutputSha256": None,
            "notes": [
                "Exact GGUF file bytes are SHA-256 hashed locally.",
                "The server must be built from a pinned llama.cpp commit; include the build commit and CUDA build flags when packaging this run.",
                "Chat mode uses the GGUF-embedded template through the loopback OpenAI-compatible API; reasoning/thinking disable requests are recorded in the decoding contract.",
                "Issue #45: prompt tokens come from the server's own /tokenize(add_special=true, parse_special=true) after /apply-template renders the same chat request, the effective context limit is the minimum of /props n_ctx (divided across slots when --parallel>1) and the configured --ctx-size, and the budget receipt is hashed into run.contextBudget.",
                "A prompt whose server-side token count disagrees with preflight, or a server-reported truncated=true, fails the run instead of being reported as candidate quality.",
                "Per-request first-token and completion times are measured by the loopback streaming client.",
                "For Word Studio suites, time-to-first/3/10 parsed candidates is measured incrementally from completed candidate strings, not equated with TTFT.",
                "A capped --limit run is marked incomplete and is not promotion-quality evidence.",
                "No answer key is loaded and no model-as-judge is invoked.",
            ],
        },
    }
    atomic_write_json(result_path, run)

    total_started = time.monotonic()
    for start in range(0, len(tasks), args.batch_size):
        stop = min(start + args.batch_size, len(tasks))
        batch = tasks[start:stop]
        batch_started = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.batch_size) as executor:
            futures = [
                executor.submit(
                    generate_one,
                    args.endpoint,
                    prompts[index],
                    # Issue #45: the frozen task's declared budget is honored
                    # verbatim rather than replaced by a global default.
                    task_max_new_tokens[index],
                    args,
                    str(task.get("suite") or "").startswith("word_studio_"),
                    task.get("selectedText") or task.get("sourceText") or None,
                    int(task.get("requestedCount") or 10),
                )
                for index, task in enumerate(batch, start)
            ]
            generated = [future.result() for future in futures]
        batch_seconds = time.monotonic() - batch_started
        for offset, (task, output) in enumerate(zip(batch, generated, strict=True)):
            budget_row = context_receipt.tasks[start + offset]
            truncation = detect_silent_truncation(
                prompt_tokens_preflight=budget_row["promptTokens"],
                prompt_tokens_runtime=output.get("promptTokensEvaluated"),
                server_reported_truncated=output.get("serverTruncated"),
            )
            if truncation["silentTruncationSuspected"]:
                raise RuntimeError(
                    "refusing to report a run whose server truncated the prompt or "
                    f"evaluated a different token count than preflight: {truncation}"
                )
            cap = classify_output_cap_exhaustion(
                finish_reason=output.get("finishReason"),
                completion_tokens=output.get("completionTokenCount"),
                expected_limit=budget_row["requestedMaxNewTokens"],
            )
            row = {
                "id": task["id"],
                "output": output["text"],
                "latencySeconds": output["latencySeconds"],
                "firstTokenLatencySeconds": output["firstTokenLatencySeconds"],
                "completionTokenCount": output["completionTokenCount"],
                "finishReason": output["finishReason"],
                "requestedMaxNewTokens": budget_row["requestedMaxNewTokens"],
                "promptTokens": budget_row["promptTokens"],
                "silentTruncation": truncation,
                "outputBudget": cap,
                "promptAdaptation": "llama.cpp_embedded_chat_template" if args.prompt_mode == "chat" else "plain",
                "promptAdaptationDetail": "reasoning_effort=none;enable_thinking=false" if args.prompt_mode == "chat" else "none",
                "firstCandidateLatencySeconds": output["firstCandidateLatencySeconds"],
                "firstThreeCandidatesLatencySeconds": output["firstThreeCandidatesLatencySeconds"],
                "firstTenCandidatesLatencySeconds": output["firstTenCandidatesLatencySeconds"],
                "progressiveOptionTiming": output["progressiveOptionTiming"],
                "diagnostics": output["diagnostics"],
                "streamChunkCount": output["streamChunkCount"],
                "streamDeltaSha256": output["streamDeltaSha256"],
                "latencySource": "client_monotonic_stream",
            }
            run["outputs"].append(row)
        run["completedCount"] = len(run["outputs"])
        run["runtime"]["lastBatchWallSeconds"] = round(batch_seconds, 6)
        run["runtime"]["wallSecondsSoFar"] = round(time.monotonic() - total_started, 6)
        atomic_write_json(result_path, run)
        print(f"completed {len(run['outputs'])}/{len(tasks)}; batch={batch_seconds:.2f}s", flush=True)

    # Issue #60: the raw-output hash must be reproducible by the strict
    # validator, which hashes with sorted_keys=True, ensure_ascii=False,
    # default separators and allow_nan=False. Match it exactly.
    canonical = json.dumps(
        run["outputs"], ensure_ascii=False, sort_keys=True, allow_nan=False
    ).encode("utf-8")
    run["status"] = "completed" if len(run["outputs"]) == len(tasks) and args.limit is None else "incomplete"
    run["complete"] = run["status"] == "completed"
    run["completedCount"] = len(run["outputs"])
    run["runtime"]["totalWallSeconds"] = round(time.monotonic() - total_started, 6)
    run["runtime"]["progressiveOptionTimingSummary"] = PROGRESSIVE.summarize_progressive_option_timing(run["outputs"])
    run["reproducibility"]["rawOutputSha256"] = sha256_bytes(canonical)
    atomic_write_json(result_path, run)
    print(f"done status={run['status']} result={result_path}", flush=True)


if __name__ == "__main__":
    main()
