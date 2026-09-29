#!/usr/bin/env python3
"""Resident MLX-VLM worker for Qwen3.5 with an optional native MTP drafter."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WORKER_PATH = ROOT / "native-runtime" / "paraphrase_worker.py"


def load_worker():
    spec = importlib.util.spec_from_file_location("pari_paraphrase_worker_mtp", WORKER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import {WORKER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def camel_request(payload: dict[str, Any], model_path: Path) -> dict[str, Any]:
    request = {
        "model_path": str(model_path),
        "original_text": payload.get("originalText", ""),
        "protected_spans": payload.get("protectedSpans", []),
        "mode": payload.get("mode", "personal"),
        "strength": payload.get("strength", 56),
        "max_tokens": payload.get("maxTokens", 768),
        "repair_pass": payload.get("repairPass", False),
        "candidates": 1,
        "custom_instructions": payload.get("styleInstructions", ""),
        "style_tweaks": payload.get("styleTweaks", {}),
        "style_context": payload.get("styleContext", {}),
    }
    if isinstance(payload.get("temperature"), (int, float)):
        request["temperature"] = payload["temperature"]
    return request


def generation_settings(request: dict[str, Any]) -> tuple[float, float, int]:
    strength = int(request.get("strength", 56))
    requested_temperature = request.get("temperature")
    if isinstance(requested_temperature, (int, float)):
        temperature = max(0.0, min(float(requested_temperature), 1.0))
    else:
        temperature = 0.16 if strength < 25 else 0.25 if strength < 50 else 0.38 if strength < 75 else 0.52
    top_p = 0.86 if strength < 50 else 0.92 if strength < 75 else 0.95
    max_tokens = max(96, min(int(request.get("max_tokens", 768)), 1536))
    return temperature, top_p, max_tokens


def summarize_acceptance(draft: Any) -> dict[str, Any] | None:
    values = getattr(draft, "accept_lens", None)
    if not isinstance(values, (list, tuple)) or not values:
        return None
    numeric = [float(value) for value in values if isinstance(value, (int, float))]
    if not numeric:
        return None
    return {
        "rounds": len(numeric),
        "meanAcceptedTokensPerRound": round(sum(numeric) / len(numeric), 3),
        "acceptedTokenRounds": [round(value, 3) for value in numeric],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--draft-model")
    args = parser.parse_args()
    model_path = Path(args.model).expanduser().resolve()
    draft_path = Path(args.draft_model).expanduser().resolve() if args.draft_model else None

    import mlx.core as mx
    from mlx_vlm import load
    from mlx_vlm.generate import stream_generate
    from mlx_vlm.sample_utils import make_sampler
    from mlx_vlm.speculative.drafters import load_drafter

    target_model, processor = load(str(model_path))
    draft_model = None
    draft_kind = None
    if draft_path is not None:
        draft_model, draft_kind = load_drafter(str(draft_path), kind="mtp")
        if draft_kind != "mtp":
            raise RuntimeError(f"Expected the native Qwen MTP drafter, got {draft_kind!r}.")

    worker = load_worker()
    print(
        json.dumps(
            {
                "ready": True,
                "model": str(model_path),
                "draftModel": str(draft_path) if draft_path else None,
                "draftKind": draft_kind,
            }
        ),
        flush=True,
    )

    for line in sys.stdin:
        if not line.strip():
            continue
        message: dict[str, Any] = {}
        started = time.perf_counter()
        try:
            message = json.loads(line)
            if message.get("action") == "cancelParaphrase":
                print(json.dumps({"id": message.get("id"), "cancelled": True}), flush=True)
                continue

            payload = message.get("payload") or {}
            request = camel_request(payload, model_path)
            use_mtp = bool(payload.get("useMtp", False))
            if use_mtp and draft_model is None:
                raise ValueError("MTP was requested but no Qwen MTP drafter was loaded.")
            seed = message.get("seed")
            if isinstance(seed, int) and not isinstance(seed, bool):
                mx.random.seed(seed)

            instruction = worker.build_instruction(request)
            prompt = worker.render_prompt(processor.tokenizer, instruction)
            temperature, top_p, max_tokens = generation_settings(request)
            sampler = make_sampler(temp=temperature, top_p=top_p)
            mx.synchronize()
            inference_started = time.perf_counter()
            pieces: list[str] = []
            final_result = None
            generation_kwargs: dict[str, Any] = {
                "max_tokens": max_tokens,
                "sampler": sampler,
                "enable_thinking": False,
                "skip_special_tokens": True,
                "verbose": False,
            }
            if use_mtp:
                generation_kwargs["draft_model"] = draft_model
                generation_kwargs["draft_kind"] = draft_kind
            for result in stream_generate(
                target_model,
                processor,
                prompt=prompt,
                **generation_kwargs,
            ):
                final_result = result
                if result.text:
                    pieces.append(result.text)
            mx.synchronize()
            inference_ms = round((time.perf_counter() - inference_started) * 1000)

            raw_text = worker.clean_output("".join(pieces))
            output = worker.postprocess(raw_text, request)
            response = {
                "ok": bool(output),
                "text": output,
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "inference_ms": inference_ms,
                "temperature": temperature,
                "top_p": top_p,
                "prompt_tokens": getattr(final_result, "prompt_tokens", None),
                "generation_tokens": getattr(final_result, "generation_tokens", None),
                "prompt_tokens_per_second": getattr(final_result, "prompt_tps", None),
                "generation_tokens_per_second": getattr(final_result, "generation_tps", None),
                "finish_reason": getattr(final_result, "finish_reason", None),
                "peak_memory_gb": getattr(final_result, "peak_memory", None),
                "mtp_acceptance": summarize_acceptance(draft_model) if use_mtp else None,
            }
            if not output:
                response["error"] = "The native generator returned no usable paragraph."
        except Exception as error:  # noqa: BLE001 - bounded local benchmark error
            response = {
                "ok": False,
                "text": "",
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "error": str(error),
            }

        try:
            mx.synchronize()
            mx.clear_cache()
        except Exception:
            pass
        print(json.dumps({"id": message.get("id"), "response": response}, ensure_ascii=False), flush=True)

    target_model = processor = draft_model = None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
