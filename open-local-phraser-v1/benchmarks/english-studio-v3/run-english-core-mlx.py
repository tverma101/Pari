"""Run a local MLX model over a Pari English Core task JSONL.

Examples:
    node build-english-core.mjs
    python run-english-core-mlx.py <model_dir> shadow-result.json

    python build-english-core-public-fast.py
    python run-english-core-mlx.py <model_dir> public-result.json \
        --tasks english-core-public-fast.jsonl

    node build-english-core-prompt-robustness.mjs
    python run-english-core-mlx.py <model_dir> prompt-result.json \
        --tasks english-core-prompt-robustness.jsonl

The runner records task hashes, environment metadata, decoding settings, and raw
output hashes so promotion-quality comparisons can be reproduced.
"""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_TASKS = HERE / "english-core-shadow.jsonl"


def strip_think(text: str) -> str:
    text = text.strip()
    if text.startswith("<think>"):
        end = text.find("</think>")
        if end != -1:
            text = text[end + 8 :].strip()
    return text


def resolve_path(value: str | None) -> Path:
    if value is None:
        return DEFAULT_TASKS
    p = Path(value)
    if not p.is_absolute():
        local = HERE / p
        if local.exists():
            return local
        p = Path.cwd() / p
    return p.resolve()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def chip_name() -> str:
    if sys.platform == "darwin":
        for key in ("machdep.cpu.brand_string", "hw.model"):
            try:
                value = subprocess.check_output(["sysctl", "-n", key], text=True).strip()
                if value:
                    return value
            except Exception:
                pass
    return platform.processor() or "unknown"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model_dir")
    ap.add_argument("result_file")
    ap.add_argument("--tasks", default=None, help="Task JSONL path; defaults to english-core-shadow.jsonl")
    ap.add_argument("--max-tokens", type=int, default=220)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=0, help="Generation RNG seed; default 0 for reproducibility")
    ap.add_argument("--model-revision", default="unknown")
    ap.add_argument("--quantization", default="unknown")
    ap.add_argument("--checkpoint-type", choices=["base", "instruct", "chat", "specialized", "unknown"], default="unknown")
    ap.add_argument("--chat-template-label", default="tokenizer.apply_chat_template")
    ap.add_argument("--benchmark-revision", default="unknown", help="Git commit/revision containing the benchmark files")
    args = ap.parse_args()

    task_path = resolve_path(args.tasks)
    if not task_path.exists():
        raise SystemExit(f"Missing task file: {task_path}. Build the requested English Core suite first.")

    task_bytes = task_path.read_bytes()
    tasks = [json.loads(line) for line in task_bytes.decode("utf-8").splitlines() if line.strip()]

    import mlx.core as mx
    from mlx_lm import load
    from mlx_lm.generate import generate
    from mlx_lm.sample_utils import make_sampler

    mx.random.seed(args.seed)
    print(f"tasks: {task_path} cases={len(tasks)} sha256={sha256_bytes(task_bytes)}", flush=True)
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
            prompt_ids = tokenizer.apply_chat_template(messages, add_generation_prompt=True)

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
        outputs.append({
            "id": task["id"],
            "output": text,
            "latencySeconds": round(latency, 4),
        })
        print(f"[{i:04d}/{len(tasks):04d}] {task['id']} {latency:.2f}s  {text[:100]}", flush=True)

    outputs_bytes = json.dumps(outputs, ensure_ascii=False, sort_keys=True).encode("utf-8")
    result = {
        "runId": f"english-core-{int(time.time())}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": {
            "name": Path(args.model_dir).name,
            "repoOrName": args.model_dir,
            "revision": args.model_revision,
            "quantization": args.quantization,
            "checkpointType": args.checkpoint_type,
            "runtime": "mlx-lm",
            "runtimeVersion": package_version("mlx-lm"),
            "chatTemplate": args.chat_template_label,
        },
        "hardware": {
            "machine": platform.machine(),
            "chip": chip_name(),
            "os": platform.platform(),
            "python": platform.python_version(),
        },
        "taskFile": str(task_path),
        "taskFileSha256": sha256_bytes(task_bytes),
        "decoding": {
            "temperature": args.temperature,
            "maxNewTokens": args.max_tokens,
            "seed": args.seed,
        },
        "runtime": {
            "coldLoadSeconds": round(load_seconds, 4),
        },
        "outputs": outputs,
        "reproducibility": {
            "benchmarkRevision": args.benchmark_revision,
            "rawOutputSha256": sha256_bytes(outputs_bytes),
            "notes": [
                "Model artifact hash is not inferred from a directory path; supply/record it separately when promotion-quality reproducibility requires it.",
                "Checkpoint type and quantization are caller-supplied metadata and should be verified against the actual model artifact."
            ],
        },
    }

    Path(args.result_file).write_text(json.dumps(result, indent=2) + "\n")
    print(f"done -> {args.result_file}")


if __name__ == "__main__":
    main()
