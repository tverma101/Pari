#!/usr/bin/env python3
"""Async adapter from a Studio lane to a local OpenAI-compatible model server.

The adapter intentionally permits loopback endpoints only. Exposing the outer
Studio service to the desktop app is a separate authenticated transport concern;
model servers themselves should remain private to the Kaggle runtime.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import urlparse

from .options import parse_options
from .prompting import CompiledPrompt


@dataclass(frozen=True)
class AdapterObservation:
    request_id: str
    parser_mode: str
    raw_text: str
    parsed_count: int
    finish_reason: str | None


class OpenAIChatLaneAdapter:
    def __init__(
        self,
        endpoint: str,
        model: str,
        *,
        timeout_seconds: float = 120.0,
        seed: int = 0,
    ) -> None:
        parsed = urlparse(endpoint)
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Studio model adapter endpoint must be loopback")
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.seed = seed
        self._tasks: dict[str, set[asyncio.Task]] = {}
        self.observations: dict[str, list[AdapterObservation]] = {}

    async def generate(self, prompt: CompiledPrompt, *, request_id: str) -> list[str]:
        try:
            import aiohttp
        except ImportError as exc:
            raise RuntimeError("aiohttp is required by the live Studio adapter; use the pinned serving environment") from exc

        current = asyncio.current_task()
        if current is not None:
            self._tasks.setdefault(request_id, set()).add(current)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt.system},
                {"role": "user", "content": prompt.user},
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
        raw_text = ""
        finish_reason = None
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self.endpoint + "/v1/chat/completions", json=payload) as response:
                    body = await response.text()
                    if response.status >= 400:
                        raise RuntimeError(f"model server HTTP {response.status}: {body[:500]}")
                    data = await response.json()
                    choices = data.get("choices") or []
                    if not choices:
                        raise RuntimeError("model server returned no choices")
                    choice = choices[0]
                    message = choice.get("message") or {}
                    raw_text = str(message.get("content") or "")
                    finish_reason = choice.get("finish_reason")
            values, parser_mode = parse_options(raw_text)
            self.observations.setdefault(request_id, []).append(
                AdapterObservation(
                    request_id=request_id,
                    parser_mode=parser_mode,
                    raw_text=raw_text,
                    parsed_count=len(values),
                    finish_reason=str(finish_reason) if finish_reason is not None else None,
                )
            )
            return values[: prompt.candidate_budget]
        finally:
            if current is not None:
                active = self._tasks.get(request_id)
                if active is not None:
                    active.discard(current)
                    if not active:
                        self._tasks.pop(request_id, None)

    async def cancel(self, request_id: str) -> None:
        # Cancelling the aiohttp request closes the client connection. vLLM can
        # observe the disconnected request and stop work; either way the Studio
        # engine guarantees no late result is delivered to the UI.
        for task in tuple(self._tasks.get(request_id, set())):
            if not task.done():
                task.cancel()
