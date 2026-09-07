"""Run an OpenAI-compatible local model over Pari's adversarial eval corpus.

This adapter is intentionally model-agnostic. It exists for local runtimes that
serve an OpenAI-compatible `/v1/chat/completions` endpoint but cannot currently
be loaded by Pari's pinned `mlx-lm` path directly (for example a new model
architecture with a separate Apple-Silicon runtime).

Writes JSONL {"id", "output"} lines compatible with:
    node benchmarks/eval/run-eval.mjs --outputs <file>

Example (Ling-3.0-tiny through rapid-mlx):
    rapid-mlx serve ling-3.0-tiny-4bit
    python benchmarks/llm-shootout/run_openai_compatible.py \
      --base-url http://127.0.0.1:8000/v1 \
      --model ling-3.0-tiny-4bit \
      --out benchmarks/llm-shootout/ling3-tiny-4bit.jsonl \
      --chat-template-kwargs '{"enable_thinking": false}'
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = ROOT / "benchmarks/eval/corpus.json"


def load_corpus(corpus_arg: str | None) -> list[dict[str, Any]]:
    p = Path(corpus_arg) if corpus_arg else DEFAULT_CORPUS
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve() if p.exists() else (ROOT / p).resolve()
        # fallback: try relative to ROOT
        if not p.exists():
            p = (ROOT / corpus_arg).resolve() if corpus_arg else DEFAULT_CORPUS
    data = json.loads(p.read_text())
    cases = data["cases"] if isinstance(data, dict) and "cases" in data else data
    return cases

PROMPT = """Rewrite the text below so it is clear, coherent, and grammatically correct English.
Rules:
- Keep the original meaning exactly. Do not add facts. Do not drop negations.
- Keep every name, date, number, percentage, phone number, and link exactly as written.
- Fix typos, broken grammar, fragments, and run-ons. Make vague wording clearer only with facts already present; never invent a person, cause, amount, event, or outcome.
- Complete standalone “Because of …”, “Due to …”, or “Waiting …” fragments without inventing who acted or what happened.
- Combine fragments into complete sentences where natural; split run-ons.
- Output ONLY the rewritten text, nothing else.

Text: {text}

Rewritten:"""


def strip_control_text(text: str) -> str:
    value = text.strip()
    if value.startswith("<think>"):
        end = value.find("</think>")
        if end != -1:
            value = value[end + len("</think>") :].strip()
    if "Text:" in value or value.lower().startswith("rewritten:"):
        value = value.split("Rewritten:", 1)[-1].strip()
    return value.strip().strip('"“”')


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
) -> tuple[str, dict[str, Any], dict[str, Any]]:
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
        raise RuntimeError(f"HTTP {exc.code} from local model server: {detail[:800]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach local model server at {endpoint(base_url)}: {exc}") from exc

    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected OpenAI-compatible response: {json.dumps(payload)[:800]}") from exc

    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise RuntimeError(f"Response did not contain text content: {json.dumps(payload)[:800]}")
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    metadata = {
        key: payload[key]
        for key in ("id", "model", "system_fingerprint")
        if isinstance(payload.get(key), (str, int, float))
    }
    return strip_control_text(content), usage, metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--corpus", default=None, help="Path to corpus JSON (default: benchmarks/eval/corpus.json). For QuillBot held-out use benchmarks/quillbot/corpus.frozen.json")
    parser.add_argument("--max-tokens", type=int, default=220)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--extra-body",
        default=None,
        help="Optional JSON object merged into every request body.",
    )
    parser.add_argument(
        "--chat-template-kwargs",
        default=None,
        help="Optional JSON object sent as chat_template_kwargs (for example to disable thinking).",
    )
    args = parser.parse_args()

    corpus = load_corpus(args.corpus)
    if args.offset < 0:
        raise SystemExit("--offset must be non-negative")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be positive when provided")
    corpus = corpus[args.offset : args.offset + args.limit if args.limit is not None else None]
    print(
        f"corpus: {args.corpus or str(DEFAULT_CORPUS)} cases={len(corpus)} "
        f"offset={args.offset} limit={args.limit if args.limit is not None else 'all'}",
        flush=True,
    )
    extra_body = parse_json_object(args.extra_body, "--extra-body")
    chat_template_kwargs = parse_json_object(args.chat_template_kwargs, "--chat-template-kwargs")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done_ids: set[str] = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                done_ids.add(json.loads(line)["id"])

    print(f"server={endpoint(args.base_url)} model={args.model}", flush=True)
    with out_path.open("a") as fh:
        for case in corpus:
            if case["id"] in done_ids:
                continue

            started = time.perf_counter()
            text, usage, metadata = request_completion(
                base_url=args.base_url,
                model=args.model,
                prompt=PROMPT.format(text=case["input"]),
                max_tokens=max(32, args.max_tokens),
                temperature=max(0.0, args.temperature),
                timeout=max(1.0, args.timeout),
                api_key=args.api_key,
                extra_body=extra_body,
                chat_template_kwargs=chat_template_kwargs,
            )
            elapsed = time.perf_counter() - started

            row = {
                "id": case["id"],
                "output": text,
                "seconds": round(elapsed, 2),
                "model": args.model,
            }
            if isinstance(metadata.get("model"), str):
                row["served_model"] = metadata["model"]
            for field, usage_key in (("prompt_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens")):
                value = usage.get(usage_key)
                if isinstance(value, (int, float)):
                    row[field] = value
            if isinstance(row.get("output_tokens"), (int, float)):
                row["tokens_per_second"] = round(row["output_tokens"] / max(elapsed, 0.001), 2)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            print(f"{case['id']:8s} {elapsed:5.1f}s  {text[:90]}", flush=True)

    print(f"done -> {out_path}")


if __name__ == "__main__":
    main()
