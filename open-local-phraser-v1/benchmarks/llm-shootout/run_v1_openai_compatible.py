"""Run Pari English Studio V1 tasks through any local OpenAI-compatible runtime.

This runner is transport-only. Task semantics live in v1_runner_common.py and
v1-prompt-contracts.json so llama.cpp/Bonsai/rapid-mlx/etc. can be compared with
the same requested behavior.

Expected input is JSONL produced by build-v1-core.mjs.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from v1_runner_common import (
    DEFAULT_SUITE,
    expanded_jobs,
    is_candidate_route,
    load_jsonl,
    parse_candidates,
    render_prompt,
    strip_control_text,
)


def endpoint(base_url: str) -> str:
    return base_url.rstrip("/") + "/chat/completions"


def parse_json_object(raw: str | None, flag_name: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{flag_name} must be valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"{flag_name} must decode to a JSON object")
    return value


def request_completion(
    *,
    base_url: str,
    model: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    timeout: float,
    api_key: str | None,
    extra_body: dict[str, Any],
    chat_template_kwargs: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    body.update(extra_body)
    if chat_template_kwargs:
        body["chat_template_kwargs"] = chat_template_kwargs

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(
        endpoint(base_url),
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from local model server: {detail[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach local model server at {endpoint(base_url)}: {exc}") from exc

    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected OpenAI-compatible response: {json.dumps(payload)[:1000]}") from exc

    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise RuntimeError(f"Response did not contain text content: {json.dumps(payload)[:1000]}")

    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return strip_control_text(content), usage


def job_key(job: dict[str, Any]) -> str:
    return f"{job['instanceId']}::{job.get('runVariant', 'default')}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--suite", default=str(DEFAULT_SUITE))
    parser.add_argument("--out", required=True)
    parser.add_argument("--temperature", type=float, default=0.35)
    parser.add_argument("--max-tokens", type=int, default=420)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--extra-body", default=None, help="JSON object merged into every request body")
    parser.add_argument("--chat-template-kwargs", default=None, help="JSON object sent as chat_template_kwargs")
    parser.add_argument("--route", action="append", default=[], help="Optional route filter; may be repeated")
    parser.add_argument("--limit", type=int, default=None, help="Optional expanded-job limit for smoke tests")
    args = parser.parse_args()

    suite_path = Path(args.suite)
    if not suite_path.is_absolute():
        suite_path = (Path.cwd() / suite_path).resolve()
    cases = load_jsonl(suite_path)
    jobs = [job for case in cases for job in expanded_jobs(case)]
    if args.route:
        allowed = set(args.route)
        jobs = [job for job in jobs if job["route"] in allowed]
    if args.limit is not None:
        jobs = jobs[: max(0, args.limit)]

    extra_body = parse_json_object(args.extra_body, "--extra-body")
    chat_template_kwargs = parse_json_object(args.chat_template_kwargs, "--chat-template-kwargs")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    completed: set[str] = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("jobKey"):
                completed.add(row["jobKey"])

    print(
        f"suite={suite_path} expanded_jobs={len(jobs)} server={endpoint(args.base_url)} model={args.model}",
        flush=True,
    )

    with out_path.open("a") as fh:
        for index, job in enumerate(jobs, start=1):
            key = job_key(job)
            if key in completed:
                continue

            candidate_count = job.get("candidateCount")
            prompt = render_prompt(
                job,
                strength=job.get("strength"),
                candidate_count=candidate_count,
            )

            started = time.perf_counter()
            raw, usage = request_completion(
                base_url=args.base_url,
                model=args.model,
                prompt=prompt,
                max_tokens=max(32, args.max_tokens),
                temperature=max(0.0, args.temperature),
                timeout=max(1.0, args.timeout),
                api_key=args.api_key,
                extra_body=extra_body,
                chat_template_kwargs=chat_template_kwargs,
            )
            elapsed = time.perf_counter() - started

            row: dict[str, Any] = {
                "jobKey": key,
                "instanceId": job["instanceId"],
                "runVariant": job.get("runVariant", "default"),
                "route": job["route"],
                "sourceSuite": job["sourceSuite"],
                "sourceId": job["sourceId"],
                "model": args.model,
                "seconds": round(elapsed, 4),
                "strength": job.get("strength"),
                "candidateCountRequested": candidate_count,
                "usage": usage,
                "rawOutput": raw,
            }
            if job.get("selection") is not None:
                row["selection"] = job["selection"]

            if is_candidate_route(job["route"]):
                row["candidates"] = parse_candidates(raw, limit=candidate_count)
                row["candidateCountParsed"] = len(row["candidates"])
            else:
                row["output"] = raw

            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            preview = (row.get("candidates") or [row.get("output", "")])[0] if (row.get("candidates") or row.get("output")) else ""
            print(f"[{index}/{len(jobs)}] {key} {elapsed:.2f}s {str(preview)[:90]}", flush=True)

    print(f"done -> {out_path}")


if __name__ == "__main__":
    main()
