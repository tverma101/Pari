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
import contextlib
import copy
import hashlib
import json
import os
import platform
import queue
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Protocol

HERE = Path(__file__).resolve().parent
WORD_STUDIO = HERE.parent
REPO_ROOT = WORD_STUDIO.parents[1]
CANDIDATE_FILES = (REPO_ROOT / "bench" / "candidates.json", HERE / "controls.json")

if str(WORD_STUDIO) not in sys.path:
    sys.path.insert(0, str(WORD_STUDIO))

from v2 import build_tasks, prompts  # noqa: E402
from word_studio_output_parser import partial_option_values  # noqa: E402

SCHEMA_VERSION = 1
PACKAGES = ("torch", "transformers", "accelerate", "tokenizers", "huggingface_hub", "safetensors", "gptqmodel")


class Backend(Protocol):
    def load(self) -> dict[str, Any]: ...

    def generate(self, messages: list[dict[str, str]], *, max_new_tokens: int, seed: int,
                 on_text: Callable[..., None]) -> dict[str, Any]: ...

    def environment(self) -> dict[str, Any]: ...


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def messages_digest(messages: list[dict[str, str]]) -> str:
    return sha256_text(json.dumps(messages, ensure_ascii=False, sort_keys=True))


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

    def elapsed_ms(self, at: float | None = None) -> float:
        return round(((time.perf_counter() if at is None else at) - self.started) * 1000.0, 1)

    def on_text(self, chunk: str, at: float | None = None) -> None:
        """Record ``chunk``; ``at`` is the ``perf_counter()`` time its token arrived, if known."""
        if not chunk:
            return
        now = self.elapsed_ms(at)
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
            "note": "Milliseconds from the generate call, timed per generated token. option_ms[i] is when option i+1 was complete in the stream; an option the parser can only close at the end of the output gets total_ms.",
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
            "messages_sha256": messages_digest(task["messages"]),
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


class TokenStreamer:
    """Releases decoded text on every generated token, stamped with when it arrived.

    Transformers' ``TextIteratorStreamer`` only releases text at a space or a
    newline, so a model that writes compact JSON would seem to produce every
    option at the very end. This streamer holds back only an incomplete
    character. ``generate`` calls ``put`` with the prompt first, then with each
    new token, then ``end``.
    """

    def __init__(self, decode: Callable[[list[int]], str], *, timeout: float) -> None:
        self.decode = decode
        self.timeout = timeout
        self.ids: list[int] = []
        self.released = 0
        self.prompt_seen = False
        self.stop = threading.Event()
        self._queue: queue.Queue = queue.Queue()

    def _release(self) -> None:
        text = self.decode(self.ids)
        if len(text) > self.released and not text.endswith("\ufffd"):
            self._queue.put((time.perf_counter(), text[self.released:]))
            self.released = len(text)

    def put(self, value: Any) -> None:
        ids = value.tolist() if hasattr(value, "tolist") else list(value)
        if ids and isinstance(ids[0], list):
            if len(ids) != 1:
                raise ValueError("TokenStreamer streams one sequence at a time")
            ids = ids[0]
        if not self.prompt_seen:
            self.prompt_seen = True
            return
        self.ids.extend(int(i) for i in ids)
        self._release()

    def end(self) -> None:
        text = self.decode(self.ids)
        if len(text) > self.released:
            self._queue.put((time.perf_counter(), text[self.released:]))
            self.released = len(text)
        self._queue.put(None)

    def __iter__(self):
        while True:
            item = self._queue.get(timeout=self.timeout)
            if item is None:
                return
            yield item


class TransformersBackend:
    """Hugging Face Transformers on CUDA. No remote code, no fallbacks."""

    #: Checkpoints below this size go on one T4; larger ones are split across both.
    SINGLE_GPU_BYTES = 11_000_000_000

    def __init__(self, model_id: str, revision: str, *, dtype: str = "float16",
                 weight_bytes: int | None = None) -> None:
        self.model_id, self.revision, self.dtype_name = model_id, revision, dtype
        self.weight_bytes = weight_bytes
        self.model = self.tokenizer = self.generation_config = None
        #: Set when a generation could not be stopped; later tasks are refused, not run on a busy model.
        self.wedged: str | None = None

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
            env["host_ram_bytes"] = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        except (AttributeError, OSError, ValueError):
            env["host_ram_bytes"] = None
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
        from transformers import AutoTokenizer, GenerationConfig

        dtype = getattr(torch, self.dtype_name)
        single = self.weight_bytes is not None and self.weight_bytes < self.SINGLE_GPU_BYTES
        device_map: Any = {"": 0} if single else "auto"
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_id, revision=self.revision, trust_remote_code=False)
        self.model, missing, unexpected, extra = self.load_weights(dtype, device_map)
        # Randomly initialised weights would produce garbage that looks like the
        # model's own output. Treat any missing weight as a load failure.
        if missing:
            raise RuntimeError(f"{len(missing)} weights missing after load (first: {missing[:5]})")
        # A model that spills onto the CPU is not served by the T4s, and its timings would mislead.
        devices = sorted({str(t.device) for t in self.model.state_dict().values()})
        offloaded = [d for d in devices if not d.startswith("cuda")]
        if offloaded:
            raise RuntimeError(f"weights placed off the GPUs ({offloaded}); the model does not fit 2xT4")
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
        # One untimed generation first, so CUDA start-up is not charged to the first task.
        started = time.perf_counter()
        self.generate([{"role": "user", "content": "Reply with OK."}], max_new_tokens=8, seed=0,
                      on_text=lambda *_: None)
        warmup_seconds = round(time.perf_counter() - started, 2)
        return {
            "warmup_seconds": warmup_seconds,
            "model_class": type(self.model).__name__,
            "dtype": self.dtype_name,
            "device_map": "single T4 (cuda:0)" if single else "auto across both T4s",
            "devices": devices,
            "unexpected_keys": unexpected,
            "parameters": sum(p.numel() for p in self.model.parameters()),
            "generation_config": self.generation_config.to_dict(),
            "chat_template_sha256": sha256_text(self.tokenizer.chat_template or ""),
            **extra,
        }

    def load_weights(self, dtype: Any, device_map: Any) -> tuple[Any, list[str], int, dict[str, Any]]:
        """Return the model, the weights the checkpoint did not fill, the unused checkpoint count, extra load info."""
        from transformers import AutoModelForCausalLM

        model, info = AutoModelForCausalLM.from_pretrained(
            self.model_id, revision=self.revision, dtype=dtype, device_map=device_map, trust_remote_code=False,
            output_loading_info=True)
        return model, sorted(info.get("missing_keys") or []), len(info.get("unexpected_keys") or []), {}


def checkpoint_coverage(model_names: Iterable[str], stored_names: Iterable[str], *,
                        kernel_buffers: tuple[str, ...] = (), unused_prefixes: tuple[str, ...] = ()
                        ) -> tuple[list[str], list[str]]:
    """Model weights the checkpoint does not hold, and checkpoint tensors the model has no slot for."""
    model_names, stored_names = set(model_names), set(stored_names)
    missing = sorted(n for n in model_names - stored_names if not n.endswith(kernel_buffers))
    unused = sorted(n for n in stored_names - model_names if not n.startswith(unused_prefixes))
    return missing, unused


@contextlib.contextmanager
def lazy_expert_shells() -> Iterator[None]:
    """Split fused MoE experts without copying their placeholder values.

    GPTQModel builds the float model on the CPU before swapping in the quantized
    layers. Defuser splits each fused expert tensor into per-expert Linear layers
    by copying it, which makes those never-initialised values resident: tens of
    GB for a 35B MoE, more than Kaggle's host RAM (run
    2026-10-22T1846Z-screen-94c5fca-limit2 was killed there). Here the split
    happens on the meta device and each Linear gets an untouched CPU tensor
    instead. The quantized layers replace them, and the coverage check still
    fails the load if any is left unfilled.
    """
    import torch
    from defuser.modeling import moe_experts_interface as experts

    original = experts._unfuse_single_projection

    def split(module, proj_name, *args, **kwargs):
        fused = experts._get_registered_tensor(module, proj_name)
        on_cpu = fused is not None and fused.device.type == "cpu"
        if on_cpu:
            experts._set_registered_tensor_like(module, proj_name, torch.empty_like(fused, device="meta"), fused)
        linears = original(module, proj_name, *args, **kwargs)
        for linear in (linears or []) if on_cpu else []:
            for name, param in list(linear.named_parameters(recurse=False)):
                setattr(linear, name, torch.nn.Parameter(torch.empty_like(param, device="cpu"),
                                                         requires_grad=False))
        return linears

    experts._unfuse_single_projection = split
    try:
        yield
    finally:
        experts._unfuse_single_projection = original


class GPTQModelBackend(TransformersBackend):
    """A GPTQ checkpoint loaded by GPTQModel, which splits the fused MoE experts Transformers would leave empty.

    GPTQModel loads through accelerate without a strict check, so the model's
    weight names are compared with the checkpoint index here instead.
    """

    #: Buffers the GPTQ kernels add after loading; they are not checkpoint weights.
    KERNEL_BUFFERS = ("g_idx_sort_indices", "workspace")
    #: Checkpoint tensors generation never uses: the multi-token-prediction head.
    UNUSED_PREFIXES = ("mtp.",)
    #: GPTQModel 7.5.0 picks Marlin, whose sm75 build fails on the T4 (run
    #: 2026-10-22T1859Z-screen-ac3f270-limit2); ExLlamaV2 compiled there.
    KERNEL = "gptq_exllama_v2"

    def load_weights(self, dtype: Any, device_map: Any) -> tuple[Any, list[str], int, dict[str, Any]]:
        from gptqmodel import GPTQModel
        from huggingface_hub import hf_hub_download

        with lazy_expert_shells():
            wrapped = GPTQModel.load(self.model_id, revision=self.revision, device_map=device_map, dtype=dtype,
                                     backend=self.KERNEL, trust_remote_code=False)
        model = wrapped.model
        index = hf_hub_download(self.model_id, "model.safetensors.index.json", revision=self.revision)
        stored = json.loads(Path(index).read_text(encoding="utf-8"))["weight_map"]
        missing, unused = checkpoint_coverage(model.state_dict(), stored, kernel_buffers=self.KERNEL_BUFFERS,
                                              unused_prefixes=self.UNUSED_PREFIXES)
        kernels = sorted({type(m).__name__ for m in model.modules()
                          if type(m).__module__.startswith("gptqmodel.nn_modules.qlinear")})
        return model, missing, len(unused), {"loader": "gptqmodel", "quant_kernels": kernels}

    def generate(self, messages: list[dict[str, str]], *, max_new_tokens: int, seed: int,
                 on_text: Callable[..., None]) -> dict[str, Any]:
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList

        if self.wedged:
            raise RuntimeError(f"not run: an earlier generation never stopped ({self.wedged}), so the model is busy")
        tok = self.tokenizer
        rendered = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        inputs = tok.apply_chat_template(messages, tokenize=True, add_generation_prompt=True, enable_thinking=False,
                                         return_tensors="pt", return_dict=True)
        inputs = {k: v.to(self.model.device) for k, v in inputs.items()}
        prompt_tokens = int(inputs["input_ids"].shape[1])
        streamer = TokenStreamer(lambda ids: tok.decode(ids, skip_special_tokens=True), timeout=900)

        class StopWhenAsked(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return torch.full((input_ids.shape[0],), streamer.stop.is_set(), dtype=torch.bool,
                                  device=input_ids.device)

        config = copy.deepcopy(self.generation_config)
        config.max_new_tokens = max_new_tokens
        holder: dict[str, Any] = {}

        def work() -> None:
            try:
                torch.manual_seed(seed)
                with torch.inference_mode():
                    holder["ids"] = self.model.generate(
                        **inputs, generation_config=config, streamer=streamer,
                        stopping_criteria=StoppingCriteriaList([StopWhenAsked()]))
            except BaseException as exc:  # re-raised on the caller's thread
                holder["error"] = exc
                streamer.end()

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        try:
            for at, piece in streamer:
                on_text(piece, at)
        except BaseException as exc:
            streamer.stop.set()
            thread.join(timeout=300)
            if thread.is_alive():
                self.wedged = f"{type(exc).__name__} while streaming"
            raise
        thread.join()
        if "error" in holder:
            raise holder["error"]
        new_ids = holder["ids"][0, prompt_tokens:]
        text = tok.decode(new_ids, skip_special_tokens=True)
        new_tokens = int(new_ids.shape[0])
        eos = self.generation_config.eos_token_id
        eos_ids = {i for i in (eos if isinstance(eos, list) else [eos]) if i is not None}
        if new_tokens and int(new_ids[-1]) in eos_ids:
            finish = "stop"
        elif new_tokens >= max_new_tokens:
            finish = "length"
        else:
            finish = "stop"
        return {
            "text": text,
            "rendered_prompt": rendered,
            "prompt_tokens": prompt_tokens,
            "new_tokens": new_tokens,
            "finish_reason": finish,
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
    gptq = str(candidate.get("quantization", "")).startswith("GPTQ")
    backend = (GPTQModelBackend if gptq else TransformersBackend)(
        candidate["model_id"], candidate["revision"], dtype=args.dtype,
        weight_bytes=candidate.get("upstream_weight_files_bytes"))
    record = run(candidate, args.set, args.out, backend, limit=args.limit)
    print(json.dumps({"candidate": args.candidate, "status": record["status"], "tasks": record["tasks"]}))
    return 0 if record["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
