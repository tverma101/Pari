#!/usr/bin/env python3
"""Authenticated, bounded SSE service for the Pari Word Studio engine.

The outer service is the only component intended to face an external tunnel.
Model servers remain loopback-only. The service exposes minimal liveness,
authenticated detailed diagnostics, one structured transform route, and an
authenticated cancellation route.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

try:
    from fastapi import FastAPI, Header, Request
    from fastapi.responses import JSONResponse, StreamingResponse
except ImportError as exc:  # pragma: no cover - live serving environment only
    raise RuntimeError("FastAPI is required only for the live Studio service environment") from exc

from word_studio_output_parser import PARSER_VERSION  # type: ignore[import-not-found]

from .engine import StudioEngine
from .errors import (
    ClientErrorCode,
    ServiceLimitError,
    ServiceRequestError,
    error_code_for_exception,
    error_event,
    internal_diagnostic_fields,
)
from .openai_adapter import OpenAIChatLaneAdapter
from .prompting import PROMPT_CONTRACT_VERSION
from .range_encoding import RANGE_ENCODING_VERSION, REQUEST_CONTRACT_VERSION
from .service_limits import (
    ServiceLimits,
    read_limited_json_body,
    studio_request_from_wire,
)
from .telemetry import LaneTelemetry, RequestTelemetry, RequestTelemetryStore, log_internal, request_tag


LOGGER = logging.getLogger("pari.studio.service")
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass
class ActiveRequestRegistry:
    """Server-issued execution IDs prevent requestId reuse cross-cancels.

    Issue #50's request-ID collision rule: the caller keeps a correlation ID and
    the server mints a fresh ``executionId`` per admission. Two live requests
    that reuse one correlation ID cannot overwrite or cross-cancel each other:
    the second is refused with HTTP 409 before an execution ID is reserved, and
    the first keeps the reservation until its own cleanup runs. ``release``
    matches on ``(request_id, execution_id)``, so a late cleanup from a finished
    request can never clear a newer request that reused the same ID.
    """

    _by_request: dict[str, str] = field(default_factory=dict)
    _by_execution: dict[str, str] = field(default_factory=dict)

    def reserve(self, request_id: str, execution_id: str) -> None:
        if request_id in self._by_request:
            raise ServiceRequestError("requestIdActive")
        self._by_request[request_id] = execution_id
        self._by_execution[execution_id] = request_id

    def release(self, request_id: str, execution_id: str) -> None:
        if self._by_request.get(request_id) == execution_id:
            self._by_request.pop(request_id, None)
        if self._by_execution.get(execution_id) == request_id:
            self._by_execution.pop(execution_id, None)

    def active_for(self, request_id: str) -> str | None:
        return self._by_request.get(request_id)

    def __len__(self) -> int:
        return len(self._by_execution)


@dataclass
class ServiceRuntime:
    limits: ServiceLimits
    telemetry: RequestTelemetryStore
    engine: StudioEngine | Any | None = None
    engine_factory: Callable[["ServiceRuntime"], StudioEngine | Any] | None = None
    active: ActiveRequestRegistry = field(default_factory=ActiveRequestRegistry)
    request_gate: asyncio.Semaphore = field(init=False)
    connection_gate: asyncio.Semaphore = field(init=False)
    queued_gate: asyncio.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        self.request_gate = asyncio.Semaphore(self.limits.max_concurrent_requests)
        self.connection_gate = asyncio.Semaphore(self.limits.max_sse_connections)
        # Bounds how many distinct requests may be parked on the admission
        # semaphores so abandoned clients cannot grow the active registry and
        # telemetry store without limit.
        self.queued_gate = asyncio.Semaphore(
            self.limits.max_concurrent_requests + self.limits.max_queued_requests
        )

    def resolve_engine(self) -> StudioEngine | Any:
        if self.engine is None:
            factory = self.engine_factory or default_engine
            self.engine = factory(self)
        return self.engine


def default_engine(limits: ServiceLimits) -> StudioEngine:
    fast_endpoint = os.environ.get("PARI_FAST_ENDPOINT", "http://127.0.0.1:8000")
    diversity_endpoint = os.environ.get("PARI_DIVERSITY_ENDPOINT", "http://127.0.0.1:8001")
    fast_model = os.environ.get("PARI_FAST_MODEL")
    diversity_model = os.environ.get("PARI_DIVERSITY_MODEL") or fast_model
    if not fast_model or not diversity_model:
        raise RuntimeError(
            "PARI_FAST_MODEL and PARI_DIVERSITY_MODEL (or shared model) must be configured"
        )
    fast_runtime = os.environ.get("PARI_FAST_RUNTIME_ID") or fast_model
    diversity_runtime = os.environ.get("PARI_DIVERSITY_RUNTIME_ID") or fast_runtime
    fast = OpenAIChatLaneAdapter(
        fast_endpoint,
        fast_model,
        runtime_id=fast_runtime,
        observation_entries=limits.observation_entries,
        observation_ttl_seconds=limits.observation_ttl_seconds,
    )
    diversity = OpenAIChatLaneAdapter(
        diversity_endpoint,
        diversity_model,
        runtime_id=diversity_runtime,
        observation_entries=limits.observation_entries,
        observation_ttl_seconds=limits.observation_ttl_seconds,
    )
    return StudioEngine(fast, diversity)


def default_runtime() -> ServiceRuntime:
    limits = ServiceLimits.from_env()
    service_id = os.environ.get("PARI_STUDIO_SERVICE_ID", "pari-word-studio-unselected")
    return ServiceRuntime(
        limits=limits,
        telemetry=RequestTelemetryStore(
            service_id=service_id,
            max_entries=limits.telemetry_entries,
            ttl_seconds=limits.telemetry_ttl_seconds,
        ),
    )


def _is_loopback_host(host: str | None) -> bool:
    return str(host or "").lower() in _LOOPBACK_HOSTS


def _forwarded_headers_present(request: Request) -> bool:
    return any(
        request.headers.get(name)
        for name in (
            "forwarded",
            "x-forwarded-for",
            "x-forwarded-host",
            "x-forwarded-proto",
            "x-real-ip",
        )
    )


def _request_is_loopback(request: Request) -> bool:
    client = request.client
    return bool(client and _is_loopback_host(client.host) and not _forwarded_headers_present(request))


def validate_startup_auth() -> None:
    """Fail closed when the service would expose unauthenticated endpoints.

    A missing bind/exposure declaration is treated as loopback because that is
    uvicorn's own default, but any declared non-loopback bind or non-loopback
    exposure mode requires a non-empty bearer token before startup. The
    unauthenticated development flag is never a generic auth-disable switch.
    """
    if os.environ.get("PARI_STUDIO_TOKEN"):
        return
    exposure_mode = os.environ.get("PARI_STUDIO_EXPOSURE_MODE", "loopback").strip().lower()
    bind_host = os.environ.get("PARI_STUDIO_SERVICE_HOST")
    if exposure_mode != "loopback" or (bind_host is not None and not _is_loopback_host(bind_host)):
        raise RuntimeError(
            "PARI_STUDIO_TOKEN is required when the Studio service is not loopback-only"
        )
    if os.environ.get("PARI_ALLOW_UNAUTHENTICATED_LOOPBACK") != "1":
        # Without a token and without the explicit development opt-in there is
        # no way to authenticate any caller, so refuse to start rather than
        # serving a permanently unauthorized surface.
        raise RuntimeError(
            "PARI_STUDIO_TOKEN or PARI_ALLOW_UNAUTHENTICATED_LOOPBACK=1 is required"
        )


def _authorized(request: Request, authorization: str | None) -> bool:
    token = os.environ.get("PARI_STUDIO_TOKEN")
    if token:
        supplied = authorization or ""
        expected = f"Bearer {token}"
        return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))

    # Unauthenticated access is a deliberate loopback-only development mode.
    # It requires the explicit opt-in flag, a loopback bind (or no declared
    # bind at all, which uvicorn treats as loopback), a loopback transport peer,
    # and no forwarding headers that could hide a remote client.
    exposure_mode = os.environ.get("PARI_STUDIO_EXPOSURE_MODE", "loopback").strip().lower()
    bind_host = os.environ.get("PARI_STUDIO_SERVICE_HOST")
    if bind_host is not None and not _is_loopback_host(bind_host):
        return False
    return (
        exposure_mode == "loopback"
        and os.environ.get("PARI_ALLOW_UNAUTHENTICATED_LOOPBACK") == "1"
        and _request_is_loopback(request)
    )


def _json_error(
    code: ClientErrorCode,
    status_code: int,
    *,
    request_id: str | None = None,
    execution_id: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "version": 1,
            "type": "error",
            "error": error_event(code, request_id=request_id, execution_id=execution_id)["error"],
        },
        headers=dict(headers or {}),
    )


def _runtime_identity(runtime: ServiceRuntime) -> dict[str, Any]:
    return {
        "serviceId": runtime.telemetry.service_id,
        "fastModelId": os.environ.get("PARI_FAST_MODEL"),
        "diversityModelId": os.environ.get("PARI_DIVERSITY_MODEL")
        or os.environ.get("PARI_FAST_MODEL"),
        "fastRuntimeId": os.environ.get("PARI_FAST_RUNTIME_ID")
        or os.environ.get("PARI_FAST_MODEL"),
        "diversityRuntimeId": os.environ.get("PARI_DIVERSITY_RUNTIME_ID")
        or os.environ.get("PARI_DIVERSITY_MODEL")
        or os.environ.get("PARI_FAST_MODEL"),
        "fastEndpoint": os.environ.get("PARI_FAST_ENDPOINT", "http://127.0.0.1:8000"),
        "diversityEndpoint": os.environ.get(
            "PARI_DIVERSITY_ENDPOINT", "http://127.0.0.1:8001"
        ),
        "promptContractVersion": PROMPT_CONTRACT_VERSION,
        "parserVersion": PARSER_VERSION,
        "exposureMode": os.environ.get("PARI_STUDIO_EXPOSURE_MODE", "external"),
        "authenticationConfigured": bool(os.environ.get("PARI_STUDIO_TOKEN")),
    }


def _limits_wire(limits: ServiceLimits) -> dict[str, Any]:
    return {
        "maxBodyBytes": limits.max_body_bytes,
        "maxDocumentChars": limits.max_document_chars,
        "maxDocumentBytes": limits.max_document_bytes,
        "maxRequestIdChars": limits.max_request_id_chars,
        "maxRevisionChars": limits.max_revision_chars,
        "maxProtectedSpans": limits.max_protected_spans,
        "maxProtectedSpanTextChars": limits.max_protected_span_text_chars,
        "maxProtectedMetadataBytes": limits.max_protected_metadata_bytes,
        "maxTargetWords": limits.max_target_words,
        "maxRequestedCandidates": limits.max_requested_candidates,
        "maxContextWindowChars": limits.max_context_window_chars,
        "maxQueuedRequests": limits.max_queued_requests,
        "maxSseEventBytes": limits.max_sse_event_bytes,
        "maxSseEvents": limits.max_sse_events,
        "maxSseQueue": limits.max_sse_queue,
        "maxConcurrentRequests": limits.max_concurrent_requests,
        "maxSseConnections": limits.max_sse_connections,
        "queueWaitSeconds": limits.queue_wait_seconds,
        "cancelTimeoutSeconds": limits.cancel_timeout_seconds,
        "heartbeatSeconds": limits.heartbeat_seconds,
        "requestTimeoutSeconds": limits.request_timeout_seconds,
        "telemetryEntries": limits.telemetry_entries,
        "telemetryTtlSeconds": limits.telemetry_ttl_seconds,
        "observationEntries": limits.observation_entries,
        "observationTtlSeconds": limits.observation_ttl_seconds,
    }


def _lane_telemetry_from_diagnostic(
    telemetry: RequestTelemetry,
    diagnostic: Mapping[str, Any],
) -> None:
    lane_name = str(diagnostic.get("lane") or "unknown")
    lane = telemetry.lanes.setdefault(lane_name, LaneTelemetry(lane=lane_name))
    lane.model_id = diagnostic.get("modelId") or lane.model_id
    lane.runtime_id = diagnostic.get("runtimeId") or lane.runtime_id
    lane.state = str(diagnostic.get("state") or lane.state)
    lane.parser_mode = diagnostic.get("parserMode") or lane.parser_mode
    lane.parsed_count = int(diagnostic.get("parsedCount") or 0)
    lane.accepted_count = int(diagnostic.get("acceptedCount") or 0)
    lane.gate_rejected_count = int(diagnostic.get("gateRejectedCount") or 0)
    lane.finish_reason = diagnostic.get("finishReason") or lane.finish_reason
    lane.error_code = diagnostic.get("errorCode") or lane.error_code
    lane.failure_class = diagnostic.get("failureClass") or lane.failure_class
    lane.output_chars = int(diagnostic.get("outputChars") or 0)
    lane.output_sha256 = diagnostic.get("outputSha256") or lane.output_sha256
    lane.elapsed_ms = (
        float(diagnostic["elapsedMs"])
        if diagnostic.get("elapsedMs") is not None
        else lane.elapsed_ms
    )


def _batch_wire(
    batch: Any,
    *,
    identity: Any,
    execution_id: str,
) -> dict[str, Any]:
    candidate_payloads = [
        {
            "text": candidate.text,
            "lane": candidate.lane.value,
            "family": candidate.family,
            "generationIndex": candidate.generation_index,
            "modelId": candidate.model_id,
            "runtimeId": candidate.runtime_id,
            "rawScore": candidate.raw_score,
        }
        for candidate in batch.candidates
    ]
    return {
        "version": 1,
        "requestId": batch.request_id,
        "executionId": execution_id,
        "identity": identity.to_wire(),
        # Issue #50 stale-response contract: every candidate batch repeats the
        # wire contract version and the immutable source identity of the request
        # that produced it, so the client can discard a batch whose document or
        # selection no longer matches what it is showing even when the sequence
        # numbers are perfect. ``documentRevision`` is the client's own opaque
        # revision token, carried verbatim rather than digested, so a client
        # that tracks revisions can compare it exactly and one that does not can
        # ignore it.
        "contractVersion": REQUEST_CONTRACT_VERSION,
        "rangeEncoding": RANGE_ENCODING_VERSION,
        "documentSha256": identity.source_sha256,
        "documentRevision": identity.document_revision,
        "selectionSha256": identity.selection_sha256,
        "sequence": batch.sequence,
        # Candidate events are cumulative ranked snapshots, not deltas. The
        # client replaces its visible option list through ``replaceThroughRank``
        # and can prove the terminal set from the final event without
        # text-based dedupe.
        "deliveryMode": "snapshot",
        "replaceThroughRank": len(candidate_payloads),
        "cumulativeUniqueCount": batch.cumulative_unique_count,
        "candidateCount": len(candidate_payloads),
        "final": batch.final,
        "cancelled": batch.cancelled,
        "cancelReason": batch.cancel_reason,
        "candidates": candidate_payloads,
        "diagnostics": list(batch.diagnostics),
        "errors": list(batch.errors),
    }


def _encode_sse(event: str, payload: Mapping[str, Any], limit: int) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    raw = f"event: {event}\ndata: {data}\n\n".encode("utf-8")
    if len(raw) > limit:
        raise ServiceLimitError("sseEventBytes", limit)
    return raw


def _threshold_crossings(
    previous: tuple[int | None, int | None, int | None],
    current_count: int,
    timings: tuple[float | None, float | None, float | None],
) -> list[int]:
    crossings: list[int] = []
    for threshold, before, timing in zip((1, 3, 10), previous, timings):
        if before is None and current_count >= threshold and timing is not None:
            crossings.append(threshold)
    return crossings


def _lane_failure_client_code(
    errors: tuple[dict[str, Any], ...],
) -> ClientErrorCode:
    """Pick one stable client error code for a fully failed generation."""
    codes = [
        str(error.get("code"))
        for error in errors
        if isinstance(error, Mapping) and error.get("code")
    ]
    for code in codes:
        try:
            return ClientErrorCode(code)
        except ValueError:
            continue
    return ClientErrorCode.BACKEND_PROTOCOL_ERROR


async def _pump_engine_stream(
    stream: Any,
    queue: asyncio.Queue[Any],
    *,
    on_error: Callable[[BaseException], None],
    finished: asyncio.Event,
) -> None:
    """Forward engine batches into a bounded SSE queue.

    Completion is published through ``finished`` rather than a sentinel item so
    an abandoned consumer can never deadlock the pump: a cancelled pump no
    longer has to enqueue into a queue nobody is draining, so ``gather`` in the
    owner's ``finally`` always settles and the admission gates are released.
    """
    try:
        async for batch in stream:
            await queue.put(batch)
    except asyncio.CancelledError:
        raise
    except BaseException as exc:
        on_error(exc)
    finally:
        finished.set()


async def _next_stream_item(
    queue: asyncio.Queue[Any],
    finished: asyncio.Event,
    wait_seconds: float,
) -> tuple[str, Any]:
    """Wait for the next queue item, pump completion, or a heartbeat.

    Returns ``("item", batch)``, ``("done", None)`` or ``("timeout", None)``.
    Queued batches win over pump completion so a batch produced in the same
    event-loop tick as the terminal transition is never dropped.
    """
    getter = asyncio.ensure_future(queue.get())
    waiter = asyncio.ensure_future(finished.wait())
    try:
        await asyncio.wait(
            {getter, waiter},
            timeout=wait_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        getter.cancel()
        waiter.cancel()
    if getter.done() and not getter.cancelled():
        return "item", getter.result()
    if not queue.empty():
        return "item", queue.get_nowait()
    if finished.is_set():
        return "done", None
    return "timeout", None


async def _cancel_owned(
    engine: Any,
    request_id: str,
    reason: str,
    execution_id: str,
    timeout_seconds: float,
) -> None:
    """Cancel exactly one owned generation, bounded in time and never raising.

    Cancellation must never be able to strand the admission gates, the active
    registry entry, or the SSE pump task, so failures are logged with a hashed
    request tag only and swallowed.
    """
    try:
        await asyncio.wait_for(
            engine.cancel(
                request_id,
                reason=reason,
                generation_id=execution_id,
            ),
            timeout=max(0.001, float(timeout_seconds)),
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log_internal(
            LOGGER,
            "studio_owned_cancel_failed",
            level=logging.WARNING,
            executionId=execution_id,
            requestTag=request_tag(request_id),
            cancellationReason=reason,
            **internal_diagnostic_fields(exc),
        )


def create_app(runtime: ServiceRuntime | None = None) -> FastAPI:
    state = runtime or default_runtime()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # Runs in the ASGI lifespan, not at import time, so importing the module
        # for tests or tooling never depends on deployment environment variables.
        validate_startup_auth()
        yield

    app = FastAPI(title="Pari Word Studio", version="0.3.0", lifespan=lifespan)
    app.state.studio_runtime = state

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/studio/diagnostics")
    async def diagnostics(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        if not _authorized(request, authorization):
            return _json_error(
                ClientErrorCode.UNAUTHORIZED,
                401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        adapters = None
        try:
            adapters = getattr(state.resolve_engine(), "observation_counts", None)
        except Exception:
            adapters = None
        return {
            "version": 1,
            "runtime": _runtime_identity(state),
            "limits": _limits_wire(state.limits),
            "activeRequestCount": len(state.active),
            "activeRequests": state.telemetry.active(),
            "recentRequests": state.telemetry.recent(limit=20),
            "adapterObservationCount": adapters() if callable(adapters) else None,
        }

    @app.post("/v1/studio/transform")
    async def transform(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        if not _authorized(request, authorization):
            return _json_error(
                ClientErrorCode.UNAUTHORIZED,
                401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            body = await read_limited_json_body(request, state.limits)
            parsed = studio_request_from_wire(body, state.limits)
        except ServiceLimitError as exc:
            log_internal(
                LOGGER,
                "studio_request_rejected",
                level=logging.INFO,
                field=exc.field,
                limit=exc.limit,
                errorCode=ClientErrorCode.RESOURCE_LIMIT.value,
            )
            return _json_error(ClientErrorCode.RESOURCE_LIMIT, 413)
        except ServiceRequestError as exc:
            log_internal(
                LOGGER,
                "studio_request_rejected",
                level=logging.INFO,
                field=exc.field,
                errorCode=ClientErrorCode.INVALID_REQUEST.value,
            )
            return _json_error(ClientErrorCode.INVALID_REQUEST, 400)

        # Bound the number of distinct requests that may wait for admission.
        # This must happen before reserving an execution ID or creating
        # telemetry, so a flood of unique request IDs cannot grow either store.
        if state.queued_gate.locked():
            return _json_error(ClientErrorCode.RESOURCE_LIMIT, 429)
        await state.queued_gate.acquire()

        execution_id = uuid.uuid4().hex
        try:
            state.active.reserve(parsed.identity.request_id, execution_id)
        except ServiceRequestError:
            state.queued_gate.release()
            return _json_error(
                ClientErrorCode.INVALID_REQUEST,
                409,
                request_id=parsed.identity.request_id,
            )

        telemetry = RequestTelemetry(
            service_id=state.telemetry.service_id,
            execution_id=execution_id,
            request_tag=request_tag(parsed.identity.request_id),
            operation=parsed.request.operation.value,
            source_sha256=parsed.identity.source_sha256,
            selection_sha256=parsed.identity.selection_sha256,
            selection_start=parsed.identity.selection_start,
            selection_end=parsed.identity.selection_end,
            requested_candidates=parsed.request.requested_candidates,
        )
        try:
            state.telemetry.create(telemetry)
        except BaseException:
            state.active.release(parsed.identity.request_id, execution_id)
            state.queued_gate.release()
            raise
        try:
            engine = state.resolve_engine()
        except asyncio.CancelledError:
            state.active.release(parsed.identity.request_id, execution_id)
            state.queued_gate.release()
            telemetry.cancellation_reason = "request_cancelled_before_admission"
            telemetry.finish("cancelled", error_code=ClientErrorCode.CANCELLED.value)
            raise
        except Exception as exc:
            state.active.release(parsed.identity.request_id, execution_id)
            state.queued_gate.release()
            telemetry.failure_class = type(exc).__name__
            telemetry.finish(
                "failed",
                error_code=error_code_for_exception(exc).value,
            )
            log_internal(
                LOGGER,
                "studio_engine_initialization_failed",
                level=logging.ERROR,
                executionId=execution_id,
                requestTag=telemetry.request_tag,
                **internal_diagnostic_fields(exc),
            )
            return _json_error(
                error_code_for_exception(exc),
                503,
                request_id=parsed.identity.request_id,
                execution_id=execution_id,
            )

        request_slot_acquired = False
        connection_slot_acquired = False
        try:
            await asyncio.wait_for(
                state.request_gate.acquire(),
                timeout=state.limits.queue_wait_seconds,
            )
            request_slot_acquired = True
            await asyncio.wait_for(
                state.connection_gate.acquire(),
                timeout=state.limits.queue_wait_seconds,
            )
            connection_slot_acquired = True
        except asyncio.CancelledError:
            if request_slot_acquired:
                state.request_gate.release()
            if connection_slot_acquired:
                state.connection_gate.release()
            state.active.release(parsed.identity.request_id, execution_id)
            state.queued_gate.release()
            telemetry.queue_wait_ms = telemetry.elapsed_ms()
            telemetry.cancellation_reason = "request_cancelled_while_queued"
            telemetry.finish("cancelled", error_code=ClientErrorCode.CANCELLED.value)
            raise
        except TimeoutError:
            if request_slot_acquired:
                state.request_gate.release()
            if connection_slot_acquired:
                state.connection_gate.release()
            state.active.release(parsed.identity.request_id, execution_id)
            state.queued_gate.release()
            telemetry.queue_wait_ms = telemetry.elapsed_ms()
            telemetry.failure_class = "AdmissionQueueTimeout"
            telemetry.finish(
                "failed",
                error_code=ClientErrorCode.RESOURCE_LIMIT.value,
            )
            return _json_error(
                ClientErrorCode.RESOURCE_LIMIT,
                429,
                request_id=parsed.identity.request_id,
                execution_id=execution_id,
            )

        telemetry.admit()

        async def event_stream():
            queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=state.limits.max_sse_queue)
            pump_task: asyncio.Task[None] | None = None
            pump_finished = asyncio.Event()
            pump_error: list[BaseException] = []
            terminal = False
            event_count = 0
            last_sequence = 0
            deadline = time.monotonic() + state.limits.request_timeout_seconds

            pump_task = asyncio.create_task(
                _pump_engine_stream(
                    engine.stream(
                        parsed.request,
                        generation_id=execution_id,
                    ),
                    queue,
                    on_error=pump_error.append,
                    finished=pump_finished,
                )
            )

            async def emit(event: str, payload: Mapping[str, Any]) -> bytes | None:
                nonlocal event_count, terminal
                event_count += 1
                if event_count > state.limits.max_sse_events:
                    terminal = True
                    await _cancel_owned(
                        engine,
                        parsed.identity.request_id,
                        "sse_event_limit",
                        execution_id,
                        state.limits.cancel_timeout_seconds,
                    )
                    telemetry.cancellation_reason = "sse_event_limit"
                    return _encode_sse(
                        "error",
                        error_event(
                            ClientErrorCode.RESOURCE_LIMIT,
                            request_id=parsed.identity.request_id,
                            execution_id=execution_id,
                        ),
                        state.limits.max_sse_event_bytes,
                    )
                try:
                    return _encode_sse(event, payload, state.limits.max_sse_event_bytes)
                except ServiceLimitError:
                    terminal = True
                    await _cancel_owned(
                        engine,
                        parsed.identity.request_id,
                        "sse_event_limit",
                        execution_id,
                        state.limits.cancel_timeout_seconds,
                    )
                    telemetry.cancellation_reason = "sse_event_limit"
                    return _encode_sse(
                        "error",
                        error_event(
                            ClientErrorCode.RESOURCE_LIMIT,
                            request_id=parsed.identity.request_id,
                            execution_id=execution_id,
                        ),
                        state.limits.max_sse_event_bytes,
                    )

            try:
                accepted = {
                    "version": 1,
                    "type": "accepted",
                    "requestId": parsed.identity.request_id,
                    "executionId": execution_id,
                    "identity": parsed.identity.to_wire(),
                    # The client opens its stream guard from this event. The
                    # explicit contract/version/digest fields are repeated at
                    # the top level (not only inside ``identity``) so a client
                    # can bind the stream without knowing the nested shape, and
                    # so every later batch can be compared field for field.
                    "contractVersion": REQUEST_CONTRACT_VERSION,
                    "rangeEncoding": RANGE_ENCODING_VERSION,
                    "documentSha256": parsed.identity.source_sha256,
                    "documentRevision": parsed.identity.document_revision,
                    "selectionSha256": parsed.identity.selection_sha256,
                    "selection": {
                        "start": parsed.identity.selection_start,
                        "end": parsed.identity.selection_end,
                    },
                    "operation": parsed.request.operation.value,
                    "requestedCandidates": parsed.request.requested_candidates,
                    "service": {
                        "serviceId": state.telemetry.service_id,
                        "promptContractVersion": PROMPT_CONTRACT_VERSION,
                        "parserVersion": PARSER_VERSION,
                    },
                    "timings": {
                        "queueWaitMs": telemetry.queue_wait_ms,
                        "acceptedMs": telemetry.accepted_ms,
                    },
                }
                yield (await emit("accepted", accepted) or b"").decode("utf-8")

                while True:
                    if await request.is_disconnected():
                        telemetry.client_disconnected = True
                        telemetry.cancellation_reason = "client_disconnect"
                        await _cancel_owned(
                            engine,
                            parsed.identity.request_id,
                            "client_disconnect",
                            execution_id,
                            state.limits.cancel_timeout_seconds,
                        )
                        terminal = True
                        break

                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        await _cancel_owned(
                            engine,
                            parsed.identity.request_id,
                            "server_timeout",
                            execution_id,
                            state.limits.cancel_timeout_seconds,
                        )
                        telemetry.cancellation_reason = "server_timeout"
                        terminal = True
                        yield (
                            await emit(
                                "error",
                                error_event(
                                    ClientErrorCode.MODEL_TIMEOUT,
                                    request_id=parsed.identity.request_id,
                                    execution_id=execution_id,
                                    retryable=True,
                                ),
                            )
                            or b""
                        ).decode("utf-8")
                        telemetry.finish("failed", error_code=ClientErrorCode.MODEL_TIMEOUT.value)
                        break

                    wait_seconds = min(state.limits.heartbeat_seconds, remaining)
                    item_kind, item = await _next_stream_item(
                        queue, pump_finished, wait_seconds
                    )
                    if item_kind == "timeout":
                        yield ": keep-alive\n\n"
                        continue

                    if item_kind == "done":
                        if pump_error:
                            item = pump_error[0]
                        else:
                            telemetry.failure_class = "UnexpectedStreamEnd"
                            telemetry.finish(
                                "failed",
                                error_code=ClientErrorCode.BACKEND_PROTOCOL_ERROR.value,
                            )
                            terminal = True
                            yield (
                                await emit(
                                    "error",
                                    error_event(
                                        ClientErrorCode.BACKEND_PROTOCOL_ERROR,
                                        request_id=parsed.identity.request_id,
                                        execution_id=execution_id,
                                    ),
                                )
                                or b""
                            ).decode("utf-8")
                            break
                    if isinstance(item, BaseException):
                        code = error_code_for_exception(item)
                        terminal = True
                        telemetry.failure_class = type(item).__name__
                        telemetry.finish("failed", error_code=code.value)
                        log_internal(
                            LOGGER,
                            "studio_request_failed",
                            level=logging.WARNING,
                            executionId=execution_id,
                            requestTag=telemetry.request_tag,
                            **internal_diagnostic_fields(item),
                        )
                        yield (
                            await emit(
                                "error",
                                error_event(
                                    code,
                                    request_id=parsed.identity.request_id,
                                    execution_id=execution_id,
                                    retryable=(
                                        True
                                        if code
                                        in {
                                            ClientErrorCode.MODEL_TIMEOUT,
                                            ClientErrorCode.MODEL_UNAVAILABLE,
                                        }
                                        else None
                                    ),
                                ),
                            )
                            or b""
                        ).decode("utf-8")
                        break

                    batch = item
                    if batch.sequence <= last_sequence or batch.sequence != last_sequence + 1:
                        # A gapped or repeated sequence means the engine contract
                        # is broken; do not let the UI apply a partial stream.
                        terminal = True
                        await _cancel_owned(
                            engine,
                            parsed.identity.request_id,
                            "sequence_violation",
                            execution_id,
                            state.limits.cancel_timeout_seconds,
                        )
                        telemetry.cancellation_reason = "sequence_violation"
                        telemetry.finish(
                            "failed", error_code=ClientErrorCode.BACKEND_PROTOCOL_ERROR.value
                        )
                        yield (
                            await emit(
                                "error",
                                error_event(
                                    ClientErrorCode.BACKEND_PROTOCOL_ERROR,
                                    request_id=parsed.identity.request_id,
                                    execution_id=execution_id,
                                ),
                            )
                            or b""
                        ).decode("utf-8")
                        break
                    last_sequence = batch.sequence
                    for diagnostic in batch.diagnostics:
                        if diagnostic.get("type") == "lane":
                            _lane_telemetry_from_diagnostic(telemetry, diagnostic)
                        duplicate_count = diagnostic.get("duplicateRejectedCount")
                        if duplicate_count is not None:
                            telemetry.duplicate_rejection_count = max(
                                telemetry.duplicate_rejection_count,
                                int(duplicate_count),
                            )
                    for error in batch.errors:
                        telemetry.lane_failure_count += 1
                        telemetry.failure_class = str(error.get("failureClass") or telemetry.failure_class or "")
                    telemetry.gate_rejection_count = sum(
                        lane.gate_rejected_count for lane in telemetry.lanes.values()
                    )
                    telemetry.parser_failure_count = sum(
                        1
                        for lane in telemetry.lanes.values()
                        if lane.state == "completed" and lane.parser_mode in {"unparseable", "empty_output"}
                    )

                    before = (
                        telemetry.first_candidate_ms,
                        telemetry.first_three_ms,
                        telemetry.first_ten_ms,
                    )
                    telemetry.observe_candidates(
                        len(batch.candidates), batch.cumulative_unique_count
                    )
                    after = (
                        telemetry.first_candidate_ms,
                        telemetry.first_three_ms,
                        telemetry.first_ten_ms,
                    )
                    for threshold in _threshold_crossings(before, len(batch.candidates), after):
                        timing = after[(1, 3, 10).index(threshold)]
                        milestone = {
                            "version": 1,
                            "type": "milestone",
                            "requestId": batch.request_id,
                            "executionId": execution_id,
                            # Milestones are part of the same stream, so they
                            # carry the same identity fields as a candidate
                            # batch; a client that checks identity on one event
                            # must not be able to skip the check on another.
                            "contractVersion": REQUEST_CONTRACT_VERSION,
                            "rangeEncoding": RANGE_ENCODING_VERSION,
                            "documentSha256": parsed.identity.source_sha256,
                            "documentRevision": parsed.identity.document_revision,
                            "selectionSha256": parsed.identity.selection_sha256,
                            "threshold": threshold,
                            # The milestone reports how many usable options the
                            # client has been given at this threshold, never the
                            # server's larger in-flight pool size.
                            "uniqueCandidateCount": threshold,
                            "elapsedMs": timing,
                        }
                        encoded = await emit("milestone", milestone)
                        if encoded:
                            yield encoded.decode("utf-8")
                        if terminal:
                            break
                    if terminal:
                        break

                    fully_failed_final = (
                        batch.final
                        and batch.cumulative_unique_count == 0
                        and telemetry.lane_failure_count > 0
                    )
                    if fully_failed_final:
                        # Do not emit an empty "completion" before the error: the
                        # client must see one terminal failure event, not a
                        # success-looking completion followed by an error.
                        failure_code = _lane_failure_client_code(batch.errors)
                        telemetry.finish("failed", error_code=failure_code.value)
                        terminal = True
                        yield (
                            await emit(
                                "error",
                                error_event(
                                    failure_code,
                                    request_id=parsed.identity.request_id,
                                    execution_id=execution_id,
                                    retryable=(
                                        True
                                        if failure_code
                                        in {
                                            ClientErrorCode.MODEL_TIMEOUT,
                                            ClientErrorCode.MODEL_UNAVAILABLE,
                                        }
                                        else None
                                    ),
                                ),
                            )
                            or b""
                        ).decode("utf-8")
                        break

                    payload = _batch_wire(
                        batch,
                        identity=parsed.identity,
                        execution_id=execution_id,
                    )
                    payload["type"] = (
                        "cancelled"
                        if batch.cancelled
                        else "completion"
                        if batch.final
                        else "candidates"
                        if batch.candidates
                        else "diagnostics"
                    )
                    payload["timings"] = {
                        "queueWaitMs": telemetry.queue_wait_ms,
                        "acceptedMs": telemetry.accepted_ms,
                        "firstCandidateMs": telemetry.first_candidate_ms,
                        "firstThreeMs": telemetry.first_three_ms,
                        "firstTenMs": telemetry.first_ten_ms,
                        "completionMs": telemetry.elapsed_ms(),
                    }
                    event_name = payload["type"]
                    encoded = await emit(event_name, payload)
                    if encoded:
                        yield encoded.decode("utf-8")
                    if terminal:
                        break

                    if batch.cancelled:
                        telemetry.cancellation_reason = batch.cancel_reason or "cancelled"
                        telemetry.finish("cancelled", error_code=ClientErrorCode.CANCELLED.value)
                        terminal = True
                        break
                    if batch.final:
                        telemetry.finish("completed")
                        terminal = True
                        break
            except asyncio.CancelledError:
                telemetry.cancellation_reason = telemetry.cancellation_reason or "service_disconnect"
                await _cancel_owned(
                    engine,
                    parsed.identity.request_id,
                    "service_disconnect",
                    execution_id,
                    state.limits.cancel_timeout_seconds,
                )
                raise
            finally:
                try:
                    if not terminal:
                        await _cancel_owned(
                            engine,
                            parsed.identity.request_id,
                            "service_disconnect",
                            execution_id,
                            state.limits.cancel_timeout_seconds,
                        )
                        if telemetry.state not in {"failed", "cancelled", "completed"}:
                            telemetry.finish(
                                "cancelled", error_code=ClientErrorCode.CANCELLED.value
                            )
                    if pump_task is not None and not pump_task.done():
                        pump_task.cancel()
                        try:
                            await asyncio.wait_for(
                                asyncio.gather(pump_task, return_exceptions=True),
                                timeout=state.limits.cancel_timeout_seconds,
                            )
                        except TimeoutError:
                            log_internal(
                                LOGGER,
                                "studio_pump_cleanup_timeout",
                                level=logging.WARNING,
                                executionId=execution_id,
                                requestTag=telemetry.request_tag,
                            )
                finally:
                    # Cleanup must run even if a cancel or pump await raised:
                    # leaking an admission slot would stall every later
                    # request, and leaking the reservation would 409 the same
                    # request ID forever.
                    state.active.release(parsed.identity.request_id, execution_id)
                    state.request_gate.release()
                    state.connection_gate.release()
                    state.queued_gate.release()

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/v1/studio/cancel/{request_id}")
    async def cancel(
        request_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        if not _authorized(request, authorization):
            return _json_error(
                ClientErrorCode.UNAUTHORIZED,
                401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        if len(request_id) > state.limits.max_request_id_chars or not _SAFE_REQUEST_ID.fullmatch(
            request_id
        ):
            return _json_error(ClientErrorCode.INVALID_REQUEST, 400)
        # The response is intentionally constant for unknown, already-completed,
        # and cancelled requests so the endpoint is not an existence oracle.
        active_execution = state.active.active_for(request_id)
        if active_execution is None:
            # Do not let unknown request IDs accumulate engine cancellation
            # tombstones. The response stays constant either way.
            return {"status": "accepted"}

        record = state.telemetry.get(active_execution)
        if record is not None:
            record.state = "cancelling"
            record.cancellation_reason = "client_cancelled"
        try:
            # Cancel the exact execution the client observed as active. A stale
            # cancel must never be able to kill a newer generation that reuses
            # the same external requestId.
            await asyncio.wait_for(
                state.resolve_engine().cancel(
                    request_id,
                    reason="client_cancelled",
                    generation_id=active_execution,
                ),
                timeout=state.limits.cancel_timeout_seconds,
            )
        except Exception as exc:
            log_internal(
                LOGGER,
                "studio_cancel_failed",
                level=logging.WARNING,
                executionId=active_execution,
                requestTag=request_tag(request_id),
                **internal_diagnostic_fields(exc),
            )
            return _json_error(
                ClientErrorCode.BACKEND_PROTOCOL_ERROR,
                500,
                request_id=request_id,
                execution_id=active_execution,
            )
        return {"status": "accepted"}

    return app


app = create_app()


__all__ = [
    "ActiveRequestRegistry",
    "ServiceRuntime",
    "app",
    "create_app",
    "default_engine",
    "default_runtime",
    "validate_startup_auth",
]
