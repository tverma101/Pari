#!/usr/bin/env python3
"""Run a frozen Pari English Core JSONL screen with vLLM on CUDA.

This runner does inference only. It never opens lane answer files or invokes a
model-as-judge. Each completed chunk is atomically checkpointed to the result
JSON so an interrupted Kaggle session leaves recoverable work.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_TASKS = HERE / "english-core-fixed-screen.jsonl"
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str | None) -> str | None:
    return sha256_bytes(text.encode("utf-8")) if text else None


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def resolve_path(value: str | None) -> Path:
    if value is None:
        return DEFAULT_TASKS
    path = Path(value)
    if not path.is_absolute():
        local = HERE / path
        if local.exists():
            return local.resolve()
        path = Path.cwd() / path
    return path.resolve()


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def clean_generation(text: str) -> str:
    text = text.strip()
    if text.startswith("<think>"):
        close = text.find("</think>")
        if close >= 0:
            text = text[close + len("</think>") :].strip()
    return text


def prompt_for_task(tokenizer: Any, text: str, mode: str) -> tuple[str, str, str]:
    if mode == "plain":
        return text, "plain", "none"
    messages = [{"role": "user", "content": text}]
    try:
        try:
            prompt = tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            return prompt, "chat_template", "enable_thinking=false"
        except TypeError:
            prompt = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            return prompt, "chat_template", "template_default_no_enable_thinking_arg"
    except Exception:
        if mode == "chat":
            raise
        return text, "plain_fallback", "chat_template_failed"


def hash_hub_artifact_manifest(model_id: str, revision: str) -> tuple[str, str, list[dict[str, Any]]]:
    """Hash the pinned Hub file inventory and immutable blob identities.

    This is a reproducible artifact-manifest hash, not a bytewise hash of every
    model tensor. HF supplies immutable Git/LFS object identities for the pinned
    commit; those identities and file sizes bind this digest to the exact tree.
    """
    from huggingface_hub import HfApi

    info = HfApi().model_info(model_id, revision=revision, files_metadata=True)
    rows: list[dict[str, Any]] = []
    for sibling in info.siblings or []:
        lfs = getattr(sibling, "lfs", None)
        lfs_oid = getattr(lfs, "oid", None) if lfs else None
        blob_id = getattr(sibling, "blob_id", None) or getattr(sibling, "blobId", None)
        rows.append({
            "path": getattr(sibling, "rfilename", ""),
            "blobId": blob_id,
            "lfsSha256": lfs_oid,
            "size": getattr(sibling, "size", None),
        })
    rows.sort(key=lambda row: row["path"])
    payload = json.dumps(
        {"repo": model_id, "commit": info.sha, "files": rows},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return info.sha, sha256_bytes(payload), rows


def elapsed_metric(metrics: Any, start_field: str, end_field: str) -> float | None:
    if metrics is None:
        return None
    start = getattr(metrics, start_field, None)
    end = getattr(metrics, end_field, None)
    if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end >= start:
        return round(float(end - start), 6)
    return None


def hardware_record() -> dict[str, Any]:
    record: dict[str, Any] = {
        "machine": platform.machine(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "gpu": [],
    }
    try:
        import torch

        record["torchVersion"] = torch.__version__
        record["cudaVersion"] = torch.version.cuda
        if torch.cuda.is_available():
            for index in range(torch.cuda.device_count()):
                prop = torch.cuda.get_device_properties(index)
                record["gpu"].append({
                    "index": index,
                    "name": prop.name,
                    "totalMemoryBytes": int(prop.total_memory),
                    "computeCapability": f"{prop.major}.{prop.minor}",
                })
    except Exception as exc:
        record["gpuInspectionError"] = f"{type(exc).__name__}: {exc}"
    try:
        record["nvidiaSmi"] = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            text=True,
            stderr=subprocess.STDOUT,
            timeout=10,
        ).strip().splitlines()
    except Exception as exc:
        record["nvidiaSmiError"] = f"{type(exc).__name__}: {exc}"
    return record


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model", help="Hugging Face model repository ID")
    ap.add_argument("result_file", type=Path)
    ap.add_argument("--tasks", default=None)
    ap.add_argument("--revision", required=True, help="Immutable Hugging Face commit SHA")
    ap.add_argument("--benchmark-revision", required=True, help="Git commit containing the benchmark")
    ap.add_argument("--model-name", default=None)
    ap.add_argument("--checkpoint-type", choices=["base", "instruct", "chat", "specialized", "unknown"], default="instruct")
    ap.add_argument("--quantization", default="bf16", help="Explicit evaluated artifact quantization")
    ap.add_argument("--prompt-mode", choices=["chat", "plain"], required=True)
    ap.add_argument("--max-model-len", type=int, default=8192)
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.88)
    ap.add_argument("--tensor-parallel-size", type=int, default=1)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--max-tokens", type=int, default=220)
    ap.add_argument("--choice-max-tokens", type=int, default=8)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--top-p", type=float, default=1.0)
    ap.add_argument("--top-k", type=int, default=-1)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--limit", type=int, default=None, help="Smoke-test cap; capped runs are marked incomplete")
    ap.add_argument("--trust-remote-code", action="store_true")
    ap.add_argument("--dtype", choices=["auto", "half", "bfloat16"], default="half")
    ap.add_argument("--language-model-only", action="store_true", help="Skip unused multimodal towers for supported models")
    ap.add_argument("--speculative-method", choices=["mtp", "qwen3_next_mtp"], default=None)
    ap.add_argument("--speculative-tokens", type=int, default=1)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    if not re.fullmatch(r"[0-9a-fA-F]{40}", args.revision):
        raise SystemExit("--revision must be an immutable 40-character Hugging Face commit SHA")
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", args.benchmark_revision):
        raise SystemExit("--benchmark-revision must be a Git commit SHA")
    if args.batch_size < 1 or args.tensor_parallel_size < 1 or args.max_model_len < 512:
        raise SystemExit("batch size, tensor parallel size and max model length must be positive and reasonable")
    if not 0.1 <= args.gpu_memory_utilization <= 0.98:
        raise SystemExit("--gpu-memory-utilization must be in [0.1, 0.98]")
    if args.speculative_tokens < 1:
        raise SystemExit("--speculative-tokens must be >= 1")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be >= 1")

    result_path = args.result_file.resolve()
    if result_path.exists() and not args.overwrite:
        raise SystemExit(f"Refusing to overwrite existing result {result_path}; choose a new path or pass --overwrite")
    task_path = resolve_path(args.tasks)
    if not task_path.is_file():
        raise SystemExit(f"Missing task file: {task_path}. Build the requested task screen first.")
    task_bytes = task_path.read_bytes()
    tasks = [json.loads(line) for line in task_bytes.decode("utf-8").splitlines() if line.strip()]
    if args.limit is not None:
        tasks = tasks[: args.limit]
    ids = [task.get("id") for task in tasks]
    if not tasks or any(not value for value in ids) or len(ids) != len(set(ids)):
        raise SystemExit("Tasks must be non-empty and have unique, non-empty IDs")
    if any(not isinstance(task.get("prompt"), str) or not task["prompt"] for task in tasks):
        raise SystemExit("Every task must have a non-empty prompt")

    try:
        import torch
        from transformers import AutoTokenizer
        from vllm import LLM, SamplingParams
    except Exception as exc:
        raise SystemExit(f"Importing pinned inference dependencies failed: {type(exc).__name__}: {exc}") from exc
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is not available; this runner is CUDA-only and will not silently fall back to CPU")

    resolved_revision, artifact_hash, artifact_files = hash_hub_artifact_manifest(args.model, args.revision)
    tokenizer = AutoTokenizer.from_pretrained(
        args.model,
        revision=resolved_revision,
        trust_remote_code=args.trust_remote_code,
    )
    prompts: list[str] = []
    adaptations: set[str] = set()
    adaptation_details: set[str] = set()
    for task in tasks:
        prompt, adaptation, detail = prompt_for_task(tokenizer, task["prompt"], args.prompt_mode)
        prompts.append(prompt)
        adaptations.add(adaptation)
        adaptation_details.add(detail)

    speculative_config = None
    if args.speculative_method:
        speculative_config = {
            "method": args.speculative_method,
            "num_speculative_tokens": args.speculative_tokens,
        }
    llm_kwargs: dict[str, Any] = {
        "model": args.model,
        "revision": resolved_revision,
        "tokenizer": args.model,
        "tokenizer_revision": resolved_revision,
        "trust_remote_code": args.trust_remote_code,
        "dtype": args.dtype,
        "tensor_parallel_size": args.tensor_parallel_size,
        "max_model_len": args.max_model_len,
        "gpu_memory_utilization": args.gpu_memory_utilization,
        "seed": args.seed,
        "disable_log_stats": False,
    }
    if args.language_model_only:
        llm_kwargs["language_model_only"] = True
    if speculative_config is not None:
        llm_kwargs["speculative_config"] = speculative_config

    print(f"task_file={task_path} task_count={len(tasks)} sha256={sha256_bytes(task_bytes)}", flush=True)
    print(f"loading model={args.model} revision={resolved_revision} tp={args.tensor_parallel_size} speculative={speculative_config}", flush=True)
    load_started = time.monotonic()
    llm = LLM(**llm_kwargs)
    cold_load_seconds = time.monotonic() - load_started

    model_name = args.model_name or args.model.rsplit("/", 1)[-1]
    chat_template = getattr(tokenizer, "chat_template", None)
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    run = {
        "runId": f"english-core-{model_name}-{uuid.uuid4().hex[:8]}",
        "timestamp": created_at,
        "status": "running",
        "complete": False,
        "model": {
            "name": model_name,
            "repoOrName": args.model,
            "revision": resolved_revision,
            "artifactSha256": artifact_hash,
            "artifactIdentityType": "sha256_of_sorted_pinned_huggingface_blob_inventory",
            "artifactFiles": len(artifact_files),
            "quantization": args.quantization,
            "checkpointType": args.checkpoint_type,
            "runtime": "vllm",
            "runtimeVersion": package_version("vllm"),
            "tokenizerName": getattr(tokenizer, "name_or_path", args.model),
            "chatTemplate": "tokenizer.apply_chat_template" if "chat_template" in adaptations else "none/plain",
            "chatTemplateSha256": sha256_text(chat_template if isinstance(chat_template, str) else None),
        },
        "hardware": hardware_record(),
        "taskFile": str(task_path),
        "taskFileSha256": sha256_bytes(task_bytes),
        "taskCount": len(tasks),
        "sourceTaskCount": len([line for line in task_bytes.decode("utf-8").splitlines() if line.strip()]),
        "promptModeRequested": args.prompt_mode,
        "promptAdaptationModesObserved": sorted(adaptations),
        "promptAdaptationDetailsObserved": sorted(adaptation_details),
        "decoding": {
            "temperature": args.temperature,
            "topP": args.top_p,
            "topK": args.top_k,
            "maxNewTokens": args.max_tokens,
            "forcedChoiceMaxNewTokens": args.choice_max_tokens,
            "seed": args.seed,
            "batchSize": args.batch_size,
            "tensorParallelSize": args.tensor_parallel_size,
            "dtype": args.dtype,
            "languageModelOnly": args.language_model_only,
            "speculativeConfig": speculative_config,
        },
        "runtime": {
            "coldLoadSeconds": round(cold_load_seconds, 6),
            "cudaVisibleDevices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        },
        "outputs": [],
        "reproducibility": {
            "benchmarkRevision": args.benchmark_revision,
            "rawOutputSha256": None,
            "notes": [
                "artifactSha256 hashes the canonical inventory of immutable Hub blobs and file sizes at the resolved commit; it is not a second bytewise hash of every downloaded weight tensor.",
                "Run output contains no gold answers and this runner never opens answer-key files.",
                "Per-request TTFT and completion latency are taken from vLLM RequestOutput metrics when exposed by the installed version; unavailable values remain null.",
                "For a smoke run with --limit, taskCount is the attempted prefix and complete remains false; it cannot be promoted as the fixed screen.",
                "MTP is opt-in. An unsupported method/configuration fails explicitly; there is no silent fallback to ordinary decoding.",
            ],
        },
    }
    atomic_write_json(result_path, run)

    total_started = time.monotonic()
    sampling_batches = []
    for start in range(0, len(tasks), args.batch_size):
        stop = min(start + args.batch_size, len(tasks))
        batch_tasks = tasks[start:stop]
        batch_prompts = prompts[start:stop]
        sampling = [
            SamplingParams(
                temperature=args.temperature,
                top_p=args.top_p,
                top_k=args.top_k,
                max_tokens=args.max_tokens if task.get("generative") else args.choice_max_tokens,
                seed=args.seed,
            )
            for task in batch_tasks
        ]
        batch_started = time.monotonic()
        request_outputs = llm.generate(batch_prompts, sampling_params=sampling, use_tqdm=False)
        batch_wall = time.monotonic() - batch_started
        if len(request_outputs) != len(batch_tasks):
            raise RuntimeError(f"vLLM returned {len(request_outputs)} outputs for {len(batch_tasks)} inputs")
        for task, request_output in zip(batch_tasks, request_outputs, strict=True):
            generated = [clean_generation(choice.text) for choice in request_output.outputs]
            metrics = getattr(request_output, "metrics", None)
            row = {
                "id": task["id"],
                "output": generated[0] if generated else "",
                "latencySeconds": elapsed_metric(metrics, "arrival_time", "finished_time"),
                "firstTokenLatencySeconds": elapsed_metric(metrics, "arrival_time", "first_token_time"),
                "promptAdaptation": "chat_template" if args.prompt_mode == "chat" else "plain",
                "promptAdaptationDetail": next(iter(adaptation_details), "none"),
                "completionTokenCount": len(request_output.outputs[0].token_ids) if generated else 0,
            }
            if len(generated) > 1:
                row["alternatives"] = generated
            run["outputs"].append(row)
        sampling_batches.append(round(batch_wall, 6))
        run["completedCount"] = len(run["outputs"])
        run["runtime"]["wallSecondsSoFar"] = round(time.monotonic() - total_started, 6)
        run["runtime"]["lastBatchWallSeconds"] = round(batch_wall, 6)
        run["runtime"]["batchWallSeconds"] = sampling_batches
        atomic_write_json(result_path, run)
        print(f"completed {len(run['outputs'])}/{len(tasks)}; batch={batch_wall:.2f}s; checkpoint={result_path}", flush=True)

    outputs_canonical = json.dumps(run["outputs"], ensure_ascii=False, sort_keys=True).encode("utf-8")
    run["status"] = "completed" if len(run["outputs"]) == len(tasks) and args.limit is None else "incomplete"
    run["complete"] = run["status"] == "completed"
    run["completedCount"] = len(run["outputs"])
    run["runtime"]["totalWallSeconds"] = round(time.monotonic() - total_started, 6)
    run["reproducibility"]["rawOutputSha256"] = sha256_bytes(outputs_canonical)
    atomic_write_json(result_path, run)
    print(f"done status={run['status']} result={result_path} output_sha256={run['reproducibility']['rawOutputSha256']}", flush=True)


if __name__ == "__main__":
    main()
