"""Run a local Hugging Face encoder-decoder editor over a Pari corpus.

This runner is intentionally separate from the direct MLX causal-LM runner:
CoEdIT and ADAL are T5 checkpoints with different task prefixes and a
different runtime. It preserves raw outputs plus enough model/runtime receipt
data to make a v2 result replayable.

Usage:
    python benchmarks/llm-shootout/run_seq2seq.py \
      /tmp/pari-v2-coedit-large benchmarks/paraphrase-v2/results/coedit-large.raw.jsonl \
      --corpus benchmarks/paraphrase-v2/corpus.json \
      --prompt-prefix 'Paraphrase this:'
"""

import argparse
import json
import os
import platform
import resource
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = ROOT / "benchmarks/eval/corpus.json"


def resolve_path(value: str | None, default: Path) -> Path:
    if not value:
        return default
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate
    from_cwd = Path.cwd() / candidate
    if from_cwd.exists():
        return from_cwd.resolve()
    return (ROOT / candidate).resolve()


def load_corpus_data(corpus_arg: str | None) -> tuple[Path, dict | list]:
    path = resolve_path(corpus_arg, DEFAULT_CORPUS)
    return path, json.loads(path.read_text())


def process_peak_rss_gib() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if platform.system() != "Darwin":
        value *= 1024
    return round(value / 1024**3, 3)


def model_bytes(model_dir: Path) -> int:
    return sum(item.stat().st_size for item in model_dir.rglob("*") if item.is_file())


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    value = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return round(value, 3)


def token_count(tokenizer, text: str) -> int | None:
    try:
        return len(tokenizer.encode(text, add_special_tokens=False))
    except TypeError:
        try:
            return len(tokenizer.encode(text))
        except Exception:
            return None
    except Exception:
        return None


def render_prompt(prefix: str, text: str) -> str:
    normalized = prefix.strip()
    if not normalized:
        return text
    return f"{normalized} {text}"


def dtype_for(torch, requested: str, device: str):
    if requested == "auto":
        requested = "float16" if device == "mps" else "float32"
    return {
        "float16": torch.float16,
        "float32": torch.float32,
        "bfloat16": torch.bfloat16,
    }[requested]


def mps_peak_memory_gib(torch) -> float | None:
    if not hasattr(torch, "mps") or not torch.backends.mps.is_available():
        return None
    values = []
    for name in ("current_allocated_memory", "driver_allocated_memory"):
        getter = getattr(torch.mps, name, None)
        if getter is None:
            continue
        try:
            values.append(float(getter()))
        except Exception:
            continue
    return round(max(values) / 1024**3, 3) if values else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model_dir")
    parser.add_argument("out_file")
    parser.add_argument("--corpus", default=None)
    parser.add_argument("--prompt-prefix", default="Paraphrase this:")
    parser.add_argument("--max-input-tokens", type=int, default=512)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--num-beams", type=int, default=4)
    parser.add_argument("--device", choices=("auto", "mps", "cpu"), default="auto")
    parser.add_argument("--dtype", choices=("auto", "float16", "float32", "bfloat16"), default="auto")
    parser.add_argument("--do-sample", action="store_true")
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--temperature", type=float, default=0.9)
    parser.add_argument("--model-repo", default=None)
    parser.add_argument("--model-revision", default=None)
    parser.add_argument("--conversion-repo", default=None)
    parser.add_argument("--conversion-revision", default=None)
    parser.add_argument("--license", default="unknown")
    parser.add_argument("--quantization", default="fp16")
    parser.add_argument("--role", default="research-contender")
    parser.add_argument("--engine-name", default=None)
    parser.add_argument("--metadata-out", default=None)
    args = parser.parse_args()

    corpus_path, corpus_data = load_corpus_data(args.corpus)
    corpus = corpus_data["cases"] if isinstance(corpus_data, dict) and "cases" in corpus_data else corpus_data
    model_dir = Path(args.model_dir).expanduser().resolve()
    out_path = Path(args.out_file).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path = Path(args.metadata_out).expanduser().resolve() if args.metadata_out else Path(f"{out_path}.meta.json")

    if args.device == "auto":
        import torch
        device = "mps" if torch.backends.mps.is_available() else "cpu"
    else:
        import torch
        device = args.device
    if device == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("--device mps requested but the installed PyTorch build has no MPS backend")
    dtype = dtype_for(torch, args.dtype, device)

    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    print(f"corpus: {corpus_path} cases={len(corpus)}", flush=True)
    print(f"loading {model_dir} on {device} ({dtype}) ...", flush=True)
    load_started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
    load_kwargs = {"local_files_only": True, "low_cpu_mem_usage": True, "dtype": dtype}
    try:
        model = AutoModelForSeq2SeqLM.from_pretrained(str(model_dir), **load_kwargs)
    except TypeError:
        # Compatibility with older pinned Transformers releases.
        load_kwargs.pop("dtype", None)
        load_kwargs["torch_dtype"] = dtype
        model = AutoModelForSeq2SeqLM.from_pretrained(str(model_dir), **load_kwargs)
    model.to(device).eval()
    load_seconds = time.perf_counter() - load_started
    print(f"loaded in {load_seconds:.2f}s", flush=True)

    done_ids = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                try:
                    done_ids.add(json.loads(line)["id"])
                except (KeyError, json.JSONDecodeError):
                    continue

    case_seconds: list[float] = []
    completed = 0
    with out_path.open("a") as handle:
        for case in corpus:
            if case["id"] in done_ids:
                continue
            prompt = render_prompt(args.prompt_prefix, case["input"])
            encoded = tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=args.max_input_tokens,
            )
            encoded = {key: value.to(device) for key, value in encoded.items()}
            generation_kwargs = {
                "max_new_tokens": args.max_new_tokens,
                "num_beams": args.num_beams,
                "do_sample": args.do_sample,
            }
            if args.do_sample:
                generation_kwargs.update({"top_p": args.top_p, "temperature": args.temperature})
            started = time.perf_counter()
            row = {"id": case["id"], "output": ""}
            try:
                with torch.inference_mode():
                    generated = model.generate(**encoded, **generation_kwargs)
                elapsed = time.perf_counter() - started
                decoded = tokenizer.decode(generated[0], skip_special_tokens=True).strip()
                output_tokens = token_count(tokenizer, decoded)
                row.update({"output": decoded, "seconds": round(elapsed, 3)})
                if output_tokens is not None:
                    row["output_tokens"] = output_tokens
                    row["tokens_per_second"] = round(output_tokens / max(elapsed, 0.001), 2)
                prompt_tokens = token_count(tokenizer, prompt)
                if prompt_tokens is not None:
                    row["prompt_tokens"] = prompt_tokens
                case_seconds.append(elapsed)
                completed += 1
            except Exception as error:
                row.update({"seconds": round(time.perf_counter() - started, 3), "error": f"{type(error).__name__}: {error}"})
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            print(f"{case['id']:8s} {row['seconds']:5.1f}s  {row['output'][:90]}", flush=True)

    transformers_version = __import__("transformers").__version__
    torch_version = torch.__version__
    metadata = {
        "schemaVersion": 1,
        "benchmark": "pari-paraphrase-v2" if isinstance(corpus_data, dict) and corpus_data.get("version") == 2 else "pari-model-runner",
        "generatedAt": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "corpusPath": str(corpus_path),
        "corpusVersion": corpus_data.get("version") if isinstance(corpus_data, dict) else None,
        "caseCount": len(corpus),
        "productInstruction": corpus_data.get("defaultInstruction") if isinstance(corpus_data, dict) else None,
        "promptTemplate": f"{args.prompt_prefix.strip()} {{text}}" if args.prompt_prefix.strip() else "{text}",
        "engine": {
            "name": args.engine_name or args.model_repo or model_dir.name,
            "role": args.role,
            "modelRepo": args.model_repo,
            "revision": args.model_revision,
            "conversionRepo": args.conversion_repo,
            "conversionRevision": args.conversion_revision,
            "runtime": f"transformers {transformers_version} / torch {torch_version} / {device}",
            "license": args.license,
            "quantization": args.quantization,
            "modelPath": str(model_dir),
            "diskBytes": model_bytes(model_dir),
            "installedEvidence": False,
        },
        "settings": {
            "maxInputTokens": args.max_input_tokens,
            "maxNewTokens": args.max_new_tokens,
            "numBeams": args.num_beams,
            "doSample": args.do_sample,
            "topP": args.top_p if args.do_sample else None,
            "temperature": args.temperature if args.do_sample else None,
            "dtype": str(dtype),
            "device": device,
        },
        "hardware": {
            "platform": platform.platform(),
            "arch": platform.machine(),
            "macOS": platform.mac_ver()[0] or None,
            "totalMemoryGiB": round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3, 2),
        },
        "timing": {
            "loadSeconds": round(load_seconds, 3),
            "completedCases": completed,
            "totalSeconds": round(sum(case_seconds), 3),
            "medianCaseSeconds": median(case_seconds),
            "peakMpsMemoryGiB": mps_peak_memory_gib(torch),
            "peakProcessRssGiB": process_peak_rss_gib(),
        },
    }
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"done -> {out_path}", flush=True)
    print(f"metadata -> {metadata_path}", flush=True)


if __name__ == "__main__":
    main()
