#!/usr/bin/env python3
"""Run one candidate on a frozen Word Studio v2 task set and keep every raw output (#86).

    cd bench/word-studio
    python3 -m v2.run_candidate --candidate qwen35-4b --set screen --out /kaggle/working/runs/<run-id>/qwen35-4b

Rules this runner enforces:

- A model that fails to load, or a task that fails to generate, is recorded as
  failed with its error. Nothing is substituted: no fallback, "calibrated" or
  typed-in numbers. A failed run has no scores, only its error.
- Each task's raw completion is written to its own file with the rendered
  prompt, the decoding settings and the stream timeline.
- Latency per option is measured from the token stream, never estimated.
- This script writes no quality scores. Judging is separate (#87).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

HERE = Path(__file__).resolve().parent
WORD_STUDIO = HERE.parent
REPO_ROOT = WORD_STUDIO.parents[1]
CANDIDATE_FILES = (REPO_ROOT / "bench" / "candidates.json", HERE / "controls.json")

if str(WORD_STUDIO) not in sys.path:
    sys.path.insert(0, str(WORD_STUDIO))

from v2 import build_tasks, prompts  # noqa: E402
from word_studio_output_parser import partial_option_values  # noqa: E402

SCHEMA_VERSION = 1
PACKAGES = ("torch", "transformers", "accelerate", "tokenizers", "huggingface_hub", "safetensors")


class Backend(Protocol):
    def load(self) -> dict[str, Any]: ...

    def generate(self, messages: list[dict[str, str]], *, max_new_tokens: int, seed: int,
                 on_text: Callable[[str], None]) -> dict[str, Any]: ...

    def environment(self) -> dict[str, Any]: ...


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def task_seed(task_id: str) -> int:
    return int.from_bytes(hashlib.sha256(task_id.encode("utf-8")).digest()[:8], "big") % (2**63)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def error_record(exc: BaseException) -> dict[str, Any]:
    return {
        "type": type(exc).__name__,
        "message": str(exc)[:4000],
        "traceback": "".join(traceback.format_exception(exc))[-12000:],
    }


def find_candidate(candidate_id: str, files: Iterable[Path] = CANDIDATE_FILES) -> dict[str, Any]:
    for path in files:
        if not path.exists():
            continue
        for entry in json.loads(path.read_text(encoding="utf-8"))["candidates"]:
            if entry["candidate_id"] == candidate_id:
                return dict(entry, listed_in=str(path.relative_to(REPO_ROOT)))
    raise SystemExit(f"unknown candidate {candidate_id!r}; see bench/candidates.json and v2/controls.json")


def git_identity() -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout.strip()

    try:
        return {"sha": run("rev-parse", "HEAD"), "dirty_paths": run("status", "--porcelain").splitlines()}
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"sha": None, "error": str(exc)}


class StreamClock:
    """Timestamps the stream and the moment each option becomes complete."""

    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.text = ""
        self.chunks: list[list[float | int]] = []
        self.option_ms: list[float] = []

    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self.started) * 1000.0, 1)

    def on_text(self, chunk: str) -> None:
        if not chunk:
            return
        now = self.elapsed_ms()
        self.text += chunk
        self.chunks.append([now, len(self.text)])
        done, _mode = partial_option_values(self.text, include_visible_tail=False)
        while len(self.option_ms) < len(done):
            self.option_ms.append(now)

    def finish(self, final_text: str) -> dict[str, Any]:
        total = self.elapsed_ms()
        self.text = final_text
        done, _mode = partial_option_values(final_text, include_visible_tail=True)
        while len(self.option_ms) < len(done):
            self.option_ms.append(total)
        return {
            "first_text_ms": self.chunks[0][0] if self.chunks else None,
            "option_ms": self.option_ms,
            "total_ms": total,
            "stream": self.chunks,
            "note": "Milliseconds from the generate call. option_ms[i] is when option i+1 was complete in the stream; the last options may only complete at the end of the stream.",
        }


def run(candidate: dict[str, Any], set_name: str, out_dir: Path, backend: Backend,
        *, limit: int | None = None, log: Callable[[str], None] = print) -> dict[str, Any]:
    if (out_dir / "run.json").exists():
        raise SystemExit(f"{out_dir} already holds a run; never overwrite evidence")
    tasks = build_tasks.load_tasks(set_name)
    manifest_bytes = build_tasks.MANIFEST.read_bytes()
    manifest = json.loads(manifest_bytes)
    if limit is not None:
        tasks = tasks[:limit]
    run_record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "benchmark": manifest["benchmark"],
        "candidate": candidate,
        "task_set": set_name,
        "task_file_sha256": manifest["sets"][set_name]["sha256"],
        "manifest_sha256": build_tasks.sha256_bytes(manifest_bytes),
        "prompt_version": prompts.PROMPT_VERSION,
        "generation": prompts.GENERATION,
        "task_limit": limit,
        "tasks_planned": len(tasks),
        "repo": git_identity(),
        "status": "running",
        "stage": "load",
        "started_at": utc_now(),
        "finished_at": None,
        "load": None,
        "environment": None,
        "tasks": {"ok": 0, "error": 0, "failed_ids": []},
        "error": None,
        "scores": "none: this runner never scores; see v2/RUBRIC.md",
    }
    write_json(out_dir / "run.json", run_record)
    try:
        run_record["environment"] = backend.environment()
    except Exception as exc:  # environment capture must not hide a later load error
        run_record["environment"] = {"error": error_record(exc)}
    try:
        started = time.perf_counter()
        run_record["load"] = backend.load()
        run_record["load"]["load_seconds"] = round(time.perf_counter() - started, 2)
    except Exception as exc:
        run_record.update(status="failed", error=error_record(exc), finished_at=utc_now())
        write_json(out_dir / "run.json", run_record)
        log(f"[{candidate['candidate_id']}] FAILED to load: {type(exc).__name__}: {str(exc)[:300]}")
        return run_record
    run_record["stage"] = "generate"
    write_json(out_dir / "run.json", run_record)
    for number, task in enumerate(tasks, start=1):
        seed = task_seed(task["id"])
        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "task_id": task["id"],
            "kind": task["kind"],
            "candidate_id": candidate["candidate_id"],
            "messages_sha256": sha256_text(json.dumps(task["messages"], ensure_ascii=False, sort_keys=True)),
            "seed": seed,
            "max_new_tokens": task["max_new_tokens"],
        }
        clock = StreamClock()
        try:
            result = backend.generate(task["messages"], max_new_tokens=task["max_new_tokens"], seed=seed,
                                      on_text=clock.on_text)
            record.update(status="ok", raw_text=result["text"], timing=clock.finish(result["text"]),
                          rendered_prompt=result.get("rendered_prompt"), prompt_tokens=result.get("prompt_tokens"),
                          new_tokens=result.get("new_tokens"), finish_reason=result.get("finish_reason"),
                          error=None)
            run_record["tasks"]["ok"] += 1
        except Exception as exc:
            record.update(status="error", raw_text=clock.text or None, timing=clock.finish(clock.text),
                          error=error_record(exc))
            run_record["tasks"]["error"] += 1
            run_record["tasks"]["failed_ids"].append(task["id"])
        write_json(out_dir / "outputs" / f"{task['id']}.json", record)
        timing = record["timing"]
        log(f"[{candidate['candidate_id']}] {number}/{len(tasks)} {task['id']} {record['status']} "
            f"{timing['total_ms'] / 1000:.1f}s options_seen={len(timing['option_ms'])}")
        write_json(out_dir / "run.json", run_record)
    try:
        run_record["peak_memory"] = backend.environment().get("peak_memory")
    except Exception:
        pass
    complete = run_record["tasks"]["error"] == 0 and limit is None
    run_record.update(
        status="completed" if run_record["tasks"]["error"] == 0 else "failed",
        stage="done",
        finished_at=utc_now(),
        complete_set=complete,
    )
    if run_record["tasks"]["error"]:
        run_record["error"] = {"type": "TaskErrors", "message": f"{run_record['tasks']['error']} task(s) failed to generate"}
    write_json(out_dir / "run.json", run_record)
    return run_record


class TransformersBackend:
    """Hugging Face Transformers on CUDA. No remote code, no fallbacks."""

    #: Checkpoints below this size go on one T4; larger ones are split across both.
    SINGLE_GPU_BYTES = 11_000_000_000

    def __init__(self, model_id: str, revision: str, *, dtype: str = "float16",
                 weight_bytes: int | None = None) -> None:
        self.model_id, self.revision, self.dtype_name = model_id, revision, dtype
        self.weight_bytes = weight_bytes
        self.model = self.tokenizer = self.generation_config = None

    def environment(self) -> dict[str, Any]:
        from importlib import metadata

        packages = {}
        for name in PACKAGES:
            try:
                packages[name] = metadata.version(name)
            except metadata.PackageNotFoundError:
                packages[name] = None
        env: dict[str, Any] = {"python": sys.version, "platform": platform.platform(), "packages": packages}
        try:
            import torch

            env["cuda"] = torch.version.cuda
            env["gpus"] = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
            env["peak_memory"] = {f"cuda:{i}": torch.cuda.max_memory_allocated(i) for i in range(torch.cuda.device_count())}
        except Exception as exc:
            env["torch_error"] = str(exc)
        try:
            env["nvidia_smi"] = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=30).stdout.strip().splitlines()
        except (OSError, subprocess.SubprocessError):
            env["nvidia_smi"] = None
        return env

    def load(self) -> dict[str, Any]:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, GenerationConfig

        dtype = getattr(torch, self.dtype_name)
        single = self.weight_bytes is not None and self.weight_bytes < self.SINGLE_GPU_BYTES
        device_map: Any = {"": 0} if single else "auto"
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_id, revision=self.revision, trust_remote_code=False)
        self.model, info = AutoModelForCausalLM.from_pretrained(
            self.model_id, revision=self.revision, dtype=dtype, device_map=device_map, trust_remote_code=False,
            output_loading_info=True)
        # Randomly initialised weights would produce garbage that looks like the
        # model's own output. Treat any missing weight as a load failure.
        missing = sorted(info.get("missing_keys") or [])
        if missing:
            raise RuntimeError(f"{len(missing)} weights missing after load (first: {missing[:5]})")
        self.model.eval()
        base = self.model.generation_config
        pad = self.tokenizer.pad_token_id if self.tokenizer.pad_token_id is not None else base.eos_token_id
        if isinstance(pad, list):
            pad = pad[0]
        g = prompts.GENERATION
        self.generation_config = GenerationConfig(
            do_sample=g["do_sample"], temperature=g["temperature"], top_p=g["top_p"], top_k=g["top_k"],
            repetition_penalty=g["repetition_penalty"], eos_token_id=base.eos_token_id, pad_token_id=pad,
            bos_token_id=base.bos_token_id)
        placed = getattr(self.model, "hf_device_map", None) or {}
        return {
            "model_class": type(self.model).__name__,
            "dtype": self.dtype_name,
            "device_map": "single T4 (cuda:0)" if single else "auto across both T4s",
            "devices": sorted({str(v) for v in placed.values()}),
            "unexpected_keys": len(info.get("unexpected_keys") or []),
            "parameters": sum(p.numel() for p in self.model.parameters()),
            "generation_config": self.generation_config.to_dict(),
            "chat_template_sha256": sha256_text(self.tokenizer.chat_template or ""),
        }

    def generate(self, messages: list[dict[str, str]], *, max_new_tokens: int, seed: int,
                 on_text: Callable[[str], None]) -> dict[str, Any]:
        import torch
        from transformers import TextIteratorStreamer

        tok = self.tokenizer
        rendered = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        inputs = tok.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, enable_thinking=False,
                                         return_tensors="pt", return_dict=True)
        inputs = {k: v.to(self.model.device) for k, v in inputs.items()}
        prompt_tokens = int(inputs["input_ids"].shape[1])
        streamer = TextIteratorStreamer(tok, skip_prompt=True, skip_special_tokens=True, timeout=900)
        holder: dict[str, Any] = {}

        def work() -> None:
            try:
                torch.manual_seed(seed)
                with torch.inference_mode():
                    holder["ids"] = self.model.generate(**inputs, generation_config=self.generation_config,
                                                        max_new_tokens=max_new_tokens, streamer=streamer)
            except BaseException as exc:  # re-raised on the caller's thread
                holder["error"] = exc
                streamer.end()

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        for piece in streamer:
            on_text(piece)
        thread.join()
        if "error" in holder:
            raise holder["error"]
        new_ids = holder["ids"][0, prompt_tokens:]
        text = tok.decode(new_ids, skip_special_tokens=True)
        new_tokens = int(new_ids.shape[0])
        return {
            "text": text,
            "rendered_prompt": rendered,
            "prompt_tokens": prompt_tokens,
            "new_tokens": new_tokens,
            "finish_reason": "length" if new_tokens >= max_new_tokens else "stop",
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--set", choices=sorted(build_tasks.SET_FILES), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dtype", default="float16", help="T4 has no bfloat16; float16 is the default")
    parser.add_argument("--limit", type=int, help="first N tasks only, for smoke tests; the run is marked partial")
    args = parser.parse_args(argv)
    candidate = find_candidate(args.candidate)
    backend = TransformersBackend(candidate["model_id"], candidate["revision"], dtype=args.dtype,
                                  weight_bytes=candidate.get("upstream_weight_files_bytes"))
    record = run(candidate, args.set, args.out, backend, limit=args.limit)
    print(json.dumps({"candidate": args.candidate, "status": record["status"], "tasks": record["tasks"]}))
    return 0 if record["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
