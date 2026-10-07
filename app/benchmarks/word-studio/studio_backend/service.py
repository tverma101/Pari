#!/usr/bin/env python3
"""Authenticated SSE service for the model-agnostic Pari Word Studio engine.

Expected deployment: this service is the only component exposed through an
external authenticated tunnel. vLLM/llama.cpp model servers remain loopback-only.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import uuid
from functools import lru_cache
from typing import Any

try:
    from fastapi import FastAPI, Header, HTTPException, Request
    from fastapi.responses import StreamingResponse
except ImportError as exc:  # pragma: no cover - live serving environment only
    raise RuntimeError("FastAPI is required only for the live Studio service environment") from exc

from .contracts import Operation, ProtectedSpan, StudioRequest, TextRange
from .engine import StudioEngine
from .openai_adapter import OpenAIChatLaneAdapter


@lru_cache(maxsize=1)
def _engine() -> StudioEngine:
    fast_endpoint = os.environ.get("PARI_FAST_ENDPOINT", "http://127.0.0.1:8000")
    diversity_endpoint = os.environ.get("PARI_DIVERSITY_ENDPOINT", "http://127.0.0.1:8001")
    fast_model = os.environ.get("PARI_FAST_MODEL")
    diversity_model = os.environ.get("PARI_DIVERSITY_MODEL") or fast_model
    if not fast_model or not diversity_model:
        raise RuntimeError("PARI_FAST_MODEL and PARI_DIVERSITY_MODEL (or shared model) must be configured")
    fast = OpenAIChatLaneAdapter(fast_endpoint, fast_model)
    diversity = OpenAIChatLaneAdapter(diversity_endpoint, diversity_model)
    return StudioEngine(fast, diversity)


def _authorized(authorization: str | None) -> bool:
    token = os.environ.get("PARI_STUDIO_TOKEN")
    if not token:
        return os.environ.get("PARI_ALLOW_UNAUTHENTICATED_LOOPBACK") == "1"
    supplied = authorization or ""
    expected = f"Bearer {token}"
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))


def _request_from_wire(body: dict[str, Any]) -> StudioRequest:
    selection = body.get("selection") or {}
    protected = tuple(
        ProtectedSpan(
            text=str(row.get("text") or ""),
            start=int(row["start"]) if row.get("start") is not None else None,
            end=int(row["end"]) if row.get("end") is not None else None,
        )
        for row in (body.get("protectedSpans") or [])
        if isinstance(row, dict) and row.get("text")
    )
    request = StudioRequest(
        request_id=str(body.get("requestId") or "").strip() or uuid.uuid4().hex,
        document_text=str(body.get("documentText") or ""),
        selection=TextRange(int(selection.get("start", -1)), int(selection.get("end", -1))),
        operation=Operation(str(body.get("operation") or "replace")),
        strength=int(body.get("strength", 60)),
        requested_candidates=int(body.get("requestedCandidates", 40)),
        target_min_words=int(body["targetMinWords"]) if body.get("targetMinWords") is not None else None,
        target_max_words=int(body["targetMaxWords"]) if body.get("targetMaxWords") is not None else None,
        protected_spans=protected,
    )
    request.validate()
    return request


def _batch_to_wire(batch) -> dict[str, Any]:
    return {
        "version": 1,
        "requestId": batch.request_id,
        "sequence": batch.sequence,
        "cumulativeUniqueCount": batch.cumulative_unique_count,
        "final": batch.final,
        "cancelled": batch.cancelled,
        "candidates": [
            {
                "text": candidate.text,
                "lane": candidate.lane.value,
                "family": candidate.family,
                "generationIndex": candidate.generation_index,
                "modelId": candidate.model_id,
                "rawScore": candidate.raw_score,
            }
            for candidate in batch.candidates
        ],
    }


def create_app() -> FastAPI:
    app = FastAPI(title="Pari Word Studio", version="0.1.0")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "fastEndpoint": os.environ.get("PARI_FAST_ENDPOINT", "http://127.0.0.1:8000"),
            "diversityEndpoint": os.environ.get("PARI_DIVERSITY_ENDPOINT", "http://127.0.0.1:8001"),
            "fastModelConfigured": bool(os.environ.get("PARI_FAST_MODEL")),
            "diversityModelConfigured": bool(os.environ.get("PARI_DIVERSITY_MODEL") or os.environ.get("PARI_FAST_MODEL")),
            "authenticationConfigured": bool(os.environ.get("PARI_STUDIO_TOKEN")),
        }

    @app.post("/v1/studio/transform")
    async def transform(
        body: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> StreamingResponse:
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="unauthorized")
        try:
            studio_request = _request_from_wire(body)
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        engine = _engine()

        async def event_stream():
            try:
                async for batch in engine.stream(studio_request):
                    if await request.is_disconnected():
                        await engine.cancel(studio_request.request_id)
                        return
                    payload = json.dumps(_batch_to_wire(batch), ensure_ascii=False, separators=(",", ":"))
                    yield f"event: candidates\ndata: {payload}\n\n"
            except asyncio.CancelledError:
                await engine.cancel(studio_request.request_id)
                raise
            except Exception as exc:
                # Keep the event structured so the desktop can terminate the
                # interaction without interpreting a broken stream as no options.
                payload = json.dumps(
                    {
                        "version": 1,
                        "requestId": studio_request.request_id,
                        "type": "backend_error",
                        "errorClass": type(exc).__name__,
                        "message": str(exc)[:500],
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                yield f"event: error\ndata: {payload}\n\n"
            finally:
                if await request.is_disconnected():
                    await engine.cancel(studio_request.request_id)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/v1/studio/cancel/{request_id}")
    async def cancel(request_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        if not _authorized(authorization):
            raise HTTPException(status_code=401, detail="unauthorized")
        await _engine().cancel(request_id)
        return {"status": "cancelled", "requestId": request_id}

    return app


app = create_app()
