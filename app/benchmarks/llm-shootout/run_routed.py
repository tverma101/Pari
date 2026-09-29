"""Category-routed prompt experiment for the vague/fragment/run-on gaps.

The eval corpus category is used as ground truth here to isolate the prompt
variable. Production routing (heuristics in the app) is a separate PR.

Writes JSONL compatible with: node benchmarks/eval/run-eval.mjs --outputs <file>
"""
import argparse
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS = json.loads((ROOT / "benchmarks/eval/corpus.json").read_text())["cases"]

BASE_RULES = """Rules:
- Keep the original meaning exactly. Do not add facts. Do not drop negations.
- Keep every name, date, number, percentage, phone number, and link exactly as written.
- Output ONLY the rewritten text, nothing else."""

PROMPTS = {
    "default": f"""Rewrite the text below so it is clear, coherent, and grammatically correct English.
{BASE_RULES}

Text: {{text}}

Rewritten:""",

    "fragment": f"""Rewrite the text below as complete, flowing sentences.
- Merge sentence fragments into full sentences with subjects and verbs where the meaning allows.
- Keep the speaker's tone and any deliberate emphasis; do not flatten personality.
{BASE_RULES}

Text: {{text}}

Rewritten:""",

    "vague": f"""Rewrite the text below so every statement is concrete and specific.
- Replace vague placeholders ("the thing", "stuff", "somehow", "because reasons") with the most plausible concrete reading of what the writer means. It is acceptable to name the referent generically ("the situation", "the issue") but the sentence must state what happened or what is wanted.
- Do not invent names, dates, or numbers that are not implied by the text.
{BASE_RULES}

Text: {{text}}

Rewritten:""",

    "run_on": f"""Rewrite the text below with clean sentence structure.
- Split run-on chains into separate sentences or use correct connectors/semicolons.
- Vary sentence openings; keep every fact and its order.
{BASE_RULES}

Text: {{text}}

Rewritten:""",
}


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
    model, tokenizer = load(args.model_dir)
    sampler = make_sampler(temp=0.0)

    out_path = Path(args.out_file)
    done_ids = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                done_ids.add(json.loads(line)["id"])

    with out_path.open("a") as fh:
        for case in CORPUS:
            if case["id"] in done_ids:
                continue
            template = PROMPTS.get(case["category"], PROMPTS["default"])
            messages = [{"role": "user", "content": template.format(text=case["input"])}]
            prompt_ids = tokenizer.apply_chat_template(
                messages, add_generation_prompt=True, enable_thinking=False
            )
            t0 = time.time()
            out = generate(model, tokenizer, prompt=prompt_ids, max_tokens=args.max_tokens, sampler=sampler)
            dt = time.time() - t0
            text = strip_think(out)
            if "Text:" in text or "Rewritten" in text.split("\n")[0]:
                text = ""
            fh.write(json.dumps({"id": case["id"], "output": text, "seconds": round(dt, 2)}) + "\n")
            fh.flush()
            print(f"{case['id']:8s} {dt:5.1f}s  {text[:90]}", flush=True)

    print(f"done -> {out_path}")


if __name__ == "__main__":
    main()
