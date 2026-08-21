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
CORPUS = json.loads((ROOT / "benchmarks/eval/corpus.json").read_text())["cases"]

PROMPT = """Rewrite the text below so it is clear, coherent, and grammatically correct English.
Rules:
- Keep the original meaning exactly. Do not add facts. Do not drop negations.
- Keep every name, date, number, percentage, phone number, and link exactly as written.
- Fix typos, broken grammar, fragments, and run-ons. Turn vague wording into clear, concrete statements.
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model_dir")
    ap.add_argument("out_file")
    ap.add_argument("--max-tokens", type=int, default=220)
    args = ap.parse_args()

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
        for case in CORPUS:
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
            fh.write(json.dumps({"id": case["id"], "output": text, "seconds": round(dt, 2)}) + "\n")
            fh.flush()
            print(f"{case['id']:8s} {dt:5.1f}s  {text[:90]}", flush=True)

    print(f"done -> {out_path}")


if __name__ == "__main__":
    main()
