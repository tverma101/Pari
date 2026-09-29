#!/usr/bin/env python3
"""Keep Pari's native MLX model resident while serving benchmark requests.

The request and generation code remain the production paraphrase worker's.
Only mlx_lm.load is replaced with a path-checked in-memory loader, and emit is
captured so this process can return one JSONL response per benchmark request.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WORKER_PATH = ROOT / "native-runtime" / "paraphrase_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("pari_paraphrase_worker", WORKER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import {WORKER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def camel_request(payload: dict[str, Any], model_path: Path, draft_model_path: Path | None) -> dict[str, Any]:
    request = {
        "model_path": str(model_path),
        "original_text": payload.get("originalText", ""),
        "protected_spans": payload.get("protectedSpans", []),
        "mode": payload.get("mode", "personal"),
        "strength": payload.get("strength", 56),
        "max_tokens": payload.get("maxTokens", 768),
        "repair_pass": payload.get("repairPass", False),
        "candidates": payload.get("candidates", 4),
        "custom_instructions": payload.get("styleInstructions", ""),
        "style_tweaks": payload.get("styleTweaks", {}),
        "style_context": payload.get("styleContext", {}),
        "num_draft_tokens": payload.get("numDraftTokens", 3),
    }
    if isinstance(payload.get("temperature"), (int, float)):
        request["temperature"] = payload["temperature"]
    if draft_model_path is not None:
        request["draft_model_path"] = str(draft_model_path)
    return request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--draft-model")
    args = parser.parse_args()
    model_path = Path(args.model).expanduser().resolve()
    draft_model_path = Path(args.draft_model).expanduser().resolve() if args.draft_model else None

    import mlx_lm
    import mlx.core as mx

    production_load = mlx_lm.load
    target_model, target_tokenizer = production_load(str(model_path))
    loaded: dict[Path, tuple[Any, Any]] = {model_path: (target_model, target_tokenizer)}
    if draft_model_path is not None:
        loaded[draft_model_path] = production_load(str(draft_model_path))

    def cached_load(path: str, *unused: Any, **unused_kwargs: Any):
        resolved = Path(path).expanduser().resolve()
        if resolved not in loaded:
            raise ValueError("The benchmark requested a model that was not preloaded.")
        return loaded[resolved]

    mlx_lm.load = cached_load
    worker = load_worker()
    worker.emit = lambda _payload: None
    print(json.dumps({"ready": True, "model": str(model_path), "draftModel": str(draft_model_path) if draft_model_path else None}), flush=True)

    for line in sys.stdin:
        if not line.strip():
            continue
        message: dict[str, Any] = {}
        try:
            message = json.loads(line)
            if message.get("action") == "cancelParaphrase":
                print(json.dumps({"id": message.get("id"), "cancelled": True}), flush=True)
                continue
            request = camel_request(message.get("payload", {}), model_path, draft_model_path)
            seed = message.get("seed")
            if isinstance(seed, int) and not isinstance(seed, bool):
                mx.random.seed(seed)
            captured: dict[str, Any] = {}
            worker.emit = lambda payload: captured.update(payload)
            worker.generate(request)
            response = captured or {"ok": False, "error": "The native worker emitted no result."}
        except Exception as error:  # noqa: BLE001 - report only a bounded benchmark error
            response = {"ok": False, "error": str(error)}
        try:
            if hasattr(mx, "synchronize"):
                mx.synchronize()
            mx.clear_cache()
        except Exception:
            pass
        print(json.dumps({"id": message.get("id"), "response": response}, ensure_ascii=False), flush=True)

    loaded.clear()
    target_model = target_tokenizer = None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
