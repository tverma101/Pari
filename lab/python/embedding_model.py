#!/usr/bin/env python3
"""
Sentence embedding model runner for similarity scoring.
Uses sentence-transformers to compute embeddings and cosine similarity.

Usage:
  python3 embedding_model.py --model all-MiniLM-L6-v2 --sentences '["text1","text2"]'
  python3 embedding_model.py --model all-MiniLM-L6-v2 --pairs '[["a","b"],["c","d"]]'
  python3 embedding_model.py --list-models
  python3 embedding_model.py --benchmark
"""

import argparse
import json
import sys
import time
import os

os.environ["TRANSFORMERS_VERBOSITY"] = "error"

AVAILABLE_MODELS = {
    "all-MiniLM-L6-v2": {
        "name": "all-MiniLM-L6-v2",
        "description": "Fast, lightweight embedding model — good for similarity",
        "dimensions": 384,
        "size_mb": 80,
    },
    "all-MiniLM-L12-v2": {
        "name": "all-MiniLM-L12-v2",
        "description": "Larger MiniLM — slightly better quality, slower",
        "dimensions": 384,
        "size_mb": 120,
    },
    "BAAI/bge-small-en-v1.5": {
        "name": "BGE Small English v1.5",
        "description": "BGE small model — good for retrieval/similarity",
        "dimensions": 384,
        "size_mb": 133,
    },
    "all-mpnet-base-v2": {
        "name": "all-mpnet-base-v2",
        "description": "Best quality general-purpose embedding model (slower)",
        "dimensions": 768,
        "size_mb": 420,
    },
    "paraphrase-MiniLM-L6-v2": {
        "name": "paraphrase-MiniLM-L6-v2",
        "description": "Optimized for paraphrase similarity detection",
        "dimensions": 384,
        "size_mb": 80,
    },
}


def load_model(model_name: str):
    """Load sentence-transformers model."""
    from sentence_transformers import SentenceTransformer

    print(f"Loading {model_name}...", file=sys.stderr)
    t0 = time.time()

    try:
        # Use full model name if not short form
        full_name = model_name
        if not model_name.startswith("sentence-transformers/") and not model_name.startswith("BAAI/"):
            if model_name in ["all-MiniLM-L6-v2", "all-MiniLM-L12-v2", "all-mpnet-base-v2", "paraphrase-MiniLM-L6-v2"]:
                full_name = f"sentence-transformers/{model_name}"

        model = SentenceTransformer(full_name)
        load_time = time.time() - t0
        print(f"Loaded in {load_time:.2f}s. Dims: {model.get_sentence_embedding_dimension()}", file=sys.stderr)

        return model, load_time

    except Exception as e:
        print(f"Error loading {model_name}: {e}", file=sys.stderr)
        return None, 0


def compute_similarity(model, text1: str, text2: str) -> float:
    """Compute cosine similarity between two texts."""
    embeddings = model.encode([text1, text2], normalize_embeddings=True)
    similarity = float(embeddings[0] @ embeddings[1].T)
    return similarity


def batch_encode(model, sentences: list) -> list:
    """Encode a batch of sentences and return embeddings as lists."""
    embeddings = model.encode(sentences, normalize_embeddings=True)
    return embeddings.tolist()


def main():
    parser = argparse.ArgumentParser(description="Sentence embedding model")
    parser.add_argument("--model", type=str, default="all-MiniLM-L6-v2")
    parser.add_argument("--sentences", type=str, help="JSON array of sentences to encode")
    parser.add_argument("--pairs", type=str, help="JSON array of [text1, text2] pairs for similarity")
    parser.add_argument("--similarity", type=str, nargs=2, metavar=("TEXT1", "TEXT2"),
                        help="Compute similarity between two texts")
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--json", action="store_true", help="JSON output")

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
            ("I think communication matters.", "Communication is important."),
            ("The cat sat on the mat.", "The dog ran in the park."),
            ("This is a test sentence for embedding.", "This is a different sentence entirely."),
        ]

        results = []
        for a, b in test_pairs:
            t0 = time.time()
            sim = compute_similarity(model, a, b)
            elapsed = time.time() - t0
            results.append({
                "text1": a[:50],
                "text2": b[:50],
                "similarity": round(sim, 4),
                "time_ms": round(elapsed * 1000, 2),
            })

        output = {
            "model": args.model,
            "load_time_ms": round(load_time * 1000, 2),
            "results": results,
        }
        print(json.dumps(output, indent=2))
        return

    if args.sentences:
        try:
            sentences = json.loads(args.sentences)
        except json.JSONDecodeError:
            print(json.dumps({"error": "Invalid JSON in --sentences"}))
            sys.exit(1)

        model, load_time = load_model(args.model)
        if model is None:
            print(json.dumps({"error": "Failed to load model"}))
            sys.exit(1)

        t0 = time.time()
        embeddings = batch_encode(model, sentences)
        elapsed = time.time() - t0

        output = {
            "model": args.model,
            "load_time_ms": round(load_time * 1000, 2),
            "encoding_time_ms": round(elapsed * 1000, 2),
            "dimensions": model.get_sentence_embedding_dimension(),
            "num_sentences": len(sentences),
            "embeddings": embeddings,
        }
        print(json.dumps(output) if args.json else json.dumps(output, indent=2))
        return

    if args.similarity:
        model, load_time = load_model(args.model)
        if model is None:
            print(json.dumps({"error": "Failed to load model"}))
            sys.exit(1)

        text1, text2 = args.similarity
        t0 = time.time()
        sim = compute_similarity(model, text1, text2)
        elapsed = time.time() - t0

        output = {
            "model": args.model,
            "load_time_ms": round(load_time * 1000, 2),
            "compute_time_ms": round(elapsed * 1000, 2),
            "text1": text1,
            "text2": text2,
            "similarity": round(sim, 4),
        }
        print(json.dumps(output, indent=2))
        return

    # Pairs mode
    if args.pairs:
        try:
            pairs = json.loads(args.pairs)
        except json.JSONDecodeError:
            print(json.dumps({"error": "Invalid JSON in --pairs"}))
            sys.exit(1)

        model, load_time = load_model(args.model)
        if model is None:
            print(json.dumps({"error": "Failed to load model"}))
            sys.exit(1)

        results = []
        for pair in pairs:
            t0 = time.time()
            sim = compute_similarity(model, pair[0], pair[1])
            elapsed = time.time() - t0
            results.append({
                "text1": pair[0][:50],
                "text2": pair[1][:50],
                "similarity": round(sim, 4),
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
