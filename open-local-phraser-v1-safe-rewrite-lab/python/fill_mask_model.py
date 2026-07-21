#!/usr/bin/env python3
"""
Fill-mask model for contextual word alternatives.
Given a sentence with a masked token, returns top-k predictions.

Usage:
  python3 fill_mask_model.py --model bert-base-uncased --sentence "This <mask> the role of communication." --mask "<mask>"
  python3 fill_mask_model.py --benchmark
"""

import argparse
import json
import sys
import time
import os

os.environ["TRANSFORMERS_VERBOSITY"] = "error"

AVAILABLE_MODELS = {
    "bert-base-uncased": {
        "name": "BERT Base Uncased",
        "description": "Standard BERT for fill-mask — good general predictions",
        "size_mb": 440,
    },
    "distilbert-base-uncased": {
        "name": "DistilBERT Base Uncased",
        "description": "Faster, smaller BERT — slightly lower quality",
        "size_mb": 260,
    },
    "roberta-base": {
        "name": "RoBERTa Base",
        "description": "Better contextual predictions than BERT in many cases",
        "size_mb": 470,
    },
}


def load_model(model_name: str):
    """Load fill-mask pipeline."""
    from transformers import pipeline

    print(f"Loading fill-mask model {model_name}...", file=sys.stderr)
    t0 = time.time()

    try:
        pipe = pipeline("fill-mask", model=model_name)
        load_time = time.time() - t0
        print(f"Loaded in {load_time:.2f}s", file=sys.stderr)
        return pipe, load_time
    except Exception as e:
        print(f"Error loading {model_name}: {e}", file=sys.stderr)
        return None, 0


def predict_masks(pipe, sentence: str, mask_token: str = "[MASK]", top_k: int = 20):
    """Get top-k predictions for a masked token."""
    result = pipe(sentence, top_k=top_k)
    predictions = []
    for r in result:
        predictions.append({
            "token": r["token_str"],
            "score": round(r["score"], 4),
            "sequence": r["sequence"],
        })
    return predictions


def main():
    parser = argparse.ArgumentParser(description="Fill-mask model for token alternatives")
    parser.add_argument("--model", type=str, default="bert-base-uncased")
    parser.add_argument("--sentence", type=str, help="Sentence with mask token")
    parser.add_argument("--mask", type=str, default="[MASK]", help="Mask token string")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if args.list_models:
        print(json.dumps(AVAILABLE_MODELS, indent=2))
        return

    if args.benchmark:
        pipe, load_time = load_model(args.model)
        if pipe is None:
            print(json.dumps({"error": "Failed to load model"}))
            sys.exit(1)

        test_sentences = [
            f"This {args.mask} the importance of communication.",
            f"The {args.mask} sat on the mat.",
            f"She {args.mask} to the store yesterday.",
        ]

        results = []
        for sent in test_sentences:
            t0 = time.time()
            predictions = predict_masks(pipe, sent, args.mask, 10)
            elapsed = time.time() - t0
            results.append({
                "sentence": sent,
                "predictions": predictions[:5],
                "time_ms": round(elapsed * 1000, 2),
            })

        output = {
            "model": args.model,
            "load_time_ms": round(load_time * 1000, 2),
            "results": results,
        }
        print(json.dumps(output, indent=2))
        return

    if args.sentence:
        pipe, load_time = load_model(args.model)
        if pipe is None:
            print(json.dumps({"error": "Failed to load model"}))
            sys.exit(1)

        t0 = time.time()
        predictions = predict_masks(pipe, args.sentence, args.mask, args.top_k)
        elapsed = time.time() - t0

        output = {
            "model": args.model,
            "load_time_ms": round(load_time * 1000, 2),
            "compute_time_ms": round(elapsed * 1000, 2),
            "sentence": args.sentence,
            "predictions": predictions,
        }
        print(json.dumps(output, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
