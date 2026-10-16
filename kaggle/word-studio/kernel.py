"""Kaggle 2xT4 kernel: run Word Studio v2 candidates and keep every raw output (#86).

``launch.py`` copies this file into a kernel folder and fills in CONFIG. On
Kaggle it clones the Pari repository at one exact commit, installs pinned
packages, and runs ``v2.run_candidate`` once per candidate in its own process,
so one crash or out-of-memory error cannot take down the others.

A candidate that crashes, times out or is killed is recorded as failed in its
own run.json. Nothing here computes or writes a score.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

CONFIG = {}  # filled in by launch.py

WORK = Path("/kaggle/working")
RUN_DIR = WORK / "runs" / CONFIG.get("run_id", "unset")
REPO = Path("/tmp/Pari")
HF_HOME = Path("/tmp/hf")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sh(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("$ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, text=True, **kwargs)


def capture(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return f"<{cmd[0]} failed: {exc}>"


def mark_failed(run_json: Path, reason: str) -> None:
    """Record a crash the runner itself could not record."""
    if not run_json.exists():
        run_json.parent.mkdir(parents=True, exist_ok=True)
        record = {"status": "failed", "stage": "process", "candidate": {"candidate_id": run_json.parent.name}}
    else:
        record = json.loads(run_json.read_text(encoding="utf-8"))
        if record.get("status") in {"completed", "failed"}:
            return
    record.update(status="failed", finished_at=now(),
                  error={"type": "ProcessExit", "message": reason, "recorded_by": "kaggle/word-studio/kernel.py"})
    run_json.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    if not CONFIG:
        raise SystemExit("CONFIG is empty: push this kernel with kaggle/word-studio/launch.py")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    (RUN_DIR / "nvidia-smi.txt").write_text(capture(["nvidia-smi"]), encoding="utf-8")
    (RUN_DIR / "pip-freeze-before.txt").write_text(capture([sys.executable, "-m", "pip", "freeze"]), encoding="utf-8")

    sh(["git", "clone", "--quiet", CONFIG["repo_url"], str(REPO)])
    sh(["git", "-C", str(REPO), "checkout", "--quiet", CONFIG["git_sha"]])
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    if head != CONFIG["git_sha"]:
        raise SystemExit(f"checked out {head}, expected {CONFIG['git_sha']}")
    sh([sys.executable, "-m", "pip", "install", "--quiet", *CONFIG["pip"]])
    (RUN_DIR / "pip-freeze.txt").write_text(capture([sys.executable, "-m", "pip", "freeze"]), encoding="utf-8")

    env = dict(os.environ, HF_HOME=str(HF_HOME), PYTHONDONTWRITEBYTECODE="1", TOKENIZERS_PARALLELISM="false")
    summary = {"config": CONFIG, "git_head": head, "started_at": now(), "candidates": {}}
    for candidate in CONFIG["candidates"]:
        out = RUN_DIR / candidate
        cmd = [sys.executable, "-m", "v2.run_candidate", "--candidate", candidate, "--set", CONFIG["task_set"],
               "--out", str(out)]
        if CONFIG.get("limit"):
            cmd += ["--limit", str(CONFIG["limit"])]
        started = time.time()
        log_path = RUN_DIR / f"{candidate}.log"
        print(f"=== {candidate} ===", flush=True)
        timed_out = threading.Event()
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(cmd, cwd=REPO / "bench" / "word-studio", env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True)
            watchdog = threading.Timer(CONFIG["per_candidate_timeout_s"], lambda: (timed_out.set(), proc.kill()))
            watchdog.start()
            for line in proc.stdout:
                sys.stdout.write(line)
                log.write(line)
            code = proc.wait()
            watchdog.cancel()
        if timed_out.is_set():
            reason = f"timed out after {CONFIG['per_candidate_timeout_s']} s"
        elif code not in (0, 2):
            reason = f"run_candidate exited with code {code}"
        else:
            reason = None
        if reason:
            mark_failed(out / "run.json", reason)
        run = json.loads((out / "run.json").read_text(encoding="utf-8")) if (out / "run.json").exists() else {}
        summary["candidates"][candidate] = {
            "exit_code": code,
            "status": run.get("status"),
            "tasks": run.get("tasks"),
            "error": (run.get("error") or {}).get("message"),
            "wall_seconds": round(time.time() - started, 1),
        }
        shutil.rmtree(HF_HOME / "hub", ignore_errors=True)
        (RUN_DIR / "kernel-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    summary["finished_at"] = now()
    (RUN_DIR / "kernel-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary["candidates"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
