"""Run a local MLX model over the adversarial eval corpus.

Writes JSONL {"id", "output"} lines compatible with:
    node benchmarks/eval/run-eval.mjs --outputs <file>

Usage:
    python benchmarks/llm-shootout/run_model.py <model_dir> <out.jsonl> [--max-tokens 220]
"""
import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = ROOT / "benchmarks/eval/corpus.json"


def load_corpus(corpus_arg: str | None) -> list[dict]:
    p = Path(corpus_arg) if corpus_arg else DEFAULT_CORPUS
    if not p.is_absolute():
        cand = Path.cwd() / p
        p = cand if cand.exists() else (ROOT / p).resolve() if not p.exists() else p.resolve()
        if not p.exists() and corpus_arg:
            p = (ROOT / corpus_arg).resolve()
    data = json.loads(p.read_text())
    return data["cases"] if isinstance(data, dict) and "cases" in data else data

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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model_dir")
    ap.add_argument("out_file")
    ap.add_argument("--corpus", default=None, help="Corpus JSON path (default: benchmarks/eval/corpus.json). For QuillBot frozen use benchmarks/quillbot/corpus.frozen.json")
    ap.add_argument("--max-tokens", type=int, default=220)
    args = ap.parse_args()
    corpus = load_corpus(args.corpus)
    print(f"corpus: {args.corpus or str(DEFAULT_CORPUS)} cases={len(corpus)}", flush=True)

    from mlx_lm import load
    from mlx_lm.generate import generate
    from mlx_lm.sample_utils import make_sampler

    print(f"loading {args.model_dir} ...", flush=True)
    t0 = time.time()
    model, tokenizer = load(args.model_dir)
    print(f"loaded in {time.time()-t0:.1f}s", flush=True)

    sampler = make_sampler(temp=0.0)
    out_path = Path(args.out_file)
    done_ids = set()
    if out_path.exists():  # resume support
        for line in out_path.read_text().splitlines():
            if line.strip():
                done_ids.add(json.loads(line)["id"])

    with out_path.open("a") as fh:
        for case in corpus:
            if case["id"] in done_ids:
                continue
            messages = [{"role": "user", "content": PROMPT.format(text=case["input"])}]
            prompt_ids = tokenizer.apply_chat_template(
                messages, add_generation_prompt=True, enable_thinking=False
            )
            t0 = time.time()
            out = generate(model, tokenizer, prompt=prompt_ids, max_tokens=args.max_tokens, sampler=sampler)
            dt = time.time() - t0
            text = strip_think(out)
            # The model must never echo meta instructions back.
            if "Text:" in text or "Rewritten" in text.split("\n")[0]:
                text = ""
            output_tokens = token_count(tokenizer, text)
            row = {"id": case["id"], "output": text, "seconds": round(dt, 2)}
            if output_tokens is not None:
                row["output_tokens"] = output_tokens
                row["tokens_per_second"] = round(output_tokens / max(dt, 0.001), 2)
            try:
                row["prompt_tokens"] = len(prompt_ids)
            except TypeError:
                pass
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            print(f"{case['id']:8s} {dt:5.1f}s  {text[:90]}", flush=True)

    print(f"done -> {out_path}")


if __name__ == "__main__":
    main()
