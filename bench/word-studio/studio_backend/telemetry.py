#!/usr/bin/env python3
"""Bounded, text-free Studio service telemetry."""
from __future__ import annotations

import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator


def request_tag(request_id: str) -> str:
    return hashlib.sha256(request_id.encode("utf-8", "replace")).hexdigest()[:12]


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()


class BoundedStore:
    """Small TTL + LRU store for records that must not grow with traffic."""

    def __init__(
        self,
        *,
        max_entries: int,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self.max_entries = max_entries
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._clock = clock
        self._items: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def __len__(self) -> int:
        self._expire()
        return len(self._items)

    def _expire(self) -> None:
        if not self.ttl_seconds:
            return
        now = self._clock()
        # Entries are ordered by recency, not creation time, so the head may be
        # younger than an expired record further back. Scan the whole store.
        for key in [key for key, (created, _v) in self._items.items() if now - created > self.ttl_seconds]:
            self._items.pop(key, None)

    def put(self, key: str, value: Any) -> None:
        self._expire()
        self._items[key] = (self._clock(), value)
        self._items.move_to_end(key)
        while len(self._items) > self.max_entries:
            self._items.popitem(last=False)

    def get(self, key: str) -> Any | None:
        self._expire()
        item = self._items.get(key)
        if item is None:
            return None
        created, value = item
        if self.ttl_seconds and self._clock() - created > self.ttl_seconds:
            self._items.pop(key, None)
            return None
        self._items.move_to_end(key)
        return value

    def delete(self, key: str) -> None:
        self._items.pop(key, None)

    def values(self) -> list[Any]:
        self._expire()
        return [value for _created, value in self._items.values()]

    def items(self) -> Iterator[tuple[str, Any]]:
        self._expire()
        return iter([(key, value) for key, (_created, value) in self._items.items()])

    def clear(self) -> None:
        self._items.clear()


@dataclass
class LaneTelemetry:
    lane: str
    model_id: str | None = None
    runtime_id: str | None = None
    state: str = "pending"
    parser_mode: str | None = None
    parsed_count: int = 0
    accepted_count: int = 0
    gate_rejected_count: int = 0
    duplicate_rejected_count: int = 0
    output_chars: int = 0
    output_sha256: str | None = None
    finish_reason: str | None = None
    error_code: str | None = None
    failure_class: str | None = None
    elapsed_ms: float | None = None

    def to_wire(self) -> dict[str, Any]:
        return {
            "lane": self.lane,
            "modelId": self.model_id,
            "runtimeId": self.runtime_id,
            "state": self.state,
            "parserMode": self.parser_mode,
            "parsedCount": self.parsed_count,
            "acceptedCount": self.accepted_count,
            "gateRejectedCount": self.gate_rejected_count,
            "duplicateRejectedCount": self.duplicate_rejected_count,
            "outputChars": self.output_chars,
            "outputSha256": self.output_sha256,
            "finishReason": self.finish_reason,
            "errorCode": self.error_code,
            "failureClass": self.failure_class,
            "elapsedMs": self.elapsed_ms,
        }


@dataclass
class RequestTelemetry:
    service_id: str
    execution_id: str
    request_tag: str
    operation: str
    source_sha256: str
    selection_sha256: str
    selection_start: int
    selection_end: int
    requested_candidates: int
    state: str = "queued"
    lanes: dict[str, LaneTelemetry] = field(default_factory=dict)
    started_monotonic: float | None = None
    queue_wait_ms: float | None = None
    accepted_ms: float | None = None
    first_candidate_ms: float | None = None
    first_three_ms: float | None = None
    first_ten_ms: float | None = None
    completion_ms: float | None = None
    streamed_candidate_count: int = 0
    unique_candidate_count: int = 0
    parser_failure_count: int = 0
    gate_rejection_count: int = 0
    duplicate_rejection_count: int = 0
    lane_failure_count: int = 0
    cancellation_reason: str | None = None
    error_code: str | None = None
    failure_class: str | None = None
    client_disconnected: bool = False
    finish_reason: str | None = None
    clock: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        if self.started_monotonic is None:
            self.started_monotonic = self.clock()

    def elapsed_ms(self) -> float:
        return round((self.clock() - self.started_monotonic) * 1000.0, 3)

    def admit(self) -> None:
        """Record successful admission after both bounded gates are acquired."""
        self.queue_wait_ms = self.elapsed_ms()
        self.accepted_ms = self.queue_wait_ms
        self.state = "accepted"

    def observe_candidates(self, count: int, unique_count: int) -> None:
        now = self.elapsed_ms()
        if self.state in {"queued", "accepted"}:
            self.state = "streaming"
        if count >= 1 and self.first_candidate_ms is None:
            self.first_candidate_ms = now
        if count >= 3 and self.first_three_ms is None:
            self.first_three_ms = now
        if count >= 10 and self.first_ten_ms is None:
            self.first_ten_ms = now
        # Threshold batches are cumulative snapshots, so ``count`` is the number
        # of candidate objects visible in the latest event, not the number of
        # objects emitted so far.
        self.streamed_candidate_count = max(self.streamed_candidate_count, count)
        self.unique_candidate_count = max(self.unique_candidate_count, unique_count)

    def finish(self, state: str, *, error_code: str | None = None) -> None:
        self.state = state
        self.completion_ms = self.elapsed_ms()
        if error_code is not None:
            self.error_code = error_code

    def to_wire(self, *, include_lanes: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "serviceId": self.service_id,
            "executionId": self.execution_id,
            "requestTag": self.request_tag,
            "operation": self.operation,
            "sourceSha256": self.source_sha256,
            "selectionSha256": self.selection_sha256,
            "selection": {"start": self.selection_start, "end": self.selection_end},
            "requestedCandidates": self.requested_candidates,
            "state": self.state,
            "queueWaitMs": self.queue_wait_ms,
            "acceptedMs": self.accepted_ms,
            "firstCandidateMs": self.first_candidate_ms,
            "firstThreeMs": self.first_three_ms,
            "firstTenMs": self.first_ten_ms,
            "completionMs": self.completion_ms,
            "streamedCandidateCount": self.streamed_candidate_count,
            "uniqueCandidateCount": self.unique_candidate_count,
            "parserFailureCount": self.parser_failure_count,
            "gateRejectionCount": self.gate_rejection_count,
            "duplicateRejectionCount": self.duplicate_rejection_count,
            "laneFailureCount": self.lane_failure_count,
            "cancellationReason": self.cancellation_reason,
            "errorCode": self.error_code,
            "failureClass": self.failure_class,
            "clientDisconnected": self.client_disconnected,
            "finishReason": self.finish_reason,
        }
        if include_lanes:
            payload["lanes"] = {
                name: lane.to_wire() for name, lane in sorted(self.lanes.items())
            }
        return payload


class RequestTelemetryStore:
    def __init__(
        self,
        *,
        service_id: str,
        max_entries: int = 256,
        ttl_seconds: float = 900.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.service_id = service_id
        self._store = BoundedStore(max_entries=max_entries, ttl_seconds=ttl_seconds, clock=clock)

    def create(self, record: RequestTelemetry) -> None:
        self._store.put(record.execution_id, record)

    def get(self, execution_id: str) -> RequestTelemetry | None:
        return self._store.get(execution_id)

    def delete(self, execution_id: str) -> None:
        self._store.delete(execution_id)

    def active(self) -> list[dict[str, Any]]:
        return [
            record.to_wire(include_lanes=True)
            for record in self._store.values()
            if record.state in {"queued", "accepted", "streaming", "cancelling"}
        ]

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        records = sorted(
            self._store.values(),
            key=lambda item: item.started_monotonic,
            reverse=True,
        )
        return [record.to_wire(include_lanes=True) for record in records[: max(0, int(limit))]]

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


_FORBIDDEN_LOG_KEYS = {
    "body",
    "candidateText",
    "content",
    "document",
    "documentText",
    "message",
    "prompt",
    "raw",
    "rawText",
    "raw_text",
    "responseBody",
    "text",
    "token",
    "authorization",
    "selectedText",
    "diagnostic",
}


def safe_log_fields(**fields: Any) -> dict[str, Any]:
    """Drop common raw-text fields even if a future caller passes one.

    The match is case-insensitive so ``DocumentText`` and ``documentText``
    cannot slip through.
    """
    forbidden = {key.casefold() for key in _FORBIDDEN_LOG_KEYS}
    return {
        key: value
        for key, value in fields.items()
        if key.casefold() not in forbidden
    }


def log_internal(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    logger.log(level, event, extra=safe_log_fields(**fields))


__all__ = [
    "BoundedStore",
    "LaneTelemetry",
    "RequestTelemetry",
    "RequestTelemetryStore",
    "log_internal",
    "request_tag",
    "safe_log_fields",
    "text_hash",
]
