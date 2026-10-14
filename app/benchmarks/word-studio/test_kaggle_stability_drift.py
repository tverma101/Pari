#!/usr/bin/env python3
"""CPU unit tests for finalist warm-stability telemetry parsing and drift math (Issue #31).

Tests all required fixtures from Issue #31:
• stable memory;
• monotonic leak-like growth;
• temporary spike that recovers;
• process disappears cleanly;
• owned process remains after shutdown;
• missing nvidia-smi field / partial sample without crashing the report;
• two GPUs with asymmetric usage.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from kaggle_stability_drift import (
    compute_drift_analysis,
    compute_latency_drift,
    parse_nvidia_smi_query,
    verify_process_cleanup,
)


class TestWarmStabilityTelemetry(unittest.TestCase):
    def test_fixture_stable_memory(self):
        """Stable memory: memory remains consistent with zero or negligible drift."""
        trace = [
            {0: 7850.0},
            {0: 7852.0},
            {0: 7850.5},
            {0: 7851.0},
            {0: 7850.2},
        ]
        res = compute_drift_analysis(trace, leak_threshold_mb=50.0)
        self.assertFalse(res["vramLeakDetected"])
        self.assertAlmostEqual(res["perGpu"][0]["vramDriftMB"], 0.2, places=1)
        self.assertEqual(res["perGpu"][0]["initialWarmVramMB"], 7850.0)
        self.assertEqual(res["perGpu"][0]["maxVramMB"], 7852.0)

    def test_fixture_monotonic_leak_like_growth(self):
        """Monotonic leak-like growth: strictly increasing memory above engineering threshold."""
        trace = [
            {0: 7850.0},
            {0: 7920.0},
            {0: 7990.0},
            {0: 8060.0},
            {0: 8130.0},
        ]
        res = compute_drift_analysis(trace, leak_threshold_mb=50.0)
        self.assertTrue(res["vramLeakDetected"])
        self.assertTrue(res["perGpu"][0]["vramLeakDetected"])
        self.assertTrue(res["perGpu"][0]["isMonotonicGrowth"])
        self.assertGreater(res["perGpu"][0]["vramDriftMB"], 200.0)

    def test_fixture_temporary_spike_that_recovers(self):
        """Temporary spike that recovers: peak VRAM is high during allocation, but settles back."""
        trace = [
            {0: 7850.0},
            {0: 9200.0},  # peak workspace / activation spike
            {0: 9500.0},
            {0: 7860.0},  # recovered post-generation
            {0: 7852.0},
        ]
        res = compute_drift_analysis(trace, leak_threshold_mb=50.0)
        self.assertFalse(res["vramLeakDetected"])
        self.assertFalse(res["perGpu"][0]["vramLeakDetected"])
        self.assertEqual(res["perGpu"][0]["maxVramMB"], 9500.0)
        self.assertAlmostEqual(res["perGpu"][0]["vramDriftMB"], 2.0, places=1)

    def test_fixture_process_disappears_cleanly(self):
        """Process disappears cleanly: all tracked owned pids are gone from live system."""
        live_pids = [100, 101, 105, 200]
        owned_pids = [501, 502, 503]
        res = verify_process_cleanup(live_pids, owned_pids)
        self.assertTrue(res["cleanupVerified"])
        self.assertEqual(res["lingeringPids"], [])

    def test_fixture_owned_process_remains_after_shutdown(self):
        """Owned process remains: an uncleaned child process is flagged."""
        live_pids = [100, 101, 502, 200]  # 502 is lingering!
        owned_pids = [501, 502, 503]
        res = verify_process_cleanup(live_pids, owned_pids)
        self.assertFalse(res["cleanupVerified"])
        self.assertEqual(res["lingeringPids"], [502])

    def test_fixture_missing_smi_field_or_partial_sample(self):
        """Missing nvidia-smi field / partial sample parsed safely without crashing."""
        raw_output = """
0, 7850, 15360, 45
1, [Not Supported], 15360, 0
malformed_row
0, 7860
"""
        parsed = parse_nvidia_smi_query(raw_output)
        self.assertGreaterEqual(len(parsed), 3)
        self.assertEqual(parsed[0]["index"], 0)
        self.assertEqual(parsed[0]["usedMB"], 7850.0)
        self.assertEqual(parsed[0]["totalMB"], 15360.0)
        self.assertEqual(parsed[0]["utilizationPercent"], 45.0)
        # Verify row with "[Not Supported]" parsed without crashing
        self.assertEqual(parsed[1]["index"], 1)
        self.assertIsNone(parsed[1]["usedMB"])
        self.assertEqual(parsed[1]["totalMB"], 15360.0)

    def test_fixture_two_gpus_with_asymmetric_usage(self):
        """Two GPUs with asymmetric usage: GPU0 carries model load, GPU1 remains idle/parallel lane."""
        trace = [
            {0: 7850.0, 1: 320.0},
            {0: 7855.0, 1: 320.0},
            {0: 7852.0, 1: 320.0},
        ]
        res = compute_drift_analysis(trace, leak_threshold_mb=50.0)
        self.assertTrue(res["asymmetricUsageDetected"])
        self.assertAlmostEqual(res["perGpu"][0]["endWarmVramMB"], 7852.0)
        self.assertAlmostEqual(res["perGpu"][1]["endWarmVramMB"], 320.0)
        self.assertAlmostEqual(res["perGpu"][0]["vramDriftMB"], 2.0)
        self.assertAlmostEqual(res["perGpu"][1]["vramDriftMB"], 0.0)

    def test_latency_drift_math(self):
        """Latency drift math correctly calculates early window vs late window averages and %."""
        latencies = [0.30, 0.31, 0.32, 0.30, 0.32, 0.33, 0.31, 0.33, 0.32]
        res = compute_latency_drift(latencies)
        self.assertAlmostEqual(res["earlyWindowAvgSec"], 0.31, places=2)
        self.assertAlmostEqual(res["lateWindowAvgSec"], 0.32, places=2)
        self.assertGreaterEqual(res["latencyDriftPercent"], 0.0)


if __name__ == "__main__":
    unittest.main()
