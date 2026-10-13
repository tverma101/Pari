#!/usr/bin/env python3
"""Measure usable Word Studio candidate latency from a loopback OpenAI server.

This client is intentionally runtime-agnostic. It sends only to loopback, streams
raw model text, and records when 1/3/10 complete candidate strings first become
parseable. It does not judge candidate quality and never retries poor output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import requests

from word_studio_output_parser import diagnose, partial_candidate_count


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://127.0.0.1:8000")
    ap.add_argument("--model", required=True)
    ap.add_argument("--tasks", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--top-p", type=float, default=1.0)
    ap.add_argument("--max-tokens", type=int, default=900)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--request-timeout", type=float, default=180.0)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    host = requests.utils.urlparse(args.endpoint).hostname
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("endpoint must be loopback; benchmark prompts may not be sent to a remote API")
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite {args.output}")
    task_bytes = args.tasks.read_bytes()
    tasks = [json.loads(x) for x in task_bytes.decode("utf-8").splitlines() if x.strip()]
    if args.limit is not None:
        tasks = tasks[: args.limit]
    if not tasks:
        raise SystemExit("task file is empty")
    ids = [row.get("id") for row in tasks]
    if any(not x for x in ids) or len(ids) != len(set(ids)):
        raise SystemExit("tasks require unique non-empty IDs")

    health = requests.get(args.endpoint.rstrip("/") + "/health", timeout=10)
    health.raise_for_status()

    result: dict[str, Any] = {
        "version": 1,
        "purpose": "Word Studio streaming usable-candidate latency; no quality scoring",
        "endpoint": args.endpoint,
        "model": args.model,
        "taskFile": str(args.tasks.resolve()),
        "taskFileSha256": sha256_bytes(task_bytes),
        "taskCount": len(tasks),
        "decoding": {
            "temperature": args.temperature,
            "topP": args.top_p,
            "maxTokens": args.max_tokens,
            "seed": args.seed,
            "concurrency": 1,
        },
        "outputs": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)

    for index, task in enumerate(tasks, start=1):
        started = time.monotonic()
        payload = {
            "model": args.model,
            "messages": [{"role": "user", "content": task["prompt"]}],
            "temperature": args.temperature,
            "top_p": args.top_p,
            "max_tokens": int(task.get("maxNewTokens") or args.max_tokens),
            "seed": args.seed,
            "stream": True,
            "stream_options": {"include_usage": True},
            "reasoning_effort": "none",
            "chat_template_kwargs": {"enable_thinking": False},
        }
        response = requests.post(
            args.endpoint.rstrip("/") + "/v1/chat/completions",
            json=payload,
            stream=True,
            timeout=(30, args.request_timeout),
        )
        response.raise_for_status()

        chunks: list[str] = []
        first_token = None
        first_candidate = None
        first_three = None
        first_ten = None
        finish_reason = None
        usage = None

        for raw in response.iter_lines(decode_unicode=True):
            if not raw:
                continue
            line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if not line.startswith("data:"):
                continue
            body = line[len("data:") :].strip()
            if body == "[DONE]":
                break
            try:
                event = json.loads(body)
            except json.JSONDecodeError:
                continue
            if event.get("usage") is not None:
                usage = event.get("usage")
            choices = event.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}
            text = delta.get("content") or ""
            if choice.get("finish_reason"):
                finish_reason = choice.get("finish_reason")
            if not text:
                continue
            now = time.monotonic()
            if first_token is None:
                first_token = now - started
            chunks.append(text)
            count = partial_candidate_count("".join(chunks))
            elapsed = now - started
            if count >= 1 and first_candidate is None:
                first_candidate = elapsed
            if count >= 3 and first_three is None:
                first_three = elapsed
            if count >= 10 and first_ten is None:
                first_ten = elapsed
        response.close()
        finished = time.monotonic()
        raw_text = "".join(chunks)
        requested = int(task.get("requestedCount") or 10)
        diagnostics = diagnose(
            raw_text,
            source=task.get("selectedText") or task.get("sourceText"),
            requested=requested,
        )
        row = {
            "id": task["id"],
            "output": raw_text,
            "finishReason": finish_reason,
            "latencySeconds": round(finished - started, 6),
            "firstTokenLatencySeconds": round(first_token, 6) if first_token is not None else None,
            "firstCandidateLatencySeconds": round(first_candidate, 6) if first_candidate is not None else None,
            "firstThreeCandidatesLatencySeconds": round(first_three, 6) if first_three is not None else None,
            "firstTenCandidatesLatencySeconds": round(first_ten, 6) if first_ten is not None else None,
            "usage": usage,
            "diagnostics": diagnostics,
        }
        result["outputs"].append(row)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"completed {index}/{len(tasks)} {task['id']} first3={row['firstThreeCandidatesLatencySeconds']}", flush=True)

    result["complete"] = True
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
