#!/usr/bin/env python3
"""Run a pinned vLLM candidate as a local streaming server on Kaggle T4.

This is a finalist/product-latency probe, not the common English-quality runner.
It uses the verified prebuilt vLLM wheel, refuses source-build workarounds, proves
GPU memory use, streams Word Studio tasks, and shuts the server down.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests

from kaggle_context_budget import (
    ContextBudgetReceipt,
    ContextUnqualified,
    LimitCandidate,
    PromptIdentity,
    ThinkingCapability,
    build_task_budget_row,
    classify_output_cap_exhaustion,
    enforce_budget,
    resolve_effective_context_limit,
    resolve_task_max_new_tokens,
)
from kaggle_failure_taxonomy import classify
from kaggle_server_identity import (
    OwnedServer,
    PortCollision,
    allocate_loopback_port,
    release_port_reservation,
    served_model_identity,
)

HERE = Path(__file__).resolve().parent
ROSTER = HERE / "kaggle-candidate-roster.json"
CLIENT = HERE / "run-word-studio-openai-stream.py"
DEFAULT_RUNTIME_ID = "vllm-0.30.0-cu129-linux-x86_64"
DEFAULT_TRANSFORM_TASKS = HERE / "word-studio-transform.jsonl"
DEFAULT_WORD_STUDIO_TASKS = HERE / "word-studio-strength.jsonl"


class _ServerTokenizerCounter:
    """Exact prompt length from the live vLLM server's own `/tokenize`.

    The server renders the chat template with the same
    ``--default-chat-template-kwargs`` and request-level template kwargs the
    benchmark sends, so its count already includes every template/system/user
    wrapper. If the server cannot answer, this raises rather than falling back
    to a local estimate, because a derived count is not the count the runtime
    will use.
    """

    mode = "chat"
    identity = {
        "promptMode": "chat",
        "template": "vllm-server /tokenize (server-rendered chat template)",
        "templateSha256": None,
        "detail": "server /tokenize with chat_template_kwargs and add_generation_prompt",
    }

    def __init__(self, endpoint: str, model: str, timeout: float) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout = timeout

    def id(self) -> PromptIdentity:
        return PromptIdentity(
            mode=self.identity["promptMode"],
            template=self.identity["template"],
            template_sha256=self.identity["templateSha256"],
            detail=self.identity["detail"],
        )

    def count(self, text: str) -> int:
        response = requests.post(
            self.endpoint + "/tokenize",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": text}],
                "add_generation_prompt": True,
                "add_special_tokens": True,
                "continue_final_message": False,
                "chat_template_kwargs": {"enable_thinking": False},
                "return_token_strs": False,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        body = response.json()
        tokens = body.get("tokens") if isinstance(body, dict) else None
        count = body.get("count") if isinstance(body, dict) else None
        if isinstance(tokens, list):
            return len(tokens)
        if isinstance(count, int) and not isinstance(count, bool):
            return count
        raise ContextUnqualified(
            "server_tokenize_unusable",
            detail={
                "route": "/tokenize",
                "response_keys": sorted(body.keys()) if isinstance(body, dict) else type(body).__name__,
            },
        )


def server_effective_limit(endpoint: str, args_max_model_len: int, timeout: float = 30.0) -> dict[str, Any]:
    """Minimum applicable context limit for the live server we are about to drive.

    The server is launched by this script with an explicit ``--max-model-len``,
    so that value is provable. Anything the server would clamp internally is not
    advertised over the API we depend on, so nothing optimistic is invented
    here; if a future server exposes a smaller effective limit, the minimum
    resolution below will pick it up automatically once a source is added.
    """
    candidates = [
        LimitCandidate(
            tokens=int(args_max_model_len),
            source="runtime_override",
            provenance=f"vllm serve --max-model-len {args_max_model_len}",
        )
    ]
    return resolve_effective_context_limit(candidates)


def probe_context_budget(
    endpoint: str,
    model: str,
    task_rows: list[dict[str, Any]],
    *,
    effective_limit: dict[str, Any],
    default_max_new_tokens: int,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Preflight every probe task against the live server before streaming."""
    counter = _ServerTokenizerCounter(endpoint, model, timeout)
    thinking = ThinkingCapability.applied(
        "reasoning_effort=none;chat_template_kwargs.enable_thinking=false;"
        "--default-chat-template-kwargs enable_thinking=false",
        "prompt tokens are counted by the same server that will stream the answer, "
        "so template overhead and any thinking block are already inside the count",
    )
    receipt = ContextBudgetReceipt(
        tokenizer_identity={
            "nameOrPath": model,
            "kind": "vllm-server /tokenize",
            "repoOrName": model,
            "revision": "server-loaded pinned revision (see summary.candidate.revision)",
            "specialTokenHandling": "server-rendered; add_generation_prompt=True",
        },
        prompt_identity=counter.id().as_dict(),
        effective_limit=effective_limit,
        thinking=thinking.as_dict(),
    )
    for task in task_rows:
        requested = resolve_task_max_new_tokens(
            task,
            default_max_new_tokens=default_max_new_tokens,
            default_forced_choice_max_new_tokens=default_max_new_tokens,
        )
        row = build_task_budget_row(
            task_id=str(task["id"]),
            prompt_text=task["prompt"],
            counter=counter,
            max_new_tokens=requested,
            effective_limit=effective_limit,
            thinking=thinking,
            reasoning_budget_required=True,
        )
        receipt.tasks.append(row)
        if not row["fits"]:
            receipt.violations.append(str(task["id"]))
    return enforce_budget(receipt)


class StageRecorder:
    """Record each execution stage and its failure classification on the summary.

    Issue #53: the candidate wrappers pass an explicit ``stage`` into the
    taxonomy so load-time and generation-time CUDA OOM stay distinguishable.
    This probe drives the same runtime by hand, so it declares the same stages
    and keeps them in the summary instead of relying on log wording alone.
    """

    def __init__(self, summary: dict[str, Any], summary_path: Path) -> None:
        self.summary = summary
        self.summary_path = summary_path
        self.stages: list[dict[str, Any]] = self.summary.setdefault("stages", [])

    def enter(self, stage: str) -> None:
        self.stages.append({"stage": stage, "status": "running"})
        write(self.summary_path, self.summary)

    def finish(self, stage: str, **fields: Any) -> None:
        for row in reversed(self.stages):
            if row.get("stage") == stage:
                row.update(fields)
                break
        write(self.summary_path, self.summary)

    def fail(self, stage: str, text: str, **fields: Any) -> list[str]:
        """Classify with the explicit stage and record the attribution."""
        categories = classify(text, stage=stage)
        self.finish(stage, status="failed", failureCategories=categories, **fields)
        return categories


def load_progressive_contract() -> Any:
    """Load the canonical progressive timing contract from the core vLLM runner.

    Runner filenames are hyphenated CLI scripts and cannot be imported by name, so
    the core runner is loaded by path. The latency probe, the vLLM runner and the
    llama.cpp runner therefore all read one definition of the first-1/3/10
    usable-option schema.
    """
    path = Path(__file__).resolve().parent / "run-english-core-vllm.py"
    spec = importlib.util.spec_from_file_location("pari_english_core_vllm_runner", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load the shared progressive timing contract from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROGRESSIVE = load_progressive_contract()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Issue #60: allow_nan=False so a NaN latency surfaces as a loud write
    # failure instead of an unparseable `NaN` token in the evidence file.
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )


def gpu_used_mib() -> dict[int, int]:
    proc = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,memory.used", "--format=csv,noheader,nounits"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )
    out: dict[int, int] = {}
    for line in proc.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 2:
            continue
        try:
            out[int(parts[0])] = int(parts[1])
        except ValueError:
            pass
    return out


def wait_health(proc: subprocess.Popen, endpoint: str, timeout: float) -> tuple[bool, str]:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        if proc.poll() is not None:
            return False, f"server exited early rc={proc.returncode}"
        try:
            response = requests.get(endpoint + "/health", timeout=3)
            if response.ok:
                return True, "healthy"
            last = f"HTTP {response.status_code}"
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(2)
    return False, f"health timeout: {last}"


def stream_sse_progressive(
    endpoint: str,
    model: str,
    task: dict,
    *,
    max_tokens: int,
    temperature: float,
    top_p: float,
    seed: int,
    request_timeout: float,
) -> dict[str, Any]:
    """Stream one task from the live vLLM server and time usable candidates.

    This is the in-process complement to the delegated client run: it exists so the
    latency probe can emit the same first-1/3/10 usable-candidate schema as the
    canonical runners, computed from real incremental SSE text with the shared
    contract. It never regenerates or retries to obtain a timing value.
    """
    tracker = PROGRESSIVE.ProgressiveOptionTracker(
        source=task.get("selectedText") or task.get("sourceText") or None,
        requested=int(task.get("requestedCount") or 10),
        applicable=True,
    )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": task["prompt"]}],
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "seed": seed,
        "stream": True,
        "stream_options": {"include_usage": True},
        "reasoning_effort": "none",
        "chat_template_kwargs": {"enable_thinking": False},
    }
    started = time.monotonic()
    response = requests.post(
        endpoint.rstrip("/") + "/v1/chat/completions",
        json=payload,
        stream=True,
        timeout=(30, request_timeout),
    )
    response.raise_for_status()
    first_token: float | None = None
    chunks: list[str] = []
    finish_reason = None
    for raw in response.iter_lines(decode_unicode=True):
        if not raw:
            continue
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        if not line.startswith("data:"):
            continue
        body = line[len("data:"):].strip()
        if body == "[DONE]":
            break
        try:
            event = json.loads(body)
        except json.JSONDecodeError:
            continue
        choices = event.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        delta = choice.get("delta") or {}
        text = delta.get("content") or ""
        if choice.get("finish_reason"):
            finish_reason = choice["finish_reason"]
        if not text:
            continue
        if first_token is None:
            first_token = time.monotonic() - started
        chunks.append(text)
        tracker.observe(text, "".join(chunks))
    response.close()
    finished = time.monotonic()
    raw_text = "".join(chunks)
    tracker.finish(raw_text)
    cap = classify_output_cap_exhaustion(
        finish_reason=finish_reason,
        completion_tokens=None,
        expected_limit=max_tokens,
    )
    row = {
        "id": task["id"],
        "output": raw_text,
        "latencySeconds": round(finished - started, 6),
        "firstTokenLatencySeconds": round(first_token, 6) if first_token is not None else None,
        "completionLatencySource": "client_monotonic_stream",
        "finishReason": finish_reason,
        "requestedMaxNewTokens": max_tokens,
        "outputBudget": cap,
        "streamChunkCount": len(chunks),
        "streamDeltaSha256": PROGRESSIVE.sha256_text(raw_text),
    }
    row.update(tracker.result(raw_text))
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate_id")
    ap.add_argument("--stage", choices=["word-studio", "transform"], required=True)
    ap.add_argument("--benchmark-revision", required=True)
    ap.add_argument("--decode", choices=["normal", "mtp", "qwen3_next_mtp"], default="normal")
    ap.add_argument("--speculative-tokens", type=int, default=1)
    ap.add_argument("--tasks", type=Path, default=None)
    ap.add_argument("--runtime-artifact-id", default=DEFAULT_RUNTIME_ID)
    ap.add_argument("--runtime-dir", type=Path, default=Path("/kaggle/working/pari-runtimes"))
    ap.add_argument("--preflight", type=Path, default=Path("/kaggle/working/results/preflight.json"))
    ap.add_argument("--results-dir", type=Path, default=Path("/kaggle/working/results"))
    ap.add_argument("--startup-timeout", type=float, default=300.0)
    ap.add_argument("--max-model-len", type=int, default=8192)
    ap.add_argument("--gpu-memory-utilization", type=float, default=0.88)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument(
        "--port",
        type=int,
        default=0,
        help=(
            "loopback port for the owned server; 0 allocates a verified-free port. "
            "A requested port already in use fails as port_collision."
        ),
    )
    ap.add_argument(
        "--require-listener-ownership",
        action="store_true",
        help=(
            "additionally require the listening PID to be inside the owned process tree; "
            "off by default because macOS/local runs cannot attribute sockets via /proc"
        ),
    )
    ap.add_argument(
        "--allow-unproven-served-model",
        action="store_true",
        help=(
            "record the served-model probe as unproven and continue; the run is marked "
            "identity-unproven rather than silently treated as qualified"
        ),
    )
    ap.add_argument(
        "--progressive-probe",
        choices=["auto", "off", "required"],
        default="auto",
        help=(
            "run the in-process first-1/3/10 usable-candidate probe against the live server; "
            "'auto' records an explicit limitation instead of failing, 'required' fails loudly"
        ),
    )
    ap.add_argument(
        "--progressive-probe-limit",
        type=int,
        default=4,
        help="max tasks to stream for progressive timing (bounded so the probe stays cheap)",
    )
    args = ap.parse_args()

    if not args.preflight.is_file() or not load(args.preflight).get("promotionEligibleEnvironment"):
        raise SystemExit("qualified real-Kaggle T4x2 preflight is required")

    roster = load(ROSTER)
    candidates = {row["id"]: row for row in roster["candidates"]}
    c = candidates.get(args.candidate_id)
    if c is None:
        raise SystemExit(f"unknown candidate {args.candidate_id}")
    if c.get("runtime") != "vllm":
        raise SystemExit(f"{args.candidate_id} is not a vLLM candidate")
    if args.decode != "normal" and args.decode not in set(c.get("mtpMethodsToProbe") or []):
        raise SystemExit(f"{args.decode} is not a predeclared speculative method for {args.candidate_id}")

    receipt_path = args.runtime_dir / f"{args.runtime_artifact_id}.receipt.json"
    if not receipt_path.is_file():
        raise SystemExit(f"missing verified vLLM receipt {receipt_path}; install pinned prebuilt, never compile")
    receipt = load(receipt_path)
    artifact = receipt.get("artifact") or {}
    if receipt.get("sourceCompilationAllowed") is not False or artifact.get("runtime") != "vllm":
        raise SystemExit("runtime receipt is not the approved binary-only vLLM artifact")
    if artifact.get("version") != "0.30.0":
        raise SystemExit(f"unexpected vLLM build {artifact.get('version')}; benchmark pins 0.30.0")

    vllm_exe = shutil.which("vllm")
    if not vllm_exe:
        raise SystemExit("vllm console script missing after pinned wheel installation; do not compile fallback")

    help_proc = subprocess.run(
        [vllm_exe, "serve", "--help=all"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False
    )
    required_flags = {
        "--revision", "--tokenizer-revision", "--dtype", "--tensor-parallel-size",
        "--max-model-len", "--gpu-memory-utilization", "--served-model-name",
        "--default-chat-template-kwargs",
    }
    if c.get("languageModelOnly"):
        required_flags.add("--language-model-only")
    if args.decode != "normal":
        required_flags.add("--speculative-config")
    missing = sorted(flag for flag in required_flags if flag not in help_proc.stdout)
    if help_proc.returncode != 0 or missing:
        # Issue #53: an unusable pinned CLI is an install-stage failure, not an
        # unclassified one, and it is recorded with its stage.
        install_categories = classify(
            help_proc.stdout
            + f"\npinned vLLM CLI contract mismatch; missing flags={missing}",
            stage="install",
        )
        print(
            "stage=install status=failed " + json.dumps({"failureCategories": install_categories}),
            flush=True,
        )
        raise SystemExit(f"pinned vLLM CLI contract mismatch; missing flags={missing}; do not improvise or rebuild")

    tasks = args.tasks.resolve() if args.tasks else (
        DEFAULT_TRANSFORM_TASKS if args.stage == "transform" else DEFAULT_WORD_STUDIO_TASKS
    )
    if not tasks.is_file():
        raise SystemExit(f"missing frozen product tasks {tasks}; build the declared suite first")
    task_rows = [json.loads(line) for line in tasks.read_text(encoding="utf-8").splitlines() if line.strip()]

    out_dir = args.results_dir / args.candidate_id / f"latency-{args.stage}" / args.decode
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "summary.json"
    server_log = out_dir / "vllm-server.log.txt"
    stream_result = out_dir / "streaming-result.json"
    summary = {
        "version": 1,
        # Issue #60: explicit schema identity on the summary this runner writes,
        # so a consumer does not have to infer the shape from the legacy
        # "version" field alone.
        "schemaVersion": 1,
        "candidate": c,
        "stage": f"latency-{args.stage}",
        "decode": args.decode,
        "benchmarkRevision": args.benchmark_revision,
        "runtimeReceipt": str(receipt_path),
        "tasks": str(tasks),
        "status": "starting",
        # Issue #53: the declared execution stages this probe runs, so a reader
        # can tell which phase a terminal failure came from without re-reading
        # the log. Populated as each stage starts.
        "declaredStages": ["server_start", "generate", "cleanup"],
        "progressiveOptionTiming": {
            "schemaVersion": PROGRESSIVE.PROGRESSIVE_SCHEMA_VERSION,
            "thresholds": list(PROGRESSIVE.USABLE_OPTION_THRESHOLDS),
            "fields": list(PROGRESSIVE.PROGRESSIVE_FIELD_BY_THRESHOLD.values()),
            "probeMode": args.progressive_probe,
            "clock": "time.monotonic",
        },
    }
    write(summary_path, summary)
    stages = StageRecorder(summary, summary_path)
    stages.enter("server_start")

    tp = int(c.get("tensorParallelSize") or 1)
    visible = "0" if tp == 1 else "0,1"
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = visible

    # Issue #42: prove the port before spawning. An occupied port is a hard
    # collision; we never adopt whatever is already listening there.
    requested_port = args.port if args.port and args.port > 0 else None
    try:
        port, port_evidence = allocate_loopback_port(requested_port)
    except PortCollision as collision:
        summary["status"] = "runtime_unqualified"
        summary["terminalFailureCategories"] = ["port_collision"]
        summary["reason"] = str(collision)
        summary["portOwnership"] = collision.evidence
        stages.finish("server_start", status="failed", failureCategories=["port_collision"])
        write(summary_path, summary)
        raise SystemExit(2)
    summary["portOwnership"] = port_evidence

    endpoint = f"http://127.0.0.1:{port}"
    server_cmd = [
        vllm_exe, "serve", c["repo"],
        "--host", "127.0.0.1", "--port", str(port),
        "--served-model-name", c["id"],
        "--revision", c["revision"], "--tokenizer-revision", c["revision"],
        "--dtype", "half", "--tensor-parallel-size", str(tp),
        "--max-model-len", str(args.max_model_len),
        "--gpu-memory-utilization", str(args.gpu_memory_utilization),
        "--seed", "0",
        "--default-chat-template-kwargs", '{"enable_thinking":false}',
        "--enable-per-request-metrics",
    ]
    if c.get("trustRemoteCode"):
        server_cmd.append("--trust-remote-code")
    if c.get("languageModelOnly"):
        server_cmd.append("--language-model-only")
    if args.decode != "normal":
        server_cmd += [
            "--speculative-config",
            json.dumps({"method": args.decode, "num_speculative_tokens": args.speculative_tokens}, separators=(",", ":")),
        ]

    baseline_gpu = gpu_used_mib()
    summary["serverCommand"] = server_cmd
    summary["cudaVisibleDevices"] = visible
    summary["gpuMemoryBeforeMiB"] = baseline_gpu
    summary["selectedPort"] = port
    write(summary_path, summary)

    # The reservation is released only once the real child is about to bind, so a
    # concurrent run cannot be handed the same port in between.
    release_port_reservation(port_evidence)
    server = OwnedServer(
        server_cmd,
        host="127.0.0.1",
        port=port,
        expected_model=c["id"],
        log_path=server_log,
        env=env,
    )
    proc = server.spawn(port_evidence)
    summary["ownedServer"] = server.ownership_receipt()
    write(summary_path, summary)
    try:
        # Issue #42: readiness is health AND served-model identity (and listener
        # ownership when the OS can prove it). Health alone cannot qualify.
        healthy, readiness = server.wait_ready(
            args.startup_timeout,
            require_identity=not args.allow_unproven_served_model,
            require_ownership=args.require_listener_ownership,
        )
        summary["serverReadiness"] = readiness
        if healthy:
            # Re-verify identity immediately before benchmark traffic so a server
            # swapped in after readiness cannot answer the client.
            identity = served_model_identity(endpoint, c["id"])
            summary["preRequestServedModelIdentity"] = identity
            if identity.get("identityMatched") is not True:
                healthy = False
                readiness["status"] = identity.get("identityStatus") or "identity_unavailable"
                readiness["error"] = "served-model identity changed between readiness and first request"
        detail = readiness.get("error") or readiness.get("status") or ""
        write(summary_path, summary)
        if not healthy:
            log_text = server_log.read_text(encoding="utf-8", errors="replace") if server_log.exists() else detail
            summary["status"] = "runtime_unqualified"
            category = readiness.get("status") or ""
            summary["terminalFailureCategories"] = (
                [category]
                if category in {"unowned_listener", "wrong_served_model", "identity_unavailable", "server_exited", "port_collision"}
                # Issue #53: an unhealthy server is a server_start failure, so
                # a load-time OOM here is not confused with a generate-time one.
                else stages.fail("server_start", log_text + "\n" + detail)
            )
            summary["reason"] = detail
            write(summary_path, summary)
            raise SystemExit(2)
        stages.finish("server_start", status="completed")

        after_gpu = gpu_used_mib()
        delta = {index: after_gpu.get(index, 0) - baseline_gpu.get(index, 0) for index in set(after_gpu) | set(baseline_gpu)}
        expected_devices = list(range(tp))
        placement_ok = all(delta.get(index, 0) >= 64 for index in expected_devices) and sum(max(0, delta.get(i, 0)) for i in expected_devices) >= 128
        summary["gpuPlacementEvidence"] = {
            "beforeMiB": baseline_gpu,
            "afterMiB": after_gpu,
            "deltaMiB": delta,
            "expectedVisibleDeviceCount": tp,
            "passed": placement_ok,
        }
        if not placement_ok:
            summary["status"] = "runtime_unqualified"
            summary["terminalFailureCategories"] = ["gpu_offload_unverified"]
            summary["reason"] = "healthy vLLM server did not produce expected T4 VRAM delta"
            stages.finish(
                "server_start",
                status="failed",
                failureCategories=["gpu_offload_unverified"],
                reason=summary["reason"],
            )
            write(summary_path, summary)
            raise SystemExit(2)

        # Issue #45: exact context-budget preflight against the live server,
        # before the delegated streaming client or the in-process probe sends a
        # single benchmark request. Counts come from the server's own /tokenize
        # (which renders the chat template), so the recorded prompt length is the
        # one the runtime will actually consume, not a local estimate.
        try:
            effective_limit = server_effective_limit(endpoint, args.max_model_len)
            client_default_max_tokens = 900
            context_budget = probe_context_budget(
                endpoint,
                c["id"],
                task_rows,
                effective_limit=effective_limit,
                default_max_new_tokens=client_default_max_tokens,
            )
        except ContextUnqualified as exc:
            summary["status"] = "runtime_unqualified"
            summary["terminalFailureCategories"] = ["context_length_config_failure", "context_unqualified"]
            summary["reason"] = f"context_unqualified: {exc.reason}: {exc.detail}"
            summary["contextBudget"] = exc.as_receipt()
            stages.finish(
                "server_start",
                status="failed",
                failureCategories=summary["terminalFailureCategories"],
                reason=summary["reason"],
            )
            write(summary_path, summary)
            raise SystemExit(2)
        except requests.RequestException as exc:
            summary["status"] = "runtime_unqualified"
            summary["terminalFailureCategories"] = ["context_length_config_failure", "context_budget_probe_failed"]
            summary["reason"] = f"context_budget_probe_failed: {type(exc).__name__}: {exc}"
            stages.finish(
                "server_start",
                status="failed",
                failureCategories=summary["terminalFailureCategories"],
                reason=summary["reason"],
            )
            write(summary_path, summary)
            raise SystemExit(2)
        context_budget_path = out_dir / "context-budget.json"
        write(context_budget_path, context_budget)
        summary["contextBudget"] = {
            "receiptPath": str(context_budget_path),
            "receiptSha256": context_budget["receiptSha256"],
            "effectiveContextLimit": effective_limit["effectiveContextLimit"],
            "effectiveContextLimitSource": effective_limit["selectedFrom"],
            "thinkingCapability": context_budget["thinkingCapability"],
            "summary": context_budget["summary"],
        }
        write(summary_path, summary)

        stages.enter("generate")
        client_cmd = [
            sys.executable, str(CLIENT),
            "--endpoint", endpoint, "--model", c["id"],
            "--tasks", str(tasks), "--output", str(stream_result),
        ]
        if args.limit is not None:
            client_cmd += ["--limit", str(args.limit)]
        client = subprocess.run(client_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out_dir / "streaming-client.log.txt").write_text(client.stdout, encoding="utf-8", errors="replace")
        if client.returncode != 0:
            summary["status"] = "runtime_unqualified"
            # Issue #53: the delegated client only ever runs requests, so its
            # failure is attributed to the generate stage explicitly.
            summary["terminalFailureCategories"] = stages.fail("generate", client.stdout)
            summary["reason"] = "streaming product probe failed"
            write(summary_path, summary)
            raise SystemExit(2)

        summary["status"] = "completed"
        summary["result"] = str(stream_result)
        probe_rows: list[dict[str, Any]] = []
        if args.progressive_probe != "off":
            probe_tasks = task_rows[: max(0, args.progressive_probe_limit)]
            probe_error = None
            for task in probe_tasks:
                try:
                    probe_rows.append(stream_sse_progressive(
                        endpoint,
                        c["id"],
                        task,
                        # Issue #45: the frozen task's declared budget wins; the
                        # 900 default only applies when the task declares none.
                        max_tokens=resolve_task_max_new_tokens(
                            task,
                            default_max_new_tokens=client_default_max_tokens,
                            default_forced_choice_max_new_tokens=client_default_max_tokens,
                        ),
                        temperature=0.0,
                        top_p=1.0,
                        seed=0,
                        request_timeout=180.0,
                    ))
                except Exception as exc:
                    probe_error = f"{type(exc).__name__}: {exc}"
                    break
            progressive = PROGRESSIVE.summarize_progressive_option_timing(probe_rows)
            progressive["probeError"] = probe_error
            progressive["rawStreamEvidence"] = [
                {
                    "id": row["id"],
                    "output": row["output"],
                    "finishReason": row["finishReason"],
                    "streamChunkCount": row["streamChunkCount"],
                    "streamDeltaSha256": row["streamDeltaSha256"],
                    "diagnostics": row["diagnostics"],
                }
                for row in probe_rows
            ]
            if probe_error:
                progressive["supported"] = False
                progressive["limitation"] = f"progressive probe failed: {probe_error}"
                write(out_dir / "progressive-option-timing.json", progressive)
                if args.progressive_probe == "required":
                    summary["status"] = "runtime_unqualified"
                    # Issue #53: the in-process probe streams requests, so its
                    # failure belongs to the generate stage.
                    summary["terminalFailureCategories"] = stages.fail("generate", probe_error)
                    summary["reason"] = "required progressive usable-option probe failed"
                    summary["progressiveOptionTiming"] = progressive
                    write(summary_path, summary)
                    raise SystemExit(2)
            else:
                progressive["supported"] = True
                write(out_dir / "progressive-option-timing.json", progressive)
                summary["progressiveResult"] = str(out_dir / "progressive-option-timing.json")
            summary["progressiveOptionTiming"] = progressive
        stages.finish(
            "generate",
            status="completed",
            streamedAttempts=len(probe_rows) if args.progressive_probe != "off" else None,
        )
        write(summary_path, summary)
        print(json.dumps({"status": "completed", "summary": str(summary_path), "result": str(stream_result)}, indent=2))
    finally:
        # Cleanup signals only the child this run spawned; an unrelated listener
        # that grabbed the port is never killed.
        stages.enter("cleanup")
        cleanup = server.terminate()
        summary["serverCleanup"] = cleanup
        summary["serverStopped"] = cleanup.get("stopped") is True
        summary["serverReturnCode"] = cleanup.get("returnCode")
        summary["serverSignalledPids"] = cleanup.get("signalledPids") or []
        stages.finish(
            "cleanup",
            status="completed" if cleanup.get("stopped") is True else "failed",
            stopped=cleanup.get("stopped"),
            returnCode=cleanup.get("returnCode"),
        )
        if server_log.exists():
            log_text = server_log.read_text(encoding="utf-8", errors="replace")
            if "building wheel for" in log_text.lower() or "cmake" in log_text.lower() or "ninja" in log_text.lower():
                summary["sourceBuildIndicatorDetected"] = True
                summary["status"] = "runtime_unqualified"
                summary["terminalFailureCategories"] = list(dict.fromkeys([
                    *(summary.get("terminalFailureCategories") or []), "source_build_attempt_forbidden"
                ]))
        write(summary_path, summary)


if __name__ == "__main__":
    main()
