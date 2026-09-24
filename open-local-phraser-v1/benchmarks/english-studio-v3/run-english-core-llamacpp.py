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
from pathlib import Path
from typing import Any

import requests

SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


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
            json.dump(value, stream, ensure_ascii=False, indent=2)
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


def generate_one(endpoint: str, prompt: str, max_tokens: int, args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
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
        payload = line[len("data:") :].strip()
        if payload == "[DONE]":
            break
        try:
            piece = json.loads(payload)
        except json.JSONDecodeError:
            continue
        choices = piece.get("choices") or []
        delta = choices[0].get("delta", {}) if choices else {}
        content = delta.get("content") or piece.get("content") or piece.get("response") or ""
        if content:
            if first_token_seconds is None:
                first_token_seconds = time.monotonic() - started
            chunks.append(content)
        tokens = piece.get("tokens")
        if isinstance(tokens, list):
            token_count += len(tokens)
        for key in ("timings", "tokens_predicted", "tokens_evaluated", "stop", "usage"):
            if key in piece:
                final_metrics[key] = piece[key]
    response.close()
    finished = time.monotonic()
    if first_token_seconds is None:
        first_token_seconds = finished - started
    if token_count == 0:
        token_count = int(final_metrics.get("tokens_predicted") or 0)
    return {
        "text": "".join(chunks).strip(),
        "latencySeconds": round(finished - started, 6),
        "firstTokenLatencySeconds": round(first_token_seconds, 6),
        "completionTokenCount": token_count,
        "serverMetrics": final_metrics,
    }


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

    health = requests.get(args.endpoint.rstrip("/") + "/health", timeout=10)
    health.raise_for_status()
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
    run: dict[str, Any] = {
        "runId": f"english-core-{args.model_name or model_path.stem}-{uuid.uuid4().hex[:8]}",
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
        "runtime": {"llamaCppProps": server_version},
        "outputs": [],
        "reproducibility": {
            "benchmarkRevision": args.benchmark_revision,
            "rawOutputSha256": None,
            "notes": [
                "Exact GGUF file bytes are SHA-256 hashed locally.",
                "The server must be built from a pinned llama.cpp commit; include the build commit and CUDA build flags when packaging this run.",
                "Chat mode uses the GGUF-embedded template through the loopback OpenAI-compatible API; reasoning/thinking disable requests are recorded in the decoding contract.",
                "Per-request first-token and completion times are measured by the loopback streaming client; first token is not a human-approved option.",
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
                    args.max_tokens if task.get("generative") else args.choice_max_tokens,
                    args,
                )
                for index, task in enumerate(batch, start)
            ]
            generated = [future.result() for future in futures]
        batch_seconds = time.monotonic() - batch_started
        for task, output in zip(batch, generated, strict=True):
            run["outputs"].append({
                "id": task["id"],
                "output": output["text"],
                "latencySeconds": output["latencySeconds"],
                "firstTokenLatencySeconds": output["firstTokenLatencySeconds"],
                "completionTokenCount": output["completionTokenCount"],
                "promptAdaptation": "llama.cpp_embedded_chat_template" if args.prompt_mode == "chat" else "plain",
                "promptAdaptationDetail": "reasoning_effort=none;enable_thinking=false" if args.prompt_mode == "chat" else "none",
            })
        run["completedCount"] = len(run["outputs"])
        run["runtime"]["lastBatchWallSeconds"] = round(batch_seconds, 6)
        run["runtime"]["wallSecondsSoFar"] = round(time.monotonic() - total_started, 6)
        atomic_write_json(result_path, run)
        print(f"completed {len(run['outputs'])}/{len(tasks)}; batch={batch_seconds:.2f}s", flush=True)

    canonical = json.dumps(run["outputs"], ensure_ascii=False, sort_keys=True).encode("utf-8")
    run["status"] = "completed" if len(run["outputs"]) == len(tasks) and args.limit is None else "incomplete"
    run["complete"] = run["status"] == "completed"
    run["completedCount"] = len(run["outputs"])
    run["runtime"]["totalWallSeconds"] = round(time.monotonic() - total_started, 6)
    run["reproducibility"]["rawOutputSha256"] = sha256_bytes(canonical)
    atomic_write_json(result_path, run)
    print(f"done status={run['status']} result={result_path}", flush=True)


if __name__ == "__main__":
    main()
