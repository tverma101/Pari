#!/usr/bin/env python3
"""Exercise the Ollama worker against a local OpenAI-compatible fake server."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "native-runtime" / "ollama_worker.py"


class FakeOllamaHandler(BaseHTTPRequestHandler):
    request_body: dict[str, Any] | None = None
    request_headers: dict[str, str] = {}

    def do_POST(self) -> None:  # noqa: N802 - stdlib protocol hook
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).request_body = json.loads(body.decode("utf-8"))
        type(self).request_headers = {
            "authorization": self.headers.get("Authorization", ""),
            "content_type": self.headers.get("Content-Type", ""),
        }
        response = {
            "id": "qa-ollama-completion",
            "object": "chat.completion",
            "model": "qa-model-served",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "The package arrived on Tuesday, and it was damaged.",
                },
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 12, "completion_tokens": 9, "total_tokens": 21},
        }
        encoded = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def run_worker(environment: dict[str, str], request: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    result = subprocess.run(
        [sys.executable, str(WORKER)],
        cwd=ROOT,
        input=json.dumps(request),
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise AssertionError(f"worker emitted no JSON; stderr={result.stderr!r}")
    return result.returncode, json.loads(lines[-1])


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllamaHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        environment = os.environ.copy()
        environment.update({
            "PARI_OLLAMA_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
            "PARI_OLLAMA_MODEL": "qa-model-requested",
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        request = {
            "original_text": "The package arrived yesterday but it was damaged.",
            "protected_spans": ["yesterday"],
            "mode": "personal",
            "strength": 56,
            "max_tokens": 256,
        }
        code, response = run_worker(environment, request)
        assert code == 0, response
        assert response["ok"] is True, response
        assert response["backend"] == "ollama", response
        assert response["model_id"] == "ollama:qa-model-requested", response
        assert response["served_model"] == "qa-model-served", response
        assert response["text"] == "The package arrived on Tuesday, and it was damaged.", response
        assert FakeOllamaHandler.request_body is not None
        assert FakeOllamaHandler.request_body["model"] == "qa-model-requested"
        assert FakeOllamaHandler.request_body["stream"] is False
        assert FakeOllamaHandler.request_body["messages"][0]["content"]
        assert FakeOllamaHandler.request_headers["authorization"] == "Bearer ollama"

        missing_model = environment.copy()
        missing_model.pop("PARI_OLLAMA_MODEL")
        code, response = run_worker(missing_model, request)
        assert code == 1, response
        assert response["ok"] is False, response
        assert "PARI_OLLAMA_MODEL" in response["error"], response
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    print("ollama worker QA passed (OpenAI-compatible request, response, and missing-model failure path)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
