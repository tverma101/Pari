#!/usr/bin/env python3
"""One-shot Pari worker for a matching Qwen3.5 target and native MTP drafter."""

from __future__ import annotations

import json
import sys
import time
from typing import Any


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def generate(request: dict[str, Any]) -> None:
    import mlx.core as mx
    from mlx_vlm import load
    from mlx_vlm.generate import stream_generate
    from mlx_vlm.sample_utils import make_sampler
    from mlx_vlm.speculative.drafters import load_drafter

    import paraphrase_worker as worker

    started = time.perf_counter()
    model_path = str(request.get("model_path", "")).strip()
    draft_path = str(request.get("mtp_draft_model_path", "")).strip()
    if not model_path or not draft_path:
        raise ValueError("Both a Qwen3.5 target and matching MTP drafter are required.")

    strength = int(request.get("strength", 56))
    requested_temperature = request.get("temperature")
    temperature = (
        max(0.0, min(float(requested_temperature), 1.0))
        if isinstance(requested_temperature, (int, float))
        else 0.16 if strength < 25 else 0.25 if strength < 50 else 0.38 if strength < 75 else 0.52
    )
    top_p = 0.86 if strength < 50 else 0.92 if strength < 75 else 0.95
    max_tokens = max(96, min(int(request.get("max_tokens", 768)), 1536))
    candidate_count = max(1, min(int(request.get("candidates", 1)), 4))
    target_model = processor = draft_model = None

    try:
        target_model, processor = load(model_path)
        draft_model, draft_kind = load_drafter(draft_path, kind="mtp")
        if draft_kind != "mtp":
            raise ValueError(f"Expected an MTP drafter, but MLX-VLM loaded {draft_kind!r}.")

        prompt = worker.render_prompt(
            processor.tokenizer,
            worker.build_instruction(request),
        )
        seed = request.get("seed")
        if isinstance(seed, int) and not isinstance(seed, bool):
            mx.random.seed(seed)

        candidates: list[dict[str, Any]] = []
        for index in range(candidate_count):
            candidate_temperature = (
                temperature if index == 0 else min(1.0, round(temperature + 0.22 * index, 2))
            )
            sampler = make_sampler(temp=candidate_temperature, top_p=top_p)
            pieces: list[str] = []
            for result in stream_generate(
                target_model,
                processor,
                prompt=prompt,
                max_tokens=max_tokens,
                sampler=sampler,
                draft_model=draft_model,
                draft_kind=draft_kind,
                enable_thinking=False,
                skip_special_tokens=True,
                verbose=False,
            ):
                if result.text:
                    pieces.append(result.text)

            raw_text = worker.clean_output("".join(pieces))
            try:
                text = worker.postprocess(raw_text, request)
            except ValueError as error:
                if index == 0 and candidate_count == 1:
                    raise
                candidates.append(
                    {"text": "", "temperature": candidate_temperature, "error": str(error)}
                )
                continue
            candidates.append({"text": text, "temperature": candidate_temperature})

        primary = next((candidate for candidate in candidates if candidate.get("text")), None)
        if primary is None:
            raise ValueError("The Qwen MTP generator returned no usable paragraph.")
        emit(
            {
                "ok": True,
                "text": primary["text"],
                "duration_ms": round((time.perf_counter() - started) * 1000),
                "temperature": primary["temperature"],
                "candidates": candidates,
                "backend": "native-mlx-mtp",
            }
        )
    finally:
        try:
            mx.synchronize()
        finally:
            target_model = processor = draft_model = None
            try:
                mx.clear_cache()
            except Exception:
                pass


def main() -> int:
    try:
        request = json.load(sys.stdin)
        generate(request)
        return 0
    except Exception as error:  # noqa: BLE001 - native errors are user-facing recovery state
        emit({"ok": False, "error": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
