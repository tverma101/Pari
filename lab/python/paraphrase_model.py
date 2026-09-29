#!/usr/bin/env python3
"""
Paraphrase model runner for T5/BART models.
Communicates with the TypeScript backend via stdin/stdout JSON.

Usage:
  python3 paraphrase_model.py --model humarin/chatgpt_paraphraser_on_T5_base --input "sentence to rewrite"
  python3 paraphrase_model.py --model Vamsi/T5_Paraphrase_Paws --input "sentence to rewrite"
  python3 paraphrase_model.py --model eugenesiow/bart-paraphrase --input "sentence to rewrite"
  python3 paraphrase_model.py --model humarin/chatgpt_paraphraser_on_T5_base --batch-input '["s1","s2","s3"]'
  python3 paraphrase_model.py --model humarin/chatgpt_paraphraser_on_T5_base --download-only
  python3 paraphrase_model.py --model humarin/chatgpt_paraphraser_on_T5_base --benchmark
  python3 paraphrase_model.py --list-models

Generation modes:
  --num-beams 5 --num-sequences 3 --do-sample --temperature 1.0
  Lanes: --lane conservative (beams, no sampling), natural (sampling), structure (more change), cleanup (light)
"""

import argparse
import json
import sys
import time
import os
import tempfile
from typing import List, Optional

# Suppress non-critical logs
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

AVAILABLE_MODELS = {
    "humarin/chatgpt_paraphraser_on_T5_base": {
        "name": "ChatGPT Paraphraser T5 Base",
        "type": "t5",
        "description": "Fine-tuned T5 for paraphrasing — good for conservative/natural lanes",
        "size_mb": 850,
    },
    "Vamsi/T5_Paraphrase_Paws": {
        "name": "T5 Paraphrase PAWS",
        "type": "t5",
        "description": "T5 fine-tuned on PAWS — good for structure-preserving paraphrases",
        "size_mb": 850,
    },
    "eugenesiow/bart-paraphrase": {
        "name": "BART Paraphrase",
        "type": "bart",
        "description": "BART fine-tuned for paraphrasing — good for natural/structure lanes",
        "size_mb": 1500,
    },
}

# Default generation settings per lane
LANE_SETTINGS = {
    "conservative": {
        "num_beams": 5,
        "num_return_sequences": 3,
        "do_sample": False,
        "temperature": 1.0,
        "top_k": 50,
        "top_p": 0.95,
        "repetition_penalty": 1.0,
        "max_length": 128,
        "min_length": 5,
    },
    "natural": {
        "num_beams": 3,
        "num_return_sequences": 3,
        "do_sample": True,
        "temperature": 0.8,
        "top_k": 50,
        "top_p": 0.90,
        "repetition_penalty": 1.1,
        "max_length": 128,
        "min_length": 5,
    },
    "structure": {
        "num_beams": 2,
        "num_return_sequences": 3,
        "do_sample": True,
        "temperature": 1.2,
        "top_k": 80,
        "top_p": 0.95,
        "repetition_penalty": 1.2,
        "max_length": 150,
        "min_length": 5,
    },
    "cleanup": {
        "num_beams": 4,
        "num_return_sequences": 2,
        "do_sample": False,
        "temperature": 0.5,
        "top_k": 30,
        "top_p": 0.85,
        "repetition_penalty": 1.0,
        "max_length": 128,
        "min_length": 5,
    },
}


def load_model(model_name: str, device: str = "auto"):
    """Load a T5 or BART model for paraphrasing."""
    from transformers import (
        AutoTokenizer,
        AutoModelForSeq2SeqLM,
    )

    print(f"Loading {model_name}...", file=sys.stderr)
    t0 = time.time()

    try:
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSeq2SeqLM.from_pretrained(model_name)

        # Move to available device
        if device == "auto":
            if torch.cuda.is_available():
                device = "cuda"
            elif torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"

        if device != "cpu":
            model = model.to(device)

        load_time = time.time() - t0
        print(f"Loaded in {load_time:.2f}s on {device}", file=sys.stderr)

        return model, tokenizer, device, load_time

    except Exception as e:
        print(f"Error loading model {model_name}: {e}", file=sys.stderr)
        return None, None, None, 0


def generate_paraphrases(
    model,
    tokenizer,
    text: str,
    settings: dict,
) -> List[str]:
    """Generate paraphrases for a single text using model.generate()."""
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)

    # Move inputs to the same device as model
    device = model.device
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            num_beams=settings["num_beams"],
            num_return_sequences=settings["num_return_sequences"],
            do_sample=settings["do_sample"],
            temperature=settings["temperature"],
            top_k=settings["top_k"],
            top_p=settings["top_p"],
            repetition_penalty=settings["repetition_penalty"],
            max_length=settings["max_length"],
            min_length=settings["min_length"],
        )

    results = tokenizer.batch_decode(outputs, skip_special_tokens=True)
    return results


def download_only(model_name: str):
    """Download model without running inference."""
    print(f"Downloading {model_name}...", file=sys.stderr)
    t0 = time.time()

    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSeq2SeqLM.from_pretrained(model_name)

    elapsed = time.time() - t0
    print(f"Downloaded {model_name} in {elapsed:.1f}s", file=sys.stderr)
    print(f"Model saved to cache", file=sys.stderr)

    return {"status": "downloaded", "model": model_name, "time_seconds": round(elapsed, 2)}


def run_benchmark(model_name: str):
    """Run quick timing benchmark on the model."""
    model, tokenizer, device, load_time = load_model(model_name)
    if model is None:
        return {"error": f"Failed to load {model_name}"}

    test_sentences = [
        "I think communication matters because it helps people understand each other better.",
        "The boy who the girl helped thanked the teacher.",
        "This demonstrates the significant role of communication in how individuals understand themselves.",
    ]

    results = []
    for sentence in test_sentences:
        times = []
        candidates_list = []
        for _ in range(3):
            t0 = time.time()
            gens = generate_paraphrases(model, tokenizer, sentence, LANE_SETTINGS["natural"])
            elapsed = time.time() - t0
            times.append(elapsed)
            candidates_list.append(gens)

        avg_time = sum(times) / len(times)
        results.append({
            "input": sentence[:60],
            "avg_generation_time_ms": round(avg_time * 1000, 2),
            "candidates": candidates_list[-1],
            "device": device,
        })

    return {
        "model": model_name,
        "device": device,
        "load_time_ms": round(load_time * 1000, 2),
        "sentences": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Local paraphrase model runner")
    parser.add_argument("--model", type=str, default="humarin/chatgpt_paraphraser_on_T5_base",
                        help="HuggingFace model name")
    parser.add_argument("--input", type=str, help="Single sentence to paraphrase")
    parser.add_argument("--batch-input", type=str, help="JSON array of sentences")
    parser.add_argument("--lane", type=str, default="natural",
                        choices=list(LANE_SETTINGS.keys()),
                        help="Generation lane (conservative/natural/structure/cleanup)")
    parser.add_argument("--num-beams", type=int, help="Override num beams")
    parser.add_argument("--num-sequences", type=int, help="Override num return sequences")
    parser.add_argument("--do-sample", action="store_true", help="Enable sampling")
    parser.add_argument("--temperature", type=float, help="Override temperature")
    parser.add_argument("--download-only", action="store_true", help="Only download the model")
    parser.add_argument("--benchmark", action="store_true", help="Run model benchmark")
    parser.add_argument("--list-models", action="store_true", help="List available models")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--device", type=str, default="auto", help="Device: auto/cpu/cuda/mps")
    parser.add_argument("--warmup", action="store_true", help="Run warmup inference after loading")

    args = parser.parse_args()

    if args.list_models:
        models_info = {}
        for mid, info in AVAILABLE_MODELS.items():
            models_info[mid] = info
        print(json.dumps(models_info, indent=2))
        return

    # Download-only mode
    if args.download_only:
        result = download_only(args.model)
        if args.json:
            print(json.dumps(result))
        return

    # Benchmark mode
    if args.benchmark:
        result = run_benchmark(args.model)
        if args.json:
            print(json.dumps(result))
        return

    # === Normal inference mode ===
    # Load model
    model, tokenizer, device, load_time = load_model(args.model, args.device)
    if model is None:
        result = {"error": f"Failed to load model: {args.model}"}
        print(json.dumps(result))
        sys.exit(1)

    # Warmup running
    if args.warmup:
        print("Running warmup inference...", file=sys.stderr)
        t0 = time.time()
        _ = generate_paraphrases(model, tokenizer, "Warmup sentence for model inference.", LANE_SETTINGS["natural"])
        warmup_time = time.time() - t0
        print(f"Warmup: {warmup_time*1000:.0f}ms", file=sys.stderr)

    # Build settings from lane + overrides
    settings = dict(LANE_SETTINGS[args.lane])
    if args.num_beams is not None:
        settings["num_beams"] = args.num_beams
    if args.num_sequences is not None:
        settings["num_return_sequences"] = args.num_sequences
    if args.do_sample:
        settings["do_sample"] = True
    if args.temperature is not None:
        settings["temperature"] = args.temperature

    # Process input(s)
    if args.batch_input:
        try:
            sentences = json.loads(args.batch_input)
        except json.JSONDecodeError:
            print(json.dumps({"error": "Invalid JSON in --batch-input"}))
            sys.exit(1)

        results = []
        for sent in sentences:
            t0 = time.time()
            gens = generate_paraphrases(model, tokenizer, sent, settings)
            elapsed = time.time() - t0
            results.append({
                "input": sent,
                "candidates": gens,
                "time_ms": round(elapsed * 1000, 2),
                "lane": args.lane,
                "settings": settings,
            })

        output = {
            "model": args.model,
            "device": device,
            "load_time_ms": round(load_time * 1000, 2),
            "results": results,
        }

    elif args.input:
        t0 = time.time()
        gens = generate_paraphrases(model, tokenizer, args.input, settings)
        elapsed = time.time() - t0
        output = {
            "model": args.model,
            "device": device,
            "load_time_ms": round(load_time * 1000, 2),
            "generation_time_ms": round(elapsed * 1000, 2),
            "input": args.input,
            "candidates": gens,
            "lane": args.lane,
            "settings": settings,
        }
    else:
        # Interactive mode — read sentences from stdin
        print("Reading sentences from stdin (one per line)...", file=sys.stderr)
        sentences = [line.strip() for line in sys.stdin if line.strip()]

        if not sentences:
            output = {"error": "No input provided"}
        else:
            results = []
            for sent in sentences:
                t0 = time.time()
                gens = generate_paraphrases(model, tokenizer, sent, settings)
                elapsed = time.time() - t0
                results.append({
                    "input": sent,
                    "candidates": gens,
                    "time_ms": round(elapsed * 1000, 2),
                })
            output = {
                "model": args.model,
                "device": device,
                "load_time_ms": round(load_time * 1000, 2),
                "results": results,
            }

    print(json.dumps(output, indent=2) if not args.json else json.dumps(output))


if __name__ == "__main__":
    import torch
    main()
