"""Generate N candidates per corpus case for best-of-N selection experiments.

By default this preserves the original greedy-first experiment. Pass an
explicit ``--temperatures`` list to mirror the production native schedule,
for example ``0.24,0.46,0.68,0.9``.
Writes JSONL lines: {"id", "candidates": [{"text", "temp"}]}
"""
import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = ROOT / "benchmarks/eval/corpus.json"


def load_corpus_data(corpus_arg: str | None) -> dict | list:
    p = Path(corpus_arg) if corpus_arg else DEFAULT_CORPUS
    if not p.is_absolute():
        cwd_path = Path.cwd() / p
        p = cwd_path if cwd_path.exists() else (ROOT / p).resolve()
    return json.loads(p.read_text())


def load_corpus(corpus_arg: str | None) -> list[dict]:
    data = load_corpus_data(corpus_arg)
    return data["cases"] if isinstance(data, dict) and "cases" in data else data

PROMPT = """Rewrite the text below so it is clear, coherent, and grammatically correct English.
Rules:
- Keep the original meaning exactly. Do not add facts. Do not drop negations.
- Keep every name, date, number, percentage, phone number, and link exactly as written.
- Fix typos, broken grammar, fragments, and run-ons. Make vague wording clearer only with facts already present; never invent a person, cause, amount, event, or outcome.
- Complete standalone “Because of …”, “Due to …”, or “Waiting …” fragments without inventing who acted or what happened.
- When a dense noun stack ends with “is pending … status,” make it grammatical by putting the stated status first; preserve every stated noun and do not add a cause or outcome.
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


def render_prompt(corpus_data: dict | list, text: str) -> str:
    if isinstance(corpus_data, dict) and isinstance(corpus_data.get("defaultInstruction"), str):
        return f"{corpus_data['defaultInstruction'].strip()}\n\nText: {text}\n\nRewritten:"
    return PROMPT.format(text=text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model_dir")
    ap.add_argument("out_file")
    ap.add_argument("--corpus", default=None, help="Corpus JSON path (default: benchmarks/eval/corpus.json)")
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--max-tokens", type=int, default=220)
    ap.add_argument("--temperatures", default=None, help="Comma-separated temperatures; overrides --n (for example 0.24,0.46,0.68,0.9)")
    ap.add_argument("--top-p", type=float, default=0.86)
    args = ap.parse_args()
    corpus_data = load_corpus_data(args.corpus)
    corpus = corpus_data["cases"] if isinstance(corpus_data, dict) and "cases" in corpus_data else corpus_data

    from mlx_lm import load
    from mlx_lm.generate import generate
    from mlx_lm.sample_utils import make_sampler

    print(f"loading {args.model_dir} ...", flush=True)
    model, tokenizer = load(args.model_dir)

    if args.temperatures:
        temps = [float(value.strip()) for value in args.temperatures.split(",") if value.strip()]
    else:
        temps = [0.0] + [round(0.4 + 0.3 * i, 2) for i in range(args.n - 1)]
    if not temps:
        raise SystemExit("--temperatures must contain at least one value")
    if any(temp < 0.0 or temp > 1.0 for temp in temps):
        raise SystemExit("temperatures must be between 0 and 1")
    samplers = [(t, make_sampler(temp=t, top_p=args.top_p)) for t in temps]

    out_path = Path(args.out_file)
    done_ids = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                done_ids.add(json.loads(line)["id"])

    with out_path.open("a") as fh:
        for case in corpus:
            if case["id"] in done_ids:
                continue
            messages = [{"role": "user", "content": render_prompt(corpus_data, case["input"])}]
            prompt_ids = tokenizer.apply_chat_template(
                messages, add_generation_prompt=True, enable_thinking=False
            )
            candidates = []
            for temp, sampler in samplers:
                t0 = time.time()
                out = generate(model, tokenizer, prompt=prompt_ids, max_tokens=args.max_tokens, sampler=sampler)
                dt = time.time() - t0
                text = strip_think(out)
                if "Text:" in text or "Rewritten" in text.split("\n")[0]:
                    text = ""
                candidates.append({"text": text, "temp": temp, "seconds": round(dt, 2)})
            fh.write(json.dumps({"id": case["id"], "candidates": candidates}) + "\n")
            fh.flush()
            print(f"{case['id']:8s} x{len(candidates)}  first: {candidates[0]['text'][:70]}", flush=True)

    print(f"done -> {out_path}")


if __name__ == "__main__":
    main()
