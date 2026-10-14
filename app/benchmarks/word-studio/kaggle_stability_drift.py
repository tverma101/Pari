#!/usr/bin/env python3
"""Finalist warm-stability telemetry, VRAM drift math, and cleanup verification (Issue #31).

Implements machine-readable parsing and analysis of GPU telemetry during repeated-request
loops, per-GPU memory drift math with conservative engineering leak thresholds,
cleanup verification, and robust tolerance of partial nvidia-smi samples.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence


class TelemetryParseError(Exception):
    pass


def parse_nvidia_smi_query(query_output: str) -> list[dict[str, Any]]:
    """Parse output from `nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits`.
    
    Robust against trailing whitespace, partial samples, and missing fields.
    """
    gpus: list[dict[str, Any]] = []
    lines = [line.strip() for line in query_output.strip().splitlines() if line.strip()]
    
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        if not parts:
            continue
            
        try:
            gpu_idx = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else len(gpus)
        except (ValueError, TypeError):
            gpu_idx = len(gpus)
            
        used_mb = None
        if len(parts) > 1:
            try:
                used_mb = float(parts[1])
            except ValueError:
                used_mb = None
                
        total_mb = None
        if len(parts) > 2:
            try:
                total_mb = float(parts[2])
            except ValueError:
                total_mb = None
                
        util_pct = None
        if len(parts) > 3:
            try:
                util_pct = float(parts[3])
            except ValueError:
                util_pct = None
                
        gpus.append({
            "index": gpu_idx,
            "usedMB": used_mb,
            "totalMB": total_mb,
            "utilizationPercent": util_pct,
        })
        
    return gpus


def compute_drift_analysis(
    gpu_trace: Sequence[Mapping[int, float]],
    *,
    leak_threshold_mb: float = 50.0,
) -> dict[str, Any]:
    """Compute per-GPU and overall VRAM drift across a repeated-request trajectory.
    
    Args:
        gpu_trace: Sequence of mappings from gpu_index -> memory_used_mb at each sample step.
        leak_threshold_mb: Engineering threshold above which growth is flagged as a leak.
        
    Returns:
        Structured drift report containing initial, max, end, drift_mb, and leak status.
    """
    if not gpu_trace:
        return {"error": "Empty telemetry trace", "vramLeakDetected": False}
        
    # Discover all GPU indices present across trace
    all_gpus = sorted({gpu for step in gpu_trace for gpu in step.keys()})
    
    per_gpu_reports: dict[int, dict[str, Any]] = {}
    leak_detected = False
    
    for gpu_idx in all_gpus:
        series = [step.get(gpu_idx) for step in gpu_trace if step.get(gpu_idx) is not None]
        if not series:
            continue
            
        initial_val = series[0]
        max_val = max(series)
        end_val = series[-1]
        drift_mb = round(end_val - initial_val, 2)
        pct_drift = round((drift_mb / max(0.1, initial_val)) * 100, 2) if initial_val > 0 else 0.0
        
        # Check monotonic growth pattern (each window strictly larger than previous)
        is_monotonic = True
        for i in range(1, len(series)):
            if series[i] < series[i - 1]:
                is_monotonic = False
                break
                
        gpu_leak = drift_mb > leak_threshold_mb and (is_monotonic or drift_mb > 100.0)
        if gpu_leak:
            leak_detected = True
            
        per_gpu_reports[gpu_idx] = {
            "initialWarmVramMB": round(initial_val, 2),
            "maxVramMB": round(max_val, 2),
            "endWarmVramMB": round(end_val, 2),
            "vramDriftMB": drift_mb,
            "percentDrift": pct_drift,
            "isMonotonicGrowth": is_monotonic,
            "vramLeakDetected": gpu_leak,
        }
        
    return {
        "perGpu": per_gpu_reports,
        "vramLeakDetected": leak_detected,
        "sampleCount": len(gpu_trace),
        "asymmetricUsageDetected": len(all_gpus) > 1 and (
            abs(per_gpu_reports.get(0, {}).get("endWarmVramMB", 0) - per_gpu_reports.get(1, {}).get("endWarmVramMB", 0)) > 500.0
        ),
    }


def compute_latency_drift(latencies: Sequence[float]) -> dict[str, Any]:
    """Compute early-window vs late-window latency distribution and drift percentage."""
    if not latencies:
        return {
            "earlyWindowAvgSec": 0.0,
            "lateWindowAvgSec": 0.0,
            "latencyDriftPercent": 0.0,
        }
        
    window_size = max(1, len(latencies) // 3)
    early = latencies[:window_size]
    late = latencies[-window_size:]
    
    early_avg = sum(early) / len(early)
    late_avg = sum(late) / len(late)
    
    drift_pct = round(((late_avg - early_avg) / max(0.0001, early_avg)) * 100, 2)
    
    return {
        "earlyWindowAvgSec": round(early_avg, 4),
        "lateWindowAvgSec": round(late_avg, 4),
        "latencyDriftPercent": drift_pct,
        "sampleCount": len(latencies),
    }


def verify_process_cleanup(
    live_system_pids: Sequence[int],
    owned_tracked_pids: Sequence[int],
) -> dict[str, Any]:
    """Verify that all owned child/model processes have terminated cleanly after shutdown."""
    live_set = set(live_system_pids)
    lingering = [pid for pid in owned_tracked_pids if pid in live_set]
    
    return {
        "cleanupVerified": len(lingering) == 0,
        "lingeringPids": lingering,
        "trackedPidsCount": len(owned_tracked_pids),
    }
