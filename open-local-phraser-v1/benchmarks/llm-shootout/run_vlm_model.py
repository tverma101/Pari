"""Run an MLX-VLM text model over the frozen Pari eval corpus.

This mirrors run_model.py for checkpoints whose supported runtime is
mlx-vlm (currently the Qwen3.5-4B benchmark control). It intentionally keeps
the prompt, corpus, output schema, resume behavior, and greedy settings equal
to the mlx-lm runner so model comparisons remain interpretable.
"""
import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = ROOT / "benchmarks/eval/corpus.json"

PROMPT = """Rewrite the text below so it is clear, coherent, and grammatically correct English.
Rules:
- Keep the original meaning exactly. Do not add facts. Do not drop negations.
- Keep every name, date, number, percentage, phone number, and link exactly as written.
- Fix typos, broken grammar, fragments, and run-ons. Turn vague wording into clear, concrete statements.
- Combine fragments into complete sentences where natural; split run-ons.
- Output ONLY the rewritten text, nothing else.

Text: {text}

Rewritten:"""


def load_corpus(corpus_arg: str | None) -> list[dict]:
    path = Path(corpus_arg) if corpus_arg else DEFAULT_CORPUS
    if not path.is_absolute():
        path = (Path.cwd() / path) if (Path.cwd() / path).exists() else (ROOT / path)
    data = json.loads(path.read_text())
    return data["cases"] if isinstance(data, dict) and "cases" in data else data


def strip_think(text: str) -> str:
    if text.startswith("<think>"):
        end = text.find("</think>")
        if end != -1:
            text = text[end + 8 :]
    return text.strip()


def token_count(tokenizer, text: str) -> int | None:
    try:
        try:
            return len(tokenizer.encode(text, add_special_tokens=False))
        except TypeError:
            return len(tokenizer.encode(text))
    except Exception:
        return None


def render_prompt(processor, instruction: str) -> str:
    tokenizer = processor.tokenizer if hasattr(processor, "tokenizer") else processor
    if hasattr(tokenizer, "apply_chat_template"):
        try:
            return tokenizer.apply_chat_template(
                [{"role": "user", "content": instruction}],
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        except TypeError:
            return tokenizer.apply_chat_template(
                [{"role": "user", "content": instruction}],
                tokenize=False,
                add_generation_prompt=True,
            )
    return instruction + "\n\nRewritten:"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model_dir")
    ap.add_argument("out_file")
    ap.add_argument("--corpus", default=None)
    ap.add_argument("--max-tokens", type=int, default=220)
    args = ap.parse_args()

    corpus = load_corpus(args.corpus)
    print(f"corpus: {args.corpus or DEFAULT_CORPUS} cases={len(corpus)}", flush=True)

    from mlx_vlm import generate, load

    print(f"loading {args.model_dir} ...", flush=True)
    started = time.time()
    model, processor = load(args.model_dir)
    print(f"loaded in {time.time() - started:.1f}s", flush=True)

    out_path = Path(args.out_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done_ids = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                done_ids.add(json.loads(line)["id"])

    with out_path.open("a") as handle:
        for case in corpus:
            if case["id"] in done_ids:
                continue
            prompt = render_prompt(processor, PROMPT.format(text=case["input"]))
            started = time.time()
            result = generate(
                model,
                processor,
                prompt=prompt,
                max_tokens=args.max_tokens,
                temperature=0.0,
                enable_thinking=False,
                verbose=False,
            )
            seconds = time.time() - started
            text = strip_think(getattr(result, "text", str(result)))
            if "Text:" in text or "Rewritten" in text.split("\n")[0]:
                text = ""
            output_tokens = token_count(processor.tokenizer, text)
            row = {
                "id": case["id"],
                "output": text,
                "seconds": round(seconds, 2),
                "peak_memory_gb": round(float(getattr(result, "peak_memory", 0.0) or 0.0), 3),
            }
            if output_tokens is not None:
                row["output_tokens"] = output_tokens
                row["tokens_per_second"] = round(output_tokens / max(seconds, 0.001), 2)
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            print(f"{case['id']:12s} {seconds:5.1f}s  {text[:90]}", flush=True)

    print(f"done -> {out_path}")


if __name__ == "__main__":
    main()
