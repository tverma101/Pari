"""Run Pari English Studio V1 tasks directly through mlx-lm.

Task semantics and candidate parsing are shared with the OpenAI-compatible runner
through v1_runner_common.py so transport does not change the benchmark contract.
"""

from __future__ import annotations

import argparse
import json
import time
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


def job_key(job: dict[str, Any]) -> str:
    return f"{job['instanceId']}::{job.get('runVariant', 'default')}"


def apply_chat_template(tokenizer: Any, prompt: str, disable_thinking: bool) -> Any:
    messages = [{"role": "user", "content": prompt}]
    kwargs: dict[str, Any] = {"add_generation_prompt": True}
    if disable_thinking:
        kwargs["enable_thinking"] = False
    try:
        return tokenizer.apply_chat_template(messages, **kwargs)
    except (TypeError, ValueError):
        # Some non-Qwen templates do not define an enable_thinking variable.
        kwargs.pop("enable_thinking", None)
        return tokenizer.apply_chat_template(messages, **kwargs)


def token_count(tokenizer: Any, text: str) -> int | None:
    try:
        encoded = tokenizer.encode(text)
        return len(encoded)
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_dir")
    parser.add_argument("out_file")
    parser.add_argument("--model-id", default=None, help="Exact model ID/revision label stored in results")
    parser.add_argument("--suite", default=str(DEFAULT_SUITE))
    parser.add_argument("--temperature", type=float, default=0.35)
    parser.add_argument("--max-tokens", type=int, default=420)
    parser.add_argument("--disable-thinking", action="store_true", default=True)
    parser.add_argument("--route", action="append", default=[])
    parser.add_argument("--limit", type=int, default=None)
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

    from mlx_lm import load
    from mlx_lm.generate import generate
    from mlx_lm.sample_utils import make_sampler

    print(f"loading {args.model_dir} ...", flush=True)
    load_started = time.perf_counter()
    model, tokenizer = load(args.model_dir)
    load_seconds = time.perf_counter() - load_started
    print(f"loaded in {load_seconds:.2f}s", flush=True)

    sampler = make_sampler(temp=max(0.0, args.temperature))
    out_path = Path(args.out_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    completed: set[str] = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("jobKey"):
                completed.add(row["jobKey"])

    model_label = args.model_id or args.model_dir
    print(f"suite={suite_path} expanded_jobs={len(jobs)} model={model_label}", flush=True)

    with out_path.open("a") as fh:
        for index, job in enumerate(jobs, start=1):
            key = job_key(job)
            if key in completed:
                continue

            candidate_count = job.get("candidateCount")
            prompt = render_prompt(job, strength=job.get("strength"), candidate_count=candidate_count)
            prompt_ids = apply_chat_template(tokenizer, prompt, args.disable_thinking)

            started = time.perf_counter()
            raw = generate(
                model,
                tokenizer,
                prompt=prompt_ids,
                max_tokens=max(32, args.max_tokens),
                sampler=sampler,
            )
            elapsed = time.perf_counter() - started
            raw = strip_control_text(raw)
            output_tokens = token_count(tokenizer, raw)

            row: dict[str, Any] = {
                "jobKey": key,
                "instanceId": job["instanceId"],
                "runVariant": job.get("runVariant", "default"),
                "route": job["route"],
                "sourceSuite": job["sourceSuite"],
                "sourceId": job["sourceId"],
                "model": model_label,
                "modelDir": args.model_dir,
                "loadSeconds": round(load_seconds, 4),
                "seconds": round(elapsed, 4),
                "strength": job.get("strength"),
                "candidateCountRequested": candidate_count,
                "outputTokensEstimated": output_tokens,
                "decodeTokensPerSecondEstimated": round(output_tokens / elapsed, 3) if output_tokens and elapsed > 0 else None,
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
