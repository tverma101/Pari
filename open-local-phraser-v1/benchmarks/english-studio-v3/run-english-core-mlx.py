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

Use --prompt-mode plain for a base model that should not be wrapped in a chat
template. `auto` is exploratory only; promotion-quality runs should choose an
explicit adaptation mode and record exact artifact/revision metadata.
"""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_TASKS = HERE / "english-core-shadow.jsonl"
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


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


def sha256_text(text: str | None) -> str | None:
    if not text:
        return None
    return sha256_bytes(text.encode("utf-8"))


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def sysctl_value(key: str) -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        value = subprocess.check_output(["sysctl", "-n", key], text=True).strip()
        return value or None
    except Exception:
        return None


def chip_name() -> str:
    return sysctl_value("machdep.cpu.brand_string") or sysctl_value("hw.model") or platform.processor() or "unknown"


def memory_gb() -> float | None:
    value = sysctl_value("hw.memsize")
    if not value:
        return None
    try:
        return round(int(value) / (1024 ** 3), 3)
    except ValueError:
        return None


def prompt_for_task(tokenizer, text: str, mode: str):
    if mode == "plain":
        return text, "plain", "none"

    messages = [{"role": "user", "content": text}]
    try:
        try:
            encoded = tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            return encoded, "chat_template", "enable_thinking=false"
        except TypeError:
            encoded = tokenizer.apply_chat_template(messages, add_generation_prompt=True)
            return encoded, "chat_template", "template_default_no_enable_thinking_arg"
    except Exception:
        if mode == "chat":
            raise
        return text, "plain_fallback", "chat_template_failed"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model_dir")
    ap.add_argument("result_file")
    ap.add_argument("--tasks", default=None, help="Task JSONL path; defaults to english-core-shadow.jsonl")
    ap.add_argument("--max-tokens", type=int, default=220)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--top-p", type=float, default=1.0)
    ap.add_argument("--top-k", type=int, default=0)
    ap.add_argument("--seed", type=int, default=0, help="Generation RNG seed; default 0 for reproducibility")
    ap.add_argument("--model-revision", default="unknown")
    ap.add_argument("--artifact-sha256", default=None, help="SHA-256 identifying the exact evaluated model artifact/build")
    ap.add_argument("--quantization", default="unknown", help="Explicit value such as full/fp16/bf16/q8/q4")
    ap.add_argument("--checkpoint-type", choices=["base", "instruct", "chat", "specialized", "unknown"], default="unknown")
    ap.add_argument("--prompt-mode", choices=["auto", "chat", "plain"], default="auto")
    ap.add_argument("--chat-template-label", default="tokenizer.apply_chat_template")
    ap.add_argument("--benchmark-revision", default="unknown", help="Git commit/revision containing the benchmark files")
    args = ap.parse_args()

    if not 0.0 <= args.top_p <= 1.0:
        raise SystemExit("--top-p must be in [0,1]")
    if args.top_k < 0:
        raise SystemExit("--top-k must be >= 0")
    if args.max_tokens < 1:
        raise SystemExit("--max-tokens must be >= 1")
    if args.artifact_sha256 is not None and not SHA256_RE.fullmatch(args.artifact_sha256):
        raise SystemExit("--artifact-sha256 must be exactly 64 hexadecimal characters")

    task_path = resolve_path(args.tasks)
    if not task_path.exists():
        raise SystemExit(f"Missing task file: {task_path}. Build the requested English Core suite first.")

    task_bytes = task_path.read_bytes()
    tasks = [json.loads(line) for line in task_bytes.decode("utf-8").splitlines() if line.strip()]
    task_ids = [task.get("id") for task in tasks]
    if any(not task_id for task_id in task_ids):
        raise SystemExit("Task file contains an item without an id")
    if len(task_ids) != len(set(task_ids)):
        raise SystemExit("Task file contains duplicate ids")

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

    sampler = make_sampler(temp=args.temperature, top_p=args.top_p, top_k=args.top_k)
    outputs = []
    adaptation_modes = set()
    adaptation_details = set()

    for i, task in enumerate(tasks, 1):
        prompt, adaptation_mode, adaptation_detail = prompt_for_task(tokenizer, task["prompt"], args.prompt_mode)
        adaptation_modes.add(adaptation_mode)
        adaptation_details.add(adaptation_detail)

        max_tokens = args.max_tokens if task.get("generative") else 8
        t1 = time.time()
        output = generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            sampler=sampler,
        )
        latency = time.time() - t1
        text = strip_think(output)
        outputs.append({
            "id": task["id"],
            "output": text,
            "latencySeconds": round(latency, 4),
            "promptAdaptation": adaptation_mode,
            "promptAdaptationDetail": adaptation_detail,
        })
        print(f"[{i:04d}/{len(tasks):04d}] {task['id']} {latency:.2f}s  {text[:100]}", flush=True)

    outputs_bytes = json.dumps(outputs, ensure_ascii=False, sort_keys=True).encode("utf-8")
    chat_template = getattr(tokenizer, "chat_template", None)
    tokenizer_name = getattr(tokenizer, "name_or_path", None) or getattr(tokenizer, "name", None) or "unknown"
    result = {
        "runId": f"english-core-{int(time.time())}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": {
            "name": Path(args.model_dir).name,
            "repoOrName": args.model_dir,
            "revision": args.model_revision,
            "artifactSha256": args.artifact_sha256,
            "quantization": args.quantization,
            "checkpointType": args.checkpoint_type,
            "runtime": "mlx-lm",
            "runtimeVersion": package_version("mlx-lm"),
            "tokenizerName": str(tokenizer_name),
            "chatTemplate": args.chat_template_label if "chat_template" in adaptation_modes else "none/plain",
            "chatTemplateSha256": sha256_text(chat_template if isinstance(chat_template, str) else None),
        },
        "hardware": {
            "machine": platform.machine(),
            "chip": chip_name(),
            "memoryGB": memory_gb(),
            "os": platform.platform(),
            "python": platform.python_version(),
        },
        "taskFile": str(task_path),
        "taskFileSha256": sha256_bytes(task_bytes),
        "taskCount": len(tasks),
        "promptModeRequested": args.prompt_mode,
        "promptAdaptationModesObserved": sorted(adaptation_modes),
        "promptAdaptationDetailsObserved": sorted(adaptation_details),
        "decoding": {
            "temperature": args.temperature,
            "topP": args.top_p,
            "topK": args.top_k,
            "maxNewTokens": args.max_tokens,
            "forcedChoiceMaxNewTokens": 8,
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
                "artifactSha256 is caller-supplied because hashing an arbitrary model directory safely/portably is outside this runner; promotion validation requires an exact artifact/build identity.",
                "Checkpoint type, revision, artifact hash and quantization are caller-supplied metadata and must match the evaluated artifact.",
                "Base models should generally be run with --prompt-mode plain; instruct/chat checkpoints should use their official tokenizer chat template when appropriate.",
                "The tokenizer chat-template hash is recorded when the tokenizer exposes a string template; adaptation details record whether enable_thinking=false was accepted or the tokenizer default path was used.",
                "Promotion-quality runs should use explicit --prompt-mode, --model-revision, --artifact-sha256, --quantization, --checkpoint-type and --benchmark-revision values, then pass validate-english-core-run.py --promotion."
            ],
        },
    }

    Path(args.result_file).write_text(json.dumps(result, indent=2) + "\n")
    print(f"done -> {args.result_file}")


if __name__ == "__main__":
    main()
