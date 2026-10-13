#!/usr/bin/env python3
"""Async adapter from a Studio lane to a local OpenAI-compatible model server.

The adapter permits loopback endpoints only. Raw upstream response bodies are
hashed immediately and never included in exceptions or structured observations.
Optional raw capture is bounded and disabled unless explicitly enabled.
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .errors import ClientErrorCode, ModelBackendError
from .options import parse_document_details, parse_options
from .prompting import CompiledPrompt
from .telemetry import BoundedStore


# Issue #61: an upstream error body is untrusted input that can be arbitrarily
# large and can echo the prompt, the source document, template diagnostics, or
# local paths. Read only a bounded prefix for diagnosis, hash it, and record its
# length. The body text is never placed in an exception, a log field, or an
# observation.
MAX_UPSTREAM_ERROR_DIAGNOSTIC_BYTES = 8 * 1024

# Issue #61: raw capture is an opt-in debug path, so bound a single captured
# response as well as the number of retained entries. Entry count and TTL stop
# unbounded growth across requests; this stops one response from being unbounded.
MAX_CAPTURED_RAW_TEXT_CHARS = 64 * 1024


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()


@dataclass(frozen=True)
class AdapterObservation:
    request_id: str
    model_id: str
    runtime_id: str
    parser_mode: str
    parser_version: int | None
    parsed_count: int
    finish_reason: str | None
    output_chars: int
    output_sha256: str
    elapsed_ms: float
    raw_text: str | None = None

    def to_wire(self) -> dict[str, Any]:
        payload = {
            "requestId": self.request_id,
            "modelId": self.model_id,
            "runtimeId": self.runtime_id,
            "parserMode": self.parser_mode,
            "parserVersion": self.parser_version,
            "parsedCount": self.parsed_count,
            "finishReason": self.finish_reason,
            "outputChars": self.output_chars,
            "outputSha256": self.output_sha256,
            "elapsedMs": self.elapsed_ms,
            "rawTextCaptured": self.raw_text is not None,
            "rawTextChars": None if self.raw_text is None else len(self.raw_text),
        }
        if self.raw_text is not None:
            payload["rawText"] = self.raw_text
        return payload


class OpenAIChatLaneAdapter:
    def __init__(
        self,
        endpoint: str,
        model: str,
        *,
        runtime_id: str | None = None,
        timeout_seconds: float = 120.0,
        seed: int = 0,
        observation_entries: int = 256,
        observation_ttl_seconds: float = 900.0,
        capture_raw_text: bool = False,
    ) -> None:
        parsed = urlparse(endpoint)
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Studio model adapter endpoint must be loopback")
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.runtime_id = runtime_id or model
        self.timeout_seconds = timeout_seconds
        self.seed = seed
        self.capture_raw_text = bool(capture_raw_text)
        self._tasks: dict[str, set[asyncio.Task]] = {}
        self._observations: BoundedStore = BoundedStore(
            max_entries=max(1, int(observation_entries)),
            ttl_seconds=max(0.0, float(observation_ttl_seconds)),
        )

    @property
    def observations(self) -> BoundedStore:
        return self._observations

    def diagnostics(self, request_id: str) -> dict[str, Any]:
        values = self._observations.values()
        observation = next(
            (
                item
                for item in reversed(values)
                if isinstance(item, AdapterObservation) and item.request_id == request_id
            ),
            None,
        )
        if observation is None:
            return {}
        return {
            "parserMode": observation.parser_mode,
            "parserFailure": observation.parser_mode in {"unparseable", "empty_output"},
            "parserDiagnosticAvailable": True,
            "parsedCount": observation.parsed_count,
            "finishReason": observation.finish_reason,
            "outputChars": observation.output_chars,
            "outputSha256": observation.output_sha256,
            "elapsedMs": observation.elapsed_ms,
        }

    async def generate(self, prompt: CompiledPrompt, *, request_id: str) -> list[str]:
        try:
            import aiohttp
        except ImportError as exc:  # pragma: no cover - live serving environment
            raise ModelBackendError(
                ClientErrorCode.MODEL_UNAVAILABLE,
                "aiohttp is required by the live Studio adapter",
            ) from exc

        current = asyncio.current_task()
        if current is not None:
            self._tasks.setdefault(request_id, set()).add(current)
        payload = {
            "model": self.model,
            "messages": [
                {"role": prompt.system_role, "content": prompt.system},
                {"role": prompt.data_role, "content": prompt.user},
            ],
            "temperature": prompt.temperature,
            "top_p": prompt.top_p,
            "max_tokens": prompt.max_new_tokens,
            "seed": self.seed,
            "stream": False,
            "reasoning_effort": "none",
            "chat_template_kwargs": {"enable_thinking": False},
        }
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds, connect=15)
        started = time.monotonic()
        raw_text = ""
        finish_reason = None
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self.endpoint + "/v1/chat/completions", json=payload
                ) as response:
                    if response.status >= 400:
                        # Issue #61: bound how much of an upstream error body is
                        # read at all, then record only a digest and a length.
                        # A 500-error body can be megabytes and can echo the
                        # prompt or the source document; reading it in full
                        # would both cost memory and create a string that must
                        # never reach a log, an observation, or the client.
                        prefix = await response.content.read(
                            MAX_UPSTREAM_ERROR_DIAGNOSTIC_BYTES
                        )
                        raise ModelBackendError(
                            ClientErrorCode.MODEL_UNAVAILABLE,
                            "upstream HTTP {status} errorChars={chars} errorSha256={digest}".format(
                                status=response.status,
                                chars=len(prefix),
                                digest=_sha256(prefix.decode("utf-8", "replace")),
                            ),
                            retryable=response.status >= 500,
                        )
                    body = await response.text()
                    try:
                        data = await response.json()
                    except Exception as exc:
                        raise ModelBackendError(
                            ClientErrorCode.BACKEND_PROTOCOL_ERROR,
                            "upstream response was not JSON",
                        ) from exc
                    choices = data.get("choices") or []
                    if not choices:
                        raise ModelBackendError(
                            ClientErrorCode.BACKEND_PROTOCOL_ERROR,
                            "upstream response contained no choices",
                        )
                    choice = choices[0]
                    message = choice.get("message") or {}
                    raw_text = str(message.get("content") or "")
                    finish_reason = choice.get("finish_reason")
            values, parser_mode = parse_options(raw_text)
            details = parse_document_details(raw_text)
            self._observations.put(
                request_id,
                AdapterObservation(
                    request_id=request_id,
                    model_id=self.model,
                    runtime_id=self.runtime_id,
                    parser_mode=parser_mode,
                    parser_version=details.get("parserVersion"),
                    parsed_count=len(values),
                    finish_reason=str(finish_reason) if finish_reason is not None else None,
                    output_chars=len(raw_text),
                    output_sha256=_sha256(raw_text),
                    elapsed_ms=round((time.monotonic() - started) * 1000.0, 3),
                    raw_text=(
                        raw_text[:MAX_CAPTURED_RAW_TEXT_CHARS]
                        if self.capture_raw_text
                        else None
                    ),
                ),
            )
            return values[: prompt.candidate_budget]
        except asyncio.CancelledError:
            raise
        except ModelBackendError:
            raise
        except TimeoutError as exc:
            raise ModelBackendError(
                ClientErrorCode.MODEL_TIMEOUT,
                "upstream request timed out",
                retryable=True,
            ) from exc
        except Exception as exc:
            raise ModelBackendError(
                ClientErrorCode.MODEL_UNAVAILABLE,
                f"adapter failure: {type(exc).__name__}",
                retryable=True,
            ) from exc
        finally:
            if current is not None:
                active = self._tasks.get(request_id)
                if active is not None:
                    active.discard(current)
                    if not active:
                        self._tasks.pop(request_id, None)

    async def cancel(self, request_id: str) -> None:
        for task in tuple(self._tasks.get(request_id, set())):
            if not task.done():
                task.cancel()


__all__ = [
    "MAX_CAPTURED_RAW_TEXT_CHARS",
    "MAX_UPSTREAM_ERROR_DIAGNOSTIC_BYTES",
    "AdapterObservation",
    "OpenAIChatLaneAdapter",
]
