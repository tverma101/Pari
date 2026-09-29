#!/usr/bin/env python3
"""Run one Pari paraphrase request through a local Ollama OpenAI endpoint.

The endpoint is normally the loopback end of an SSH port forward whose other
end is the Ollama server on a KaggleLink notebook.  The worker is one-shot and
never writes prompts, responses, or credentials to disk.  Pari's existing
browser-side protection, meaning, grammar, and flow gates remain authoritative.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

RUNTIME_DIR = Path(__file__).resolve().parent
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from paraphrase_worker import build_instruction, clean_output, postprocess


DEFAULT_BASE_URL = "http://127.0.0.1:11435/v1"
DEFAULT_API_KEY = "ollama"


def emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def positive_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def request_payload(request: dict[str, Any], model: str) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": build_instruction(request)}],
        # One remote draft is deliberate. Pari can issue one stricter repair
        # pass if local gates reject the first draft, but it does not spend
        # four remote calls on best-of-N ranking.
        "max_tokens": positive_int(request.get("max_tokens"), 256, 96, 768),
        "temperature": 0.0 if not request.get("repair_pass") else 0.12,
        "stream": False,
    }


def main() -> int:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("Ollama request was not a JSON object.")

        model = os.environ.get("PARI_OLLAMA_MODEL", "").strip()
        if not model:
            raise ValueError(
                "Ollama routing is enabled but PARI_OLLAMA_MODEL is not set. "
                "Choose a model present in the remote Ollama /api/tags response."
            )

        base_url = os.environ.get("PARI_OLLAMA_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
        if not base_url:
            base_url = DEFAULT_BASE_URL
        api_key = os.environ.get("PARI_OLLAMA_API_KEY", DEFAULT_API_KEY).strip() or DEFAULT_API_KEY
        endpoint = base_url + "/chat/completions"
        timeout = max(5.0, min(float(os.environ.get("PARI_OLLAMA_TIMEOUT", "180")), 240.0))

        encoded = json.dumps(request_payload(request, model), ensure_ascii=False).encode("utf-8")
        http_request = urllib.request.Request(
            endpoint,
            data=encoded,
            headers={
                # Ollama ignores the placeholder key, but its OpenAI-compatible
                # endpoint expects the standard Authorization header shape.
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(http_request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))

        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError("Ollama returned an unexpected chat completion.") from error

        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Ollama returned no text content.")

        cleaned = clean_output(content)
        text = postprocess(cleaned, request)
        if not text.strip():
            raise ValueError("Ollama returned no usable paragraph after Pari cleanup.")

        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        response: dict[str, Any] = {
            "ok": True,
            "text": text.strip(),
            "backend": "ollama",
            "model_id": f"ollama:{model}",
            "served_model": payload.get("model") if isinstance(payload.get("model"), str) else model,
            "usage": usage,
        }
        emit(response)
        return 0
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace").strip()
        emit({
            "ok": False,
            "error": f"Ollama returned HTTP {error.code}: {detail[:500] or 'no server detail'}",
        })
        return 1
    except urllib.error.URLError as error:
        emit({"ok": False, "error": f"Ollama was unreachable at the configured local endpoint: {error.reason}"})
        return 1
    except Exception as error:  # noqa: BLE001 - worker must return JSON to Swift on every failure.
        emit({"ok": False, "error": str(error)[:600]})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
