#!/usr/bin/env python3
"""Run one Pari paraphrase request through the local FreeLLMAPI proxy.

The worker is one-shot and intentionally receives the API key only through
the inherited environment. It never writes credentials or provider payloads
to disk. Keeping this outside WebKit also lets the existing Swift process
return a clean failure so the browser can use Pari's offline safety fallback.
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


DEFAULT_BASE_URL = "http://127.0.0.1:31415/v1"
DEFAULT_MODEL = "gemma-4-31b"


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
        # One remote draft is deliberate. Pari's browser layer can issue one
        # stricter repair pass if the first draft fails its local gates, but it
        # must not spend four API calls on best-of-N remote ranking.
        "max_tokens": positive_int(request.get("max_tokens"), 256, 96, 512),
        "temperature": 0.0 if not request.get("repair_pass") else 0.12,
        "stream": False,
    }


def main() -> int:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("FreeLLMAPI request was not a JSON object.")

        api_key = os.environ.get("PARI_FREELLM_API_KEY", "").strip()
        if not api_key:
            raise ValueError("FreeLLMAPI route is enabled but PARI_FREELLM_API_KEY is not set.")

        base_url = os.environ.get("PARI_FREELLM_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
        if not base_url:
            base_url = DEFAULT_BASE_URL
        model = os.environ.get("PARI_FREELLM_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
        endpoint = base_url + "/chat/completions"
        timeout = max(5.0, min(float(os.environ.get("PARI_FREELLM_TIMEOUT", "120")), 180.0))

        encoded = json.dumps(request_payload(request, model), ensure_ascii=False).encode("utf-8")
        http_request = urllib.request.Request(
            endpoint,
            data=encoded,
            headers={
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
            raise ValueError("FreeLLMAPI returned an unexpected chat completion.") from error

        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ValueError("FreeLLMAPI returned no text content.")

        cleaned = clean_output(content)
        text = postprocess(cleaned, request)
        if not text.strip():
            raise ValueError("FreeLLMAPI returned no usable paragraph after Pari cleanup.")

        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        response: dict[str, Any] = {
            "ok": True,
            "text": text.strip(),
            "backend": "freellm-api",
            "model_id": f"freellm:{model}",
            "served_model": payload.get("model") if isinstance(payload.get("model"), str) else model,
            "usage": usage,
        }
        emit(response)
        return 0
    except urllib.error.HTTPError as error:
        # Provider details are useful for diagnostics, but the Authorization
        # header is never included in this message or emitted to the browser.
        detail = error.read().decode("utf-8", errors="replace").strip()
        emit({
            "ok": False,
            "error": f"FreeLLMAPI returned HTTP {error.code}: {detail[:500] or 'no provider detail'}",
        })
        return 1
    except urllib.error.URLError as error:
        emit({"ok": False, "error": f"FreeLLMAPI was unreachable at the configured local endpoint: {error.reason}"})
        return 1
    except Exception as error:  # noqa: BLE001 - worker must return JSON to Swift on every failure.
        emit({"ok": False, "error": str(error)[:600]})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
