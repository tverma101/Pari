#!/usr/bin/env python3
"""End-to-end smoke of the outer Pari Studio SSE service."""
from __future__ import annotations

import argparse
import json
import os
import time
import uuid
from pathlib import Path

import requests


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default="http://127.0.0.1:9000")
    ap.add_argument("--output", type=Path, default=Path("/kaggle/working/pari-studio/smoke-result.json"))
    ap.add_argument("--timeout", type=float, default=120.0)
    args = ap.parse_args()

    text = "The examples clarified the rule for me."
    selected = "clarified"
    start = text.index(selected)
    request_id = f"studio-smoke-{uuid.uuid4().hex[:10]}"
    body = {
        "requestId": request_id,
        "documentText": text,
        "selection": {"start": start, "end": start + len(selected)},
        "operation": "replace",
        "strength": 60,
        "requestedCandidates": 10,
    }
    headers = {"Accept": "text/event-stream"}
    token = os.environ.get("PARI_STUDIO_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    started = time.monotonic()
    response = requests.post(
        args.endpoint.rstrip("/") + "/v1/studio/transform",
        json=body,
        headers=headers,
        stream=True,
        timeout=(15, args.timeout),
    )
    response.raise_for_status()

    events = []
    event_name = None
    final = None
    first_three_seconds = None
    for raw in response.iter_lines(decode_unicode=True):
        if raw is None:
            continue
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip()
            continue
        if not line.startswith("data:"):
            continue
        payload = json.loads(line.split(":", 1)[1].strip())
        events.append({"event": event_name, "data": payload})
        if event_name == "error":
            raise SystemExit(f"Studio smoke received backend error: {payload}")
        if event_name != "candidates":
            continue
        if payload.get("requestId") != request_id:
            raise SystemExit("Studio smoke received wrong requestId")
        candidates = payload.get("candidates") or []
        if len(candidates) >= 3 and first_three_seconds is None:
            first_three_seconds = time.monotonic() - started
        if payload.get("final"):
            final = payload
            break
    response.close()

    result = {
        "version": 1,
        "requestId": request_id,
        "elapsedSeconds": round(time.monotonic() - started, 6),
        "firstThreeCandidatesSeconds": round(first_three_seconds, 6) if first_three_seconds is not None else None,
        "events": events,
        "final": final,
        "passed": bool(final and len(final.get("candidates") or []) >= 3 and not final.get("cancelled")),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "passed": result["passed"],
        "firstThreeCandidatesSeconds": result["firstThreeCandidatesSeconds"],
        "finalCandidateCount": len((final or {}).get("candidates") or []),
        "artifact": str(args.output),
    }, indent=2))
    if not result["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
