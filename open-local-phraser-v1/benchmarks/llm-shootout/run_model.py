"""Run a local MLX model over the adversarial eval corpus.

Writes JSONL {"id", "output"} lines compatible with:
    node benchmarks/eval/run-eval.mjs --outputs <file>

Usage:
    python benchmarks/llm-shootout/run_model.py <model_dir> <out.jsonl> [--max-tokens 220]
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


def load_corpus_data(corpus_arg: str | None) -> dict | list:
    p = Path(corpus_arg) if corpus_arg else DEFAULT_CORPUS
    if not p.is_absolute():
        cand = Path.cwd() / p
        p = cand if cand.exists() else (ROOT / p).resolve() if not p.exists() else p.resolve()
        if not p.exists() and corpus_arg:
            p = (ROOT / corpus_arg).resolve()
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


def token_count(tokenizer, text: str) -> int | None:
    try:
        try:
            return len(tokenizer.encode(text, add_special_tokens=False))
        except TypeError:
            return len(tokenizer.encode(text))
    except Exception:
        return None


def render_prompt(corpus_data: dict | list, text: str) -> str:
    if isinstance(corpus_data, dict) and isinstance(corpus_data.get("defaultInstruction"), str):
        return f"{corpus_data['defaultInstruction'].strip()}\n\nText: {text}\n\nRewritten:"
    return PROMPT.format(text=text)


def model_bytes(model_dir: Path) -> int:
    return sum(item.stat().st_size for item in model_dir.rglob("*") if item.is_file())


def process_peak_rss_gib() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if platform.system() != "Darwin":
        value *= 1024
    return round(value / 1024**3, 3)


def median(values: list[float]) -> float | None:
    if not values:
        return None
    values = sorted(values)
    middle = len(values) // 2
    value = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
    return round(value, 3)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("model_dir")
    ap.add_argument("out_file")
    ap.add_argument("--corpus", default=None, help="Corpus JSON path (default: benchmarks/eval/corpus.json). For QuillBot frozen use benchmarks/quillbot/corpus.frozen.json")
    ap.add_argument("--max-tokens", type=int, default=220)
    ap.add_argument("--model-repo", default=None)
    ap.add_argument("--model-revision", default=None)
    ap.add_argument("--conversion-repo", default=None)
    ap.add_argument("--conversion-revision", default=None)
    ap.add_argument("--license", default="unknown")
    ap.add_argument("--quantization", default="unknown")
    ap.add_argument("--role", default="unclassified")
    ap.add_argument("--engine-name", default=None)
    ap.add_argument("--metadata-out", default=None)
    args = ap.parse_args()
    corpus_data = load_corpus_data(args.corpus)
    corpus = corpus_data["cases"] if isinstance(corpus_data, dict) and "cases" in corpus_data else corpus_data
    print(f"corpus: {args.corpus or str(DEFAULT_CORPUS)} cases={len(corpus)}", flush=True)

    from mlx_lm import load
    from mlx_lm.generate import generate
    from mlx_lm.sample_utils import make_sampler
    try:
        import mlx.core as mx
    except ImportError:
        mx = None

    print(f"loading {args.model_dir} ...", flush=True)
    model_dir = Path(args.model_dir).expanduser().resolve()
    load_started = time.time()
    model, tokenizer = load(str(model_dir))
    load_seconds = time.time() - load_started
    print(f"loaded in {load_seconds:.1f}s", flush=True)

    sampler = make_sampler(temp=0.0)
    out_path = Path(args.out_file)
    done_ids = set()
    if out_path.exists():  # resume support
        for line in out_path.read_text().splitlines():
            if line.strip():
                done_ids.add(json.loads(line)["id"])

    case_seconds: list[float] = []
    with out_path.open("a") as fh:
        for case in corpus:
            if case["id"] in done_ids:
                continue
            messages = [{"role": "user", "content": render_prompt(corpus_data, case["input"])}]
            prompt_ids = tokenizer.apply_chat_template(
                messages, add_generation_prompt=True, enable_thinking=False
            )
            t0 = time.time()
            out = generate(model, tokenizer, prompt=prompt_ids, max_tokens=args.max_tokens, sampler=sampler)
            dt = time.time() - t0
            case_seconds.append(dt)
            text = strip_think(out)
            # The model must never echo meta instructions back.
            if "Text:" in text or "Rewritten" in text.split("\n")[0]:
                text = ""
            output_tokens = token_count(tokenizer, text)
            row = {"id": case["id"], "output": text, "seconds": round(dt, 2)}
            if output_tokens is not None:
                row["output_tokens"] = output_tokens
                row["tokens_per_second"] = round(output_tokens / max(dt, 0.001), 2)
            try:
                row["prompt_tokens"] = len(prompt_ids)
            except TypeError:
                pass
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            print(f"{case['id']:8s} {dt:5.1f}s  {text[:90]}", flush=True)

    print(f"done -> {out_path}")
    metadata_path = Path(args.metadata_out) if args.metadata_out else Path(f"{out_path}.meta.json")
    peak_metal = None
    if mx is not None:
        try:
            peak_metal = round(float(mx.metal.get_peak_memory()) / 1024**3, 3)
        except Exception:
            pass
    metadata = {
        "schemaVersion": 1,
        "benchmark": "pari-paraphrase-v2" if isinstance(corpus_data, dict) and corpus_data.get("version") == 2 else "pari-model-runner",
        "generatedAt": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "corpusPath": str(Path(args.corpus).expanduser().resolve()) if args.corpus else str(DEFAULT_CORPUS),
        "corpusVersion": corpus_data.get("version") if isinstance(corpus_data, dict) else None,
        "caseCount": len(corpus),
        "productInstruction": corpus_data.get("defaultInstruction") if isinstance(corpus_data, dict) else None,
        "engine": {
            "name": args.engine_name or args.model_repo or model_dir.name,
            "role": args.role,
            "modelRepo": args.model_repo,
            "revision": args.model_revision,
            "conversionRepo": args.conversion_repo,
            "conversionRevision": args.conversion_revision,
            "runtime": "mlx-lm",
            "license": args.license,
            "quantization": args.quantization,
            "modelPath": str(model_dir),
            "diskBytes": model_bytes(model_dir),
            "installedEvidence": False,
        },
        "settings": {"maxTokens": args.max_tokens, "temperature": 0.0, "thinking": False},
        "hardware": {
            "platform": platform.platform(),
            "arch": platform.machine(),
            "macOS": platform.mac_ver()[0] or None,
            "totalMemoryGiB": round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3, 2),
        },
        "timing": {
            "loadSeconds": round(load_seconds, 3),
            "completedCases": len(case_seconds),
            "totalSeconds": round(sum(case_seconds), 3),
            "medianCaseSeconds": median(case_seconds),
            "peakMetalMemoryGiB": peak_metal,
            "peakProcessRssGiB": process_peak_rss_gib(),
        },
    }
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"metadata -> {metadata_path}")


if __name__ == "__main__":
    main()
