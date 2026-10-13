#!/usr/bin/env python3
"""Focused CPU tests for the bounded Studio telemetry store."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from studio_backend.telemetry import (  # noqa: E402
    BoundedStore,
    RequestTelemetry,
    RequestTelemetryStore,
    safe_log_fields,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_record(execution_id: str, clock) -> RequestTelemetry:
    return RequestTelemetry(
        service_id="telemetry-unit",
        execution_id=execution_id,
        request_tag=execution_id,
        operation="replace",
        source_sha256="0" * 64,
        selection_sha256="1" * 64,
        selection_start=0,
        selection_end=1,
        requested_candidates=10,
        clock=clock,
    )


class TestBoundedStoreExpiry(unittest.TestCase):
    def test_get_does_not_shield_older_expired_entries(self) -> None:
        clock = FakeClock()
        store = BoundedStore(max_entries=8, ttl_seconds=60.0, clock=clock)
        store.put("a", "A")
        store.put("b", "B")
        clock.advance(50)
        store.put("c", "C")
        # Reading "a" reorders it behind the still-live "c" without refreshing
        # its creation time.
        self.assertEqual(store.get("a"), "A")
        clock.advance(20)

        self.assertIsNone(store.get("a"))
        self.assertEqual([value for _key, value in _items(store)], ["C"])
        self.assertEqual(len(store), 1)

    def test_values_and_items_expire_every_record(self) -> None:
        clock = FakeClock()
        store = BoundedStore(max_entries=8, ttl_seconds=10.0, clock=clock)
        store.put("old", 1)
        clock.advance(5)
        store.put("new", 2)
        clock.advance(6)
        self.assertEqual(store.values(), [2])
        self.assertEqual(list(store.items()), [("new", 2)])

    def test_max_entries_still_bounds_the_store(self) -> None:
        clock = FakeClock()
        store = BoundedStore(max_entries=2, ttl_seconds=0.0, clock=clock)
        for index in range(5):
            store.put(str(index), index)
        self.assertEqual(len(store), 2)
        self.assertEqual(sorted(value for _key, value in store.items()), [3, 4])


def _items(store: BoundedStore):
    return store.items()


class TestRequestTelemetryTiming(unittest.TestCase):
    def test_first_one_is_observed_before_first_three(self) -> None:
        clock = FakeClock()
        record = make_record("exec-1", clock)
        record.admit()

        clock.advance(0.010)
        record.observe_candidates(1, 1)
        clock.advance(0.020)
        record.observe_candidates(3, 3)
        clock.advance(0.030)
        record.observe_candidates(10, 10)

        self.assertEqual(record.first_candidate_ms, 10.0)
        self.assertEqual(record.first_three_ms, 30.0)
        self.assertEqual(record.first_ten_ms, 60.0)

    def test_thresholds_are_recorded_once(self) -> None:
        clock = FakeClock()
        record = make_record("exec-2", clock)
        clock.advance(0.005)
        record.observe_candidates(3, 3)
        clock.advance(0.005)
        record.observe_candidates(3, 3)

        self.assertEqual(record.first_candidate_ms, 5.0)
        self.assertEqual(record.first_three_ms, 5.0)
        self.assertEqual(record.streamed_candidate_count, 3)
        self.assertEqual(record.unique_candidate_count, 3)

    def test_duplicate_rejection_count_is_exported(self) -> None:
        record = make_record("exec-dupes", FakeClock())
        self.assertEqual(record.to_wire()["duplicateRejectionCount"], 0)
        record.duplicate_rejection_count = 3
        self.assertEqual(record.to_wire()["duplicateRejectionCount"], 3)


class TestRequestTelemetryStore(unittest.TestCase):
    def test_recent_and_len_agree_with_get_after_reordering(self) -> None:
        clock = FakeClock()
        store = RequestTelemetryStore(
            service_id="telemetry-unit", max_entries=8, ttl_seconds=60.0, clock=clock
        )
        first = make_record("exec-a", clock)
        second = make_record("exec-b", clock)
        store.create(first)
        store.create(second)
        clock.advance(50)
        store.create(make_record("exec-c", clock))
        self.assertIsNotNone(store.get("exec-a"))
        clock.advance(20)

        self.assertIsNone(store.get("exec-a"))
        self.assertIsNone(store.get("exec-b"))
        self.assertIsNotNone(store.get("exec-c"))
        self.assertEqual([row["executionId"] for row in store.recent()], ["exec-c"])
        self.assertEqual(len(store), 1)

    def test_active_excludes_terminal_records(self) -> None:
        clock = FakeClock()
        store = RequestTelemetryStore(service_id="telemetry-unit", clock=clock)
        queued = make_record("exec-queued", clock)
        done = make_record("exec-done", clock)
        done.finish("completed")
        store.create(queued)
        store.create(done)
        self.assertEqual([row["executionId"] for row in store.active()], ["exec-queued"])

    def test_delete_removes_record(self) -> None:
        clock = FakeClock()
        store = RequestTelemetryStore(service_id="telemetry-unit", clock=clock)
        store.create(make_record("exec-x", clock))
        store.delete("exec-x")
        self.assertEqual(len(store), 0)


class TestSafeLogFields(unittest.TestCase):
    def test_case_insensitive_text_fields_are_dropped(self) -> None:
        fields = safe_log_fields(
            DocumentText="SECRET",
            prompt="SECRET",
            RAW_TEXT="SECRET",
            message="SECRET",
            diagnostic="SECRET",
            body="SECRET",
            text="SECRET",
            content="SECRET",
            requestTag="abc123",
            errorCode="model_timeout",
        )
        self.assertEqual(fields, {"requestTag": "abc123", "errorCode": "model_timeout"})

    def test_unknown_structured_fields_are_preserved(self) -> None:
        fields = safe_log_fields(
            executionId="exec-1",
            queueWaitMs=12.5,
            laneFailureCount=1,
            field="requestId",
            limit=128,
        )
        self.assertEqual(
            fields,
            {
                "executionId": "exec-1",
                "queueWaitMs": 12.5,
                "laneFailureCount": 1,
                "field": "requestId",
                "limit": 128,
            },
        )


def main() -> None:
    unittest.main(verbosity=2)


if __name__ == "__main__":
    main()
