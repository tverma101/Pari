"""Run a local MLX model over the Pari English Core shadow benchmark.

Prerequisite:
    node build-english-core.mjs

Usage:
    python run-english-core-mlx.py <model_dir> <result.json> [--max-tokens 220]

The result format is compatible with english-core-result-schema.json and
score-english-core.mjs. Generative-expression cases are emitted raw and require
external scoring before the full English Core shadow composite can be computed.
"""

import argparse
import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS = HERE / "english-core-shadow.jsonl"


def strip_think(text: str) -> str:
    text = text.strip()
    if text.startswith("<think>"):
        end = text.find("</think>")
        if end != -1:
            text = text[end + 8 :].strip()
    return text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model_dir")
    ap.add_argument("result_file")
    ap.add_argument("--max-tokens", type=int, default=220)
    ap.add_argument("--temperature", type=float, default=0.0)
    args = ap.parse_args()

    if not TASKS.exists():
        raise SystemExit(
            f"Missing {TASKS.name}. Run `node {HERE / 'build-english-core.mjs'}` first."
        )

    tasks = [json.loads(line) for line in TASKS.read_text().splitlines() if line.strip()]

    from mlx_lm import load
    from mlx_lm.generate import generate
    from mlx_lm.sample_utils import make_sampler

    print(f"loading {args.model_dir} ...", flush=True)
    t0 = time.time()
    model, tokenizer = load(args.model_dir)
    load_seconds = time.time() - t0
    print(f"loaded in {load_seconds:.2f}s", flush=True)

    sampler = make_sampler(temp=args.temperature)
    outputs = []

    for i, task in enumerate(tasks, 1):
        messages = [{"role": "user", "content": task["prompt"]}]
        try:
            prompt_ids = tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        except TypeError:
            prompt_ids = tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
            )

        # Forced-choice cases need very few output tokens; generative cases need room.
        max_tokens = args.max_tokens if task.get("generative") else 8
        t1 = time.time()
        output = generate(
            model,
            tokenizer,
            prompt=prompt_ids,
            max_tokens=max_tokens,
            sampler=sampler,
        )
        latency = time.time() - t1
        text = strip_think(output)
        outputs.append(
            {
                "id": task["id"],
                "output": text,
                "latencySeconds": round(latency, 4),
            }
        )
        print(f"[{i:02d}/{len(tasks):02d}] {task['id']} {latency:.2f}s  {text[:100]}", flush=True)

    result = {
        "runId": f"english-core-{int(time.time())}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": {
            "name": Path(args.model_dir).name,
            "repoOrName": args.model_dir,
            "runtime": "mlx-lm",
        },
        "decoding": {
            "temperature": args.temperature,
            "maxNewTokens": args.max_tokens,
            "seed": None,
        },
        "runtime": {
            "coldLoadSeconds": round(load_seconds, 4),
        },
        "outputs": outputs,
    }

    Path(args.result_file).write_text(json.dumps(result, indent=2) + "\n")
    print(f"done -> {args.result_file}")


if __name__ == "__main__":
    main()
