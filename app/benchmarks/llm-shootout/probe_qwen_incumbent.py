"""Probe the incumbent Qwen3-4B-MLX-4bit on adversarial paraphrase cases.

Raw capability check: no repair pipeline, just the model + a strict prompt.
Results feed the model-shootout baseline in benchmarks/llm-shootout/.
"""
import json
import os
import time
import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "native-models/config.json"


def configured_model_path() -> Path:
    override = os.environ.get("PARI_NATIVE_MODEL_PATH", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    config = json.loads(CONFIG_PATH.read_text())
    local_path = config["nativeModel"]["localPath"]
    return (REPO_ROOT / local_path).resolve()

CASES = [
    # (id, input, why)
    ("broken-words", "i dont knwo waht happned but it lookd liek the meetign went badlly", "typos + missing apostrophes"),
    ("word-salad", "deadline moved because client feedback late was the reason project delay happened", "scrambled syntax"),
    ("vague", "the thing with the guy from before didnt really go how i wanted it to go honestly", "vague referents"),
    ("runon", "I woke up late and I missed the bus and then I forgot my laptop and the meeting started without me and nobody told me anything", "run-on chain"),
    ("fragment", "Not sure. Maybe Friday. If that works. Otherwise next week sometime.", "fragments"),
    ("negation-guard", "I never said the report was wrong, I said the numbers were not final.", "must preserve negation"),
    ("anchor-guard", "Send the 42.5% summary to Maya Chen by 2026-08-25 or call +1-555-0142.", "numbers/names/dates must survive"),
    ("formal-shift", "hey so basically the results came back and they were kinda mixed but mostly fine i think", "register cleanup"),
]

PROMPT = """Rewrite the text below so it is clear, coherent, and grammatically correct English.
Rules:
- Keep the original meaning exactly. Do not add facts. Do not drop negations.
- Keep every name, date, number, percentage, phone number, and link exactly as written.
- Fix typos, broken grammar, fragments, and run-ons.
- Output ONLY the rewritten text, nothing else.

Text: {text}

Rewritten:"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe a configured MLX native model on Pari safety cases.")
    parser.add_argument("model_dir", nargs="?", type=Path, help="Optional MLX checkpoint path; defaults to Pari config.")
    parser.add_argument("--output", type=Path, help="Optional JSON output path.")
    args = parser.parse_args()
    model_dir = (args.model_dir or configured_model_path()).expanduser().resolve()

    from mlx_lm import load
    from mlx_lm.generate import generate
    from mlx_lm.sample_utils import make_sampler

    print(f"loading {model_dir} ...", flush=True)
    t0 = time.time()
    model, tokenizer = load(str(model_dir))
    print(f"loaded in {time.time()-t0:.1f}s", flush=True)

    sampler = make_sampler(temp=0.0)
    rows = []
    for case_id, text, why in CASES:
        messages = [{"role": "user", "content": PROMPT.format(text=text)}]
        prompt_ids = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, enable_thinking=False
        )
        t0 = time.time()
        out = generate(model, tokenizer, prompt=prompt_ids, max_tokens=220, sampler=sampler)
        dt = time.time() - t0
        out_text = out.strip()
        if out_text.startswith("<think>"):
            end = out_text.find("</think>")
            out_text = out_text[end + 8 :].strip() if end != -1 else out_text
        rows.append({"id": case_id, "why": why, "input": text, "output": out_text, "seconds": round(dt, 2)})
        print(f"\n=== {case_id} ({dt:.1f}s) ===\nIN : {text}\nOUT: {out_text}", flush=True)

    out_path = args.output or (Path(__file__).parent / "qwen3-4b-probe-results.json")
    out_path.write_text(json.dumps(rows, indent=2))
    print(f"\nsaved -> {out_path}")


if __name__ == "__main__":
    main()
