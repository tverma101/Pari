#!/usr/bin/env python3
"""
NLI (Natural Language Inference) model runner.
Detects factual drift: does the rewrite contradict the original?

Usage:
  python3 nli_model.py --premise "Original text." --hypothesis "Rewritten text."
  python3 nli_model.py --batch '[["premise1","hyp1"],["premise2","hyp2"]]'
  python3 nli_model.py --benchmark
"""

import argparse
import json
import sys
import time
import os

os.environ["TRANSFORMERS_VERBOSITY"] = "error"

AVAILABLE_MODELS = {
    "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli": {
        "name": "DeBERTa-v3-base MNLI+FEVER+ANLI",
        "description": "Best performing zero-shot NLI model for contradiction detection",
        "size_mb": 570,
    },
    "cross-encoder/nli-deberta-v3-small": {
        "name": "DeBERTa-v3-small NLI",
        "description": "Smaller NLI model — faster but slightly less accurate",
        "size_mb": 260,
    },
}


def load_model(model_name: str):
    """Load NLI pipeline."""
    from transformers import pipeline

    print(f"Loading NLI model {model_name}...", file=sys.stderr)
    t0 = time.time()

    try:
        classifier = pipeline(
            "zero-shot-classification",
            model=model_name,
            device=-1,  # CPU for stability
        )
        load_time = time.time() - t0
        print(f"Loaded in {load_time:.2f}s", file=sys.stderr)
        return classifier, load_time

    except Exception as e:
        print(f"Error loading {model_name}: {e}", file=sys.stderr)
        return None, 0


def check_entailment(classifier, premise: str, hypothesis: str, model_name: str):
    """Check if hypothesis entails, contradicts, or is neutral w.r.t premise."""
    # Use NLI labels directly
    if "nli" in model_name.lower() or "mnli" in model_name.lower():
        # Use NLI pipeline for entailment/contradiction detection
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        # Fall back to standard entailment check
        result = classifier(
            hypothesis,
            candidate_labels=["entailment", "contradiction", "neutral"],
            hypothesis_template="{}",
        )

        scores = dict(zip(result["labels"], result["scores"]))
        return {
            "entailment": round(scores.get("entailment", 0) * 100, 2),
            "contradiction": round(scores.get("contradiction", 0) * 100, 2),
            "neutral": round(scores.get("neutral", 0) * 100, 2),
            "label": result["labels"][0],
            "score": round(result["scores"][0] * 100, 2),
        }

    # For DeBERTa NLI models, use the NLI pipeline directly
    try:
        from transformers import pipeline as nli_pipeline
        nli = nli_pipeline(
            "text-classification",
            model=model_name,
            return_all_scores=True,
        )
        # NLI models take (premise, hypothesis) pairs
        result = nli(f"{premise} </s></s> {hypothesis}")

        scores = {}
        for r in result[0]:
            label = r["label"].lower()
            scores[label] = round(r["score"] * 100, 2)

        return scores

    except Exception as e:
        return {"error": str(e), "entailment": 0, "contradiction": 0, "neutral": 0}


def main():
    parser = argparse.ArgumentParser(description="NLI model for contradiction detection")
    parser.add_argument("--model", type=str, default="MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli")
    parser.add_argument("--premise", type=str, help="Original text")
    parser.add_argument("--hypothesis", type=str, help="Rewritten text")
    parser.add_argument("--batch", type=str, help="JSON array of [premise, hypothesis] pairs")
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if args.list_models:
        print(json.dumps(AVAILABLE_MODELS, indent=2))
        return

    if args.benchmark:
        model, load_time = load_model(args.model)
        if model is None:
            print(json.dumps({"error": "Failed to load model"}))
            sys.exit(1)

        test_pairs = [
            ("The sky is blue.", "The sky is blue."),
            ("The sky is blue.", "The sky is green."),
            ("Social media has benefits and drawbacks.", "Social media only has drawbacks."),
            ("I do not think social media is always bad.", "I think social media is always bad."),
        ]

        results = []
        for premise, hypothesis in test_pairs:
            t0 = time.time()
            scores = check_entailment(model, premise, hypothesis, args.model)
            elapsed = time.time() - t0
            results.append({
                "premise": premise,
                "hypothesis": hypothesis,
                "scores": scores,
                "time_ms": round(elapsed * 1000, 2),
            })

        output = {
            "model": args.model,
            "load_time_ms": round(load_time * 1000, 2),
            "results": results,
        }
        print(json.dumps(output, indent=2))
        return

    if args.premise and args.hypothesis:
        model, load_time = load_model(args.model)
        if model is None:
            print(json.dumps({"error": "Failed to load model"}))
            sys.exit(1)

        t0 = time.time()
        scores = check_entailment(model, args.premise, args.hypothesis, args.model)
        elapsed = time.time() - t0

        output = {
            "model": args.model,
            "load_time_ms": round(load_time * 1000, 2),
            "compute_time_ms": round(elapsed * 1000, 2),
            "premise": args.premise,
            "hypothesis": args.hypothesis,
            "scores": scores,
        }
        print(json.dumps(output, indent=2))
        return

    if args.batch:
        try:
            pairs = json.loads(args.batch)
        except json.JSONDecodeError:
            print(json.dumps({"error": "Invalid JSON in --batch"}))
            sys.exit(1)

        model, load_time = load_model(args.model)
        if model is None:
            print(json.dumps({"error": "Failed to load model"}))
            sys.exit(1)

        results = []
        for premise, hypothesis in pairs:
            t0 = time.time()
            scores = check_entailment(model, premise, hypothesis, args.model)
            elapsed = time.time() - t0
            results.append({
                "premise": premise[:60],
                "hypothesis": hypothesis[:60],
                "scores": scores,
                "time_ms": round(elapsed * 1000, 2),
            })

        output = {
            "model": args.model,
            "load_time_ms": round(load_time * 1000, 2),
            "results": results,
        }
        print(json.dumps(output, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
