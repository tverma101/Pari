#!/usr/bin/env python3
"""Versioned, provenance-bound checkpoint and resume machinery for Kaggle runs.

This module owns the mechanical guarantees Issue #30 requires so an interrupted
run cannot silently duplicate, skip, reorder, or erase benchmark work:

* one explicit checkpoint artifact per run unit (candidate-stage or roster unit),
  versioned and bound to the provenance that produced it;
* atomic checkpoint writes (temp file + ``os.replace``), so a crash never leaves
  a half-written checkpoint that a later resume would trust;
* durable-output-before-completion ordering, so a unit is never marked complete
  before its output row exists on disk;
* strict canonical-order validation (no duplicate, skipped, or reordered IDs);
* refusal, not guessing, when an existing checkpoint is incompatible;
* an explicit terminal status for every unit, including abnormal paths;
* cleanup of only the subprocesses this wrapper owns.

It contains no model, prompt, quantization, or runtime-selection logic.

Test seam: set ``PARI_KAGGLE_FAULT_INJECT`` to ``hard:<point>`` (simulates
SIGKILL, no cleanup runs) or ``soft:<point>`` (simulates SIGTERM, cleanup runs)
to abort at a named boundary. The fault-injection CPU tests use this to prove
crash-safety; production runs leave the variable unset.
"""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

SCHEMA_VERSION = 1
CHECKPOINT_SUFFIX = ".checkpoint.json"

#: Every terminal status a candidate-stage summary is allowed to end in.
TERMINAL_STATUSES = frozenset({
    "completed",
    "runtime_unqualified",
    "benchmark_failed",
    "infrastructure_failed",
    "interrupted_resume_available",
})

#: Child-issued terminal statuses that are more specific than our own mapping and
#: must be preserved verbatim instead of being flattened to ``benchmark_failed``.
_PRESERVED_CHILD_TERMINAL = frozenset({
    "runtime_unqualified",
    "benchmark_tool_failure",
    "benchmark_validation_failure",
    "completed",
})

#: Named abort boundaries exercised by the fault-injection tests.
FAULT_POINTS = (
    "before_first_task",
    "after_output_before_checkpoint",
    "after_checkpoint",
    "midway_batch",
    "during_word_studio",
    "after_final_task_before_summary",
    "during_teardown",
)

#: Telemetry sampling cadence (Issue #31). Bounded on purpose: a receipt must
#: never be the reason a sweep misses its window.
TELEMETRY_MAX_SAMPLES = 64
TELEMETRY_SAMPLE_INTERVAL_SECONDS = 30.0

#: Generated output families that live under the benchmark directory but are
#: *not* benchmark source: they are self-check products, so their presence must
#: not poison the clean-tree policy (Issue #40 test case 6). Each entry matches a
#: path prefix; anything not listed still counts as a relevant change.
IGNORED_GENERATED_PREFIXES = (
    "open-local-phraser-v1/benchmarks/english-studio-v3/__pycache__/",
    "open-local-phraser-v1/benchmarks/english-studio-v3/studio_backend/__pycache__/",
    "open-local-phraser-v1/benchmarks/english-studio-v3/english-core-shadow",
    "open-local-phraser-v1/benchmarks/english-studio-v3/english-core-prompt-robustness",
    "open-local-phraser-v1/benchmarks/english-studio-v3/english-core-choice-order-robustness",
)

#: Generated benchmark *inputs* a Kaggle job legitimately materializes into the
#: checkout after cloning the pinned commit, from a hash-verified private bundle.
#: These are prepared task artifacts, not untrusted local edits, so they are
#: tracked separately from ignorable noise and are accepted only when a receipt
#: verifies them.
PREPARED_TASK_INPUT_NAMES = (
    "english-core-fixed-screen.jsonl",
    "word-studio-strength.jsonl",
    "word-studio-transform.jsonl",
    "kaggle-protocol-smoke.jsonl",
    "english-core-shadow.jsonl",
    "english-core-prompt-robustness.jsonl",
    "english-core-choice-order-robustness.jsonl",
    "kaggle-stage-manifest.prepared.json",
)


def prepared_task_input_names(receipt: Path | str | None) -> set[str]:
    """Task input files the receipt verifies as the intended prepared bundle.

    The receipt is the only source of permission. When it is absent or lists
    nothing, no prepared input is trusted and an untracked task file under the
    benchmark tree is treated as a relevant change like any other untracked
    source.
    """
    if receipt is None or not Path(receipt).is_file():
        return set()
    try:
        payload = json.loads(Path(receipt).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    if not isinstance(payload, dict):
        return set()
    approved: set[str] = set()
    for entry in payload.get("files") or payload.get("artifacts") or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("path") or entry.get("file")
        if name and Path(str(name)).name in PREPARED_TASK_INPUT_NAMES:
            approved.add(str(name))
    return approved

_ENV_FAULT = "PARI_KAGGLE_FAULT_INJECT"

#: Full SHA-1 length. Promotion-quality execution requires a full commit id.
FULL_SHA_LENGTH = 40


class CheckpointError(RuntimeError):
    """Base class for checkpoint contract violations."""


class IncompatibleCheckpoint(CheckpointError):
    """An existing checkpoint cannot be resumed against the current run."""


class CorruptCheckpoint(CheckpointError):
    """A checkpoint or result artifact could not be parsed."""


class InjectedInterrupt(BaseException):
    """Raised by the fault-injection seam to simulate SIGTERM."""


# ---------------------------------------------------------------------------
# atomic IO helpers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def canonical_json(value: Any) -> str:
    """Stable JSON encoding used for hashing and on-disk artifacts."""
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _fsync_dir(directory: Path) -> None:
    dir_fd = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def atomic_write_json(path: Path, value: Any) -> None:
    """Write JSON via temp file + atomic replace, fsyncing file and directory."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(canonical_json(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)


def atomic_write_text(path: Path, text: str) -> None:
    """Atomic text write with the same durability contract as atomic_write_json."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    _fsync_dir(path.parent)


def sha256_file(path: Path | str | None) -> str | None:
    """SHA-256 of a file, or ``None`` when the artifact is absent."""
    if path is None:
        return None
    candidate = Path(path)
    if not candidate.is_file():
        return None
    digest = hashlib.sha256()
    with open(candidate, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    """SHA-256 over canonical JSON, for identity of structured configuration."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# git identity guard (Issue #40)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GitIdentity:
    """Verified identity of the code actually being executed.

    Commit identity is authoritative; branch and ref are informational only.
    """

    repo_root: str
    head: str
    tree: str | None
    branch: str | None
    status_porcelain: tuple[str, ...]
    relevant_status_porcelain: tuple[str, ...]
    relevant_prefix: str
    promotion_eligible: bool
    approved_prepared_inputs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "repoRoot": self.repo_root,
            "head": self.head,
            "tree": self.tree,
            "branch": self.branch,
            "dirty": bool(self.status_porcelain),
            "relevantDirty": bool(self.relevant_status_porcelain),
            "relevantPaths": list(self.relevant_status_porcelain),
            "relevantPrefix": self.relevant_prefix,
            "promotionEligible": self.promotion_eligible,
            "approvedPreparedInputs": list(self.approved_prepared_inputs),
        }


def _git(repo_root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise CheckpointError(
            f"git {' '.join(args)} failed rc={proc.returncode} in {repo_root}: "
            f"{proc.stderr.strip()}"
        )
    return proc.stdout.strip()


def classify_git_status(
    lines: Iterable[str],
    relevant_prefix: str,
    approved_untracked: frozenset[str] | set[str] = frozenset(),
) -> tuple[str, ...]:
    """Split ``git status --porcelain`` lines into relevant benchmark changes.

    Only paths under the benchmark directory can invalidate promotion evidence.
    Untracked result artifacts elsewhere on the tree are ignored on purpose; an
    untracked file *inside* the benchmark directory is a relevant change.
    """
    relevant = []
    for raw in lines:
        line = raw.rstrip("\n")
        if len(line) < 4:
            continue
        entry = line[3:]
        if " -> " in entry:  # rename: the destination is what makes it dirty
            entry = entry.split(" -> ", 1)[1]
        entry = entry.strip('"')
        if entry.startswith(relevant_prefix):
            if line[:2] == "??":
                if entry.startswith(IGNORED_GENERATED_PREFIXES):
                    # Known generated self-check output, not benchmark source.
                    continue
                if Path(entry).name in approved_untracked:
                    # Prepared task input, explicitly receipt-verified.
                    continue
            relevant.append(line)
    return tuple(relevant)


def verify_git_identity(
    repo_root: Path | str,
    declared_revision: str,
    *,
    relevant_prefix: str = "open-local-phraser-v1/benchmarks/english-studio-v3",
    require_clean: bool = True,
    preparation_receipt: Path | str | None = None,
) -> GitIdentity:
    """Bind execution to the actual checked-out commit, failing closed.

    Refuses a short SHA, a declared revision that disagrees with ``HEAD``, an
    absent ``.git``, or a dirty benchmark tree. ``require_clean=False`` is the
    explicitly non-promotion debug mode: it still records that the tree is
    dirty so a summary cannot be mistaken for promotion evidence.
    """
    repo_root = Path(repo_root)
    if not (repo_root / ".git").exists():
        raise CheckpointError(
            f"no .git metadata under {repo_root}; canonical execution fails closed "
            "rather than trusting a caller-supplied revision"
        )

    head = _git(repo_root, "rev-parse", "HEAD")
    if len(head) != FULL_SHA_LENGTH or any(c not in "0123456789abcdef" for c in head):
        raise CheckpointError(
            f"git rev-parse HEAD did not yield a full {FULL_SHA_LENGTH}-character "
            f"commit SHA (got {head!r})"
        )

    tree = _git(repo_root, "rev-parse", "HEAD^{tree}") or None
    try:
        branch = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD") or None
    except CheckpointError:
        branch = None

    status_raw = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if status_raw.returncode != 0:
        raise CheckpointError(
            f"git status --porcelain failed rc={status_raw.returncode} in {repo_root}: "
            f"{status_raw.stderr.strip()}"
        )
    # Do NOT strip: porcelain's leading XY columns are the change markers, and
    # `??` (untracked) is how we distinguish ignorable generated output.
    status_lines = [line for line in status_raw.stdout.splitlines() if line.strip()]
    approved = prepared_task_input_names(preparation_receipt)
    relevant = classify_git_status(status_lines, relevant_prefix, approved)

    if len(declared_revision) != FULL_SHA_LENGTH:
        raise CheckpointError(
            f"declared --benchmark-revision {declared_revision!r} is not a full "
            f"{FULL_SHA_LENGTH}-character commit SHA; canonical runs require the "
            "exact commit id"
        )
    if declared_revision != head:
        raise CheckpointError(
            f"declared --benchmark-revision {declared_revision} does not match actual "
            f"HEAD {head} in {repo_root}; refusing to run code under a different identity"
        )

    if require_clean and relevant:
        raise CheckpointError(
            f"benchmark tree is dirty under {relevant_prefix}: {list(relevant)}; "
            "canonical runs require a clean immutable benchmark state"
        )

    return GitIdentity(
        repo_root=str(repo_root),
        head=head,
        tree=tree,
        branch=branch,
        status_porcelain=tuple(status_lines),
        relevant_status_porcelain=relevant,
        relevant_prefix=relevant_prefix,
        promotion_eligible=require_clean and not relevant,
        approved_prepared_inputs=tuple(sorted(approved)),
    )


# ---------------------------------------------------------------------------
# task manifest
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskManifest:
    """Canonical, ordered task identity for one run unit."""

    path: str
    role: str
    sha256: str
    ids: tuple[str, ...]

    def as_provenance_entry(self) -> dict[str, str]:
        return {"path": self.path, "role": self.role, "sha256": self.sha256}


def load_task_manifest(path: Path | str, role: str) -> TaskManifest:
    """Read a task file, requiring unique non-empty IDs in canonical file order."""
    path = Path(path)
    if not path.is_file():
        raise CheckpointError(f"missing task manifest: {path}")
    ids: list[str] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CorruptCheckpoint(f"{path}:{lineno} is not valid JSON: {exc}") from exc
        task_id = row.get("id")
        if not task_id:
            raise CheckpointError(f"{path}:{lineno} has no task id")
        ids.append(str(task_id))
    if not ids:
        raise CheckpointError(f"task manifest is empty: {path}")
    if len(ids) != len(set(ids)):
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        raise CheckpointError(f"task manifest has duplicate ids: {duplicates}")
    return TaskManifest(
        path=str(path),
        role=role,
        sha256=sha256_file(path) or "",
        ids=tuple(ids),
    )


# ---------------------------------------------------------------------------
# provenance (canonical Issue #33 shape)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Provenance:
    """Canonical nested provenance block for a candidate-stage summary.

    Key names are fixed by the Issue #33 contract and are validated by
    ``build-kaggle-candidate-matrix.py``; do not rename them.
    """

    benchmark_revision: str
    candidate_id: str
    candidate_revision: str
    candidate_config_sha256: str
    preflight_path: str
    preflight_sha256: str | None
    runtime_receipt_path: str | None
    runtime_receipt_sha256: str | None
    task_manifest_sha256s: tuple[dict[str, str], ...]
    task_files: tuple[str, ...]
    result_sha256: str | None = None
    parser_code_version: str = ""
    git_identity: dict[str, Any] | None = None

    PROVENANCE_KEYS = (
        "benchmarkRevision",
        "candidateRevision",
        "candidateConfigSha256",
        "preflightSha256",
        "preflightPath",
        "runtimeReceiptSha256",
        "runtimeReceiptPath",
        "taskManifestSha256s",
        "taskFiles",
        "resultSha256",
        "parserCodeVersion",
    )

    def to_dict(self) -> dict[str, Any]:
        block = {
            "benchmarkRevision": self.benchmark_revision,
            "candidateRevision": self.candidate_revision,
            "candidateConfigSha256": self.candidate_config_sha256,
            "preflightSha256": self.preflight_sha256,
            "preflightPath": self.preflight_path,
            "runtimeReceiptSha256": self.runtime_receipt_sha256,
            "runtimeReceiptPath": self.runtime_receipt_path,
            "taskManifestSha256s": [dict(entry) for entry in self.task_manifest_sha256s],
            "taskFiles": list(self.task_files),
            "resultSha256": self.result_sha256,
            "parserCodeVersion": self.parser_code_version,
            # Not part of the canonical key set, but the matrix needs the
            # candidate identity to group comparable rows.
            "candidate": self.candidate_id,
        }
        if self.git_identity is not None:
            block["gitIdentity"] = self.git_identity
        missing = [key for key in self.PROVENANCE_KEYS if key not in block]
        if missing:
            raise CheckpointError(f"provenance block missing required keys: {missing}")
        return block

    def with_result(self, result_sha256: str | None) -> "Provenance":
        """Return a copy carrying the durable result digest."""
        return Provenance(
            benchmark_revision=self.benchmark_revision,
            candidate_id=self.candidate_id,
            candidate_revision=self.candidate_revision,
            candidate_config_sha256=self.candidate_config_sha256,
            preflight_path=self.preflight_path,
            preflight_sha256=self.preflight_sha256,
            runtime_receipt_path=self.runtime_receipt_path,
            runtime_receipt_sha256=self.runtime_receipt_sha256,
            task_manifest_sha256s=self.task_manifest_sha256s,
            task_files=self.task_files,
            result_sha256=result_sha256,
            parser_code_version=self.parser_code_version,
            git_identity=self.git_identity,
        )


def parser_code_version(paths: Iterable[Path | str]) -> str:
    """Content digest of the parser/diagnostic sources that judge a result set."""
    digests = []
    for raw in sorted({str(Path(p)) for p in paths}, key=lambda name: Path(name).name):
        digest = sha256_file(raw)
        if digest is not None:
            digests.append({"source": Path(raw).name, "sha256": digest})
    if not digests:
        return "unavailable"
    primary = sorted(digests, key=lambda d: d["source"])[0]["source"]
    return f"{primary}+{sha256_json(digests)}"


# ---------------------------------------------------------------------------
# durable output reconciliation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DurableOutput:
    """Validation result for a child result artifact against the task manifest."""

    path: str
    sha256: str | None
    completed_ids: tuple[str, ...]
    next_index: int
    total: int
    complete: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "completedTaskIds": list(self.completed_ids),
            "nextTaskIndex": self.next_index,
            "taskCount": self.total,
            "complete": self.complete,
        }


def read_result_rows(result_path: Path | str) -> list[dict[str, Any]]:
    """Read output rows from a child result artifact."""
    result_path = Path(result_path)
    if not result_path.is_file():
        raise CorruptCheckpoint(f"durable result artifact missing: {result_path}")
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CorruptCheckpoint(f"durable result is not valid JSON: {result_path}: {exc}") from exc
    rows = payload.get("outputs")
    if not isinstance(rows, list):
        raise CorruptCheckpoint(f"durable result has no outputs list: {result_path}")
    return [row for row in rows if isinstance(row, dict)]


def validate_durable_output(result_path: Path | str, manifest: TaskManifest) -> DurableOutput:
    """Validate a child result against the manifest.

    Accepts only an exact canonical prefix: no duplicates, no gaps, no
    reordering.
    """
    rows = read_result_rows(result_path)
    observed = [str(row.get("id")) for row in rows]
    if len(observed) != len(set(observed)):
        duplicates = sorted({i for i in observed if observed.count(i) > 1})
        raise CheckpointError(
            f"{result_path} contains duplicate task ids {duplicates}; refusing to resume"
        )
    total = len(manifest.ids)
    if len(observed) > total:
        raise CheckpointError(
            f"{result_path} has {len(observed)} rows but manifest {manifest.path} declares {total}"
        )
    for index, task_id in enumerate(observed):
        if task_id == manifest.ids[index]:
            continue
        seen = set(observed)
        if seen.issubset(set(manifest.ids[: index + 1])):
            detail = "reordered ids"
        else:
            detail = "skipped or unknown ids"
        raise CheckpointError(
            f"{result_path} is not a canonical prefix of {manifest.path}; "
            f"row {index} is {task_id!r}, expected {manifest.ids[index]!r} ({detail})"
        )
    return DurableOutput(
        path=str(result_path),
        sha256=sha256_file(result_path),
        completed_ids=tuple(observed),
        next_index=len(observed),
        total=total,
        complete=len(observed) == total,
    )


def maybe_fault(point: str, context: str = "") -> None:
    """Fault-injection seam. See ``FAULT_POINTS`` and ``_ENV_FAULT``."""
    spec = os.environ.get(_ENV_FAULT, "").strip()
    if not spec:
        return
    mode, _, name = spec.partition(":")
    if name != point:
        return
    detail = f" [{context}]" if context else ""
    if mode == "hard":
        # Simulates SIGKILL: no Python cleanup, no atexit, no handler.
        print(f"FAULT-INJECT hard at {point}{detail}", file=sys.stderr, flush=True)
        os._exit(137)
    raise InjectedInterrupt(f"fault injected at {point}{detail}")


# ---------------------------------------------------------------------------
# owned subprocess management
# ---------------------------------------------------------------------------


@dataclass
class CleanupRecord:
    """Evidence of what the wrapper terminated, and whether it succeeded."""

    required: bool = False
    attempted: bool = False
    signaled: str | None = None
    escalated_to_kill: bool = False
    returncode: int | None = None
    outcome: str = "not_required"
    detail: str | None = None
    #: PIDs this unit provably launched, captured while the process group was
    #: still alive. Issue #57 consumers need this to tell orchestrator-owned
    #: residue apart from an unrelated foreign GPU process; an empty list means
    #: "nothing was proven owned", never "nothing was running".
    owned_pids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "attempted": self.attempted,
            "signal": self.signaled,
            "escalatedToKill": self.escalated_to_kill,
            "returnCode": self.returncode,
            "outcome": self.outcome,
            "detail": self.detail,
            "ownedPids": sorted(self.owned_pids),
        }


def _nvidia_smi_query(query: str) -> str | None:
    """Run one read-only nvidia-smi query; None when the tool is unavailable."""
    try:
        proc = subprocess.run(
            ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def _sample_gpu_snapshot(stage: str, owned_pids: list[int]) -> dict[str, Any]:
    """One bounded, read-only per-GPU telemetry snapshot (Issue #31).

    This is deliberately not a sampling loop: the wrapper samples once at launch
    and once after teardown, so a receipt can never become the reason a run
    overruns. Unavailability is recorded honestly rather than synthesized.
    """
    csv_text = _nvidia_smi_query("index,uuid,name,memory.total,memory.used,utilization.gpu")
    if csv_text is None:
        return {
            "stage": stage,
            "timestamp": now_iso(),
            "gpus": [],
            "nvidiaSmiAvailable": False,
            "ownedProcessIds": sorted(owned_pids),
        }
    try:
        import kaggle_telemetry

        samples = kaggle_telemetry.parse_nvidia_smi_csv(csv_text, stage=stage)
    except Exception as exc:  # noqa: BLE001 - telemetry must never fail a run
        return {
            "stage": stage,
            "timestamp": now_iso(),
            "gpus": [],
            "nvidiaSmiAvailable": False,
            "telemetryError": f"{type(exc).__name__}: {exc}",
            "ownedProcessIds": sorted(owned_pids),
        }
    snapshot = kaggle_telemetry.make_snapshot(
        stage, gpu_samples=samples, owned_pids=owned_pids
    )
    snapshot["nvidiaSmiAvailable"] = True
    return snapshot


class OwnedProcessGroup:
    """A subprocess in its own process group, terminated only on our teardown.

    The child wrapper spawns its own model server; putting the child in a fresh
    process group means teardown can signal the child's whole tree without
    touching any unrelated GPU process on the machine.
    """

    def __init__(self, cmd: Sequence[str], log_path: Path | str):
        self.cmd = list(cmd)
        self.log_path = Path(log_path)
        self.proc: subprocess.Popen | None = None
        #: Union of every PID ever proven to be in this child's process group.
        #: A reaper needs the set captured *before* teardown: once the group is
        #: gone there is nothing left to enumerate, and an empty set would make
        #: surviving residue look foreign.
        self._owned_pids: set[int] = set()

    def start(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(
            self.cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        # Capture the group immediately: this is the only moment the launcher
        # PID is unambiguously ours.
        self.observe_owned_pids()

    @property
    def returncode(self) -> int | None:
        return None if self.proc is None else self.proc.returncode

    def _process_group_pids(self, group: int) -> set[int]:
        """PIDs currently in `group`, proven by process-group membership.

        Two sources, both exact. `/proc/<pid>/stat` exposes the parent PID,
        which equals the process group for a session leader, so that is the
        Linux/Kaggle path. macOS and other BSD hosts have no `/proc`, so the
        equivalent `ps` listing is filtered by the real PGID column.

        Deliberately absent: the whole-machine GPU process table. That listing
        contains unrelated notebook and user work, and treating every PID in it
        as ours would let teardown signal a foreign process -- the exact failure
        Issue #57 forbids. An unprovable PID is reported foreign and blocked
        instead.
        """
        found: set[int] = set()
        proc_dir = Path("/proc")
        if proc_dir.is_dir():
            for entry in proc_dir.iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    # Field 5 (index 4) is the parent PID, which is the process
                    # group for a session leader started with start_new_session.
                    stat_fields = (entry / "stat").read_text(encoding="utf-8").split()
                    if int(stat_fields[4]) == group:
                        found.add(int(entry.name))
                except (OSError, ValueError, IndexError):
                    continue
            return found
        return self._process_group_pids_via_ps(group)

    @staticmethod
    def _process_group_pids_via_ps(group: int) -> set[int]:
        """Process-group membership on hosts without `/proc` (macOS, BSD)."""
        found: set[int] = set()
        try:
            proc = subprocess.run(
                ["ps", "-axo", "pid=,pgid="],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            return found
        if proc.returncode != 0:
            return found
        for line in (proc.stdout or "").splitlines():
            parts = line.split()
            if len(parts) != 2:
                continue
            try:
                if int(parts[1]) == group:
                    found.add(int(parts[0]))
            except ValueError:
                continue
        return found

    def observe_owned_pids(self) -> list[int]:
        """Record the PIDs currently provably in this child's own group.

        Ownership here means "same session/process group as the process this
        object launched", which is exactly what `start_new_session=True`
        establishes. Nothing else qualifies: a PID is never added because
        nvidia-smi happens to report it using GPU memory.

        That distinction is deliberate. The whole-sweep GPU process table
        contains unrelated notebook and user work, so treating every PID in it
        as owned would let cleanup signal a foreign process -- the precise
        failure Issue #57 forbids. Where neither `/proc` nor `ps` can prove group
        membership, only the launcher PID is recorded and any surviving residue
        is reported as foreign and blocked, which is the fail-closed direction.
        """
        if self.proc is None:
            return sorted(self._owned_pids)
        pid = self.proc.pid
        try:
            group = os.getpgid(pid)
        except (ProcessLookupError, PermissionError, OSError):
            self._owned_pids.add(pid)
            return sorted(self._owned_pids)
        # The launcher's parent PID equals its process group only while it is
        # the session leader; if something reparented it, trust the PID alone.
        self._owned_pids.add(pid)
        self._owned_pids |= self._process_group_pids(group)
        return sorted(self._owned_pids)

    def owned_pids(self) -> list[int]:
        """Every PID ever proven to be in this child's own process group.

        Cumulative by design: after teardown the group is gone and a fresh scan
        would return almost nothing, which would erase the evidence a caller
        needs to reap or report residue.
        """
        return self.observe_owned_pids()

    def wait(self, timeout: float | None = None) -> int | None:
        if self.proc is None:
            return None
        return self.proc.wait(timeout=timeout)

    def drain_output(self) -> str:
        """Read the child's captured output to EOF; safe after it has exited."""
        if self.proc is None or self.proc.stdout is None:
            return ""
        try:
            output = self.proc.stdout.read() or ""
        except (ValueError, OSError):
            return ""
        if output:
            atomic_write_text(self.log_path, output)
        return output

    def terminate_owned(self, grace_seconds: float = 20.0) -> CleanupRecord:
        """SIGTERM then SIGKILL this group only, and reap it."""
        record = CleanupRecord(required=True, attempted=True)
        proc = self.proc
        if proc is None:
            record.outcome = "never_started"
            return record
        # Snapshot ownership before signalling: after the group exits there is
        # nothing left to enumerate, and the caller still needs this evidence.
        record.owned_pids = self.owned_pids()
        if proc.poll() is not None:
            record.outcome = "already_exited"
            record.returncode = proc.returncode
            return record
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            record.signaled = "SIGTERM"
        except (ProcessLookupError, PermissionError) as exc:
            record.outcome = "group_gone"
            record.detail = f"{type(exc).__name__}: {exc}"
            proc.wait()
            record.returncode = proc.returncode
            return record
        try:
            proc.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            record.escalated_to_kill = True
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                record.signaled = "SIGKILL"
            except (ProcessLookupError, PermissionError) as exc:
                record.detail = f"{type(exc).__name__}: {exc}"
            proc.wait()
        record.returncode = proc.returncode
        record.outcome = "terminated"
        return record

    def reap(self) -> CleanupRecord:
        """Collect the exit status of an already-finished child."""
        proc = self.proc
        if proc is None:
            return CleanupRecord(outcome="never_started")
        owned = self.owned_pids()
        try:
            proc.wait(timeout=0)
        except subprocess.TimeoutExpired:
            return CleanupRecord(
                required=True,
                attempted=False,
                outcome="still_running",
                detail="reap skipped; child had not exited",
                owned_pids=owned,
            )
        return CleanupRecord(
            returncode=proc.returncode,
            outcome="already_exited",
            owned_pids=owned,
        )


# ---------------------------------------------------------------------------
# checkpoint
# ---------------------------------------------------------------------------


@dataclass
class RunCheckpoint:
    """Versioned, provenance-bound resume state for a single run unit."""

    path: Path
    unit_kind: str
    unit_id: str
    provenance: Provenance
    manifest: TaskManifest | None
    completed_ids: list[str] = field(default_factory=list)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    next_task_index: int = 0
    status: str = "running"
    terminal_reason: str | None = None
    durable_outputs: list[dict[str, Any]] = field(default_factory=list)
    cleanup: list[dict[str, Any]] = field(default_factory=list)
    resumed_from_index: int = 0
    created_at: str = ""
    updated_at: str = ""

    @staticmethod
    def checkpoint_path(results_dir: Path | str, *parts: str) -> Path:
        return Path(results_dir).joinpath(*parts[:-1], parts[-1] + CHECKPOINT_SUFFIX)

    def identity(self) -> dict[str, Any]:
        """Fields that must match exactly for a resume to be legal."""
        return {
            "schemaVersion": SCHEMA_VERSION,
            "unitKind": self.unit_kind,
            "unitId": self.unit_id,
            "provenance": self.provenance.to_dict(),
            "taskManifestSha256": self.manifest.sha256 if self.manifest else None,
            "taskCount": len(self.manifest.ids) if self.manifest else None,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.identity()
        payload.update({
            "completedTaskIds": list(self.completed_ids),
            "nextTaskIndex": self.next_task_index,
            "resumedFromTaskIndex": self.resumed_from_index,
            "status": self.status,
            "terminalReason": self.terminal_reason,
            "attempts": list(self.attempts),
            "durableOutputs": list(self.durable_outputs),
            "cleanup": list(self.cleanup),
            "createdAt": self.created_at or now_iso(),
            "updatedAt": self.updated_at or now_iso(),
        })
        return payload

    def save(self) -> None:
        self.updated_at = now_iso()
        if not self.created_at:
            self.created_at = self.updated_at
        atomic_write_json(self.path, self.to_dict())

    @classmethod
    def load_or_create(
        cls,
        path: Path | str,
        unit_kind: str,
        unit_id: str,
        provenance: Provenance,
        manifest: TaskManifest | None,
    ) -> tuple["RunCheckpoint", bool]:
        """Load a compatible checkpoint, or create a fresh one.

        Returns ``(checkpoint, resumed)``. An existing checkpoint whose identity
        does not match the current run raises :class:`IncompatibleCheckpoint`
        instead of being silently reused or overwritten.
        """
        path = Path(path)
        if not path.is_file():
            checkpoint = cls(
                path=path,
                unit_kind=unit_kind,
                unit_id=unit_id,
                provenance=provenance,
                manifest=manifest,
            )
            checkpoint.save()
            return checkpoint, False

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CorruptCheckpoint(
                f"checkpoint {path} is not valid JSON; refusing to guess: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise CorruptCheckpoint(f"checkpoint {path} is not a JSON object")

        candidate = cls(
            path=path,
            unit_kind=unit_kind,
            unit_id=unit_id,
            provenance=provenance,
            manifest=manifest,
        )
        candidate.created_at = str(payload.get("createdAt") or "")

        version = payload.get("schemaVersion")
        if version != SCHEMA_VERSION:
            raise IncompatibleCheckpoint(
                f"checkpoint {path} has schemaVersion {version!r}, expected {SCHEMA_VERSION}"
            )
        for field_name, expected, label in (
            ("unitKind", unit_kind, "unit kind"),
            ("unitId", unit_id, "unit id"),
            (
                "taskManifestSha256",
                manifest.sha256 if manifest else None,
                "task manifest sha256",
            ),
            ("taskCount", len(manifest.ids) if manifest else None, "task count"),
        ):
            actual = payload.get(field_name)
            if actual != expected:
                raise IncompatibleCheckpoint(
                    f"checkpoint {path} {label} is {actual!r}, current run has {expected!r}; "
                    "refusing to resume"
                )
        stored_provenance = payload.get("provenance")
        current_provenance = provenance.to_dict()
        if stored_provenance != current_provenance:
            keys = set(stored_provenance) if isinstance(stored_provenance, dict) else set()
            differing = sorted(
                key
                for key in keys | set(current_provenance)
                if (stored_provenance or {}).get(key) != current_provenance.get(key)
            )
            raise IncompatibleCheckpoint(
                f"checkpoint {path} provenance differs from the current run in {differing}; "
                "refusing to resume"
            )

        completed = payload.get("completedTaskIds")
        if not isinstance(completed, list):
            raise CorruptCheckpoint(f"checkpoint {path} has no completedTaskIds list")
        if len(completed) != len(set(completed)):
            raise CorruptCheckpoint(f"checkpoint {path} contains duplicate completed task ids")
        if manifest is not None:
            expected_prefix = list(manifest.ids[: len(completed)])
            if completed != expected_prefix:
                raise IncompatibleCheckpoint(
                    f"checkpoint {path} completed task ids are not a canonical prefix of "
                    f"the manifest; refusing to resume "
                    f"(checkpoint={completed}, expected={expected_prefix})"
                )
        declared_next = payload.get("nextTaskIndex")
        if declared_next != len(completed):
            raise CorruptCheckpoint(
                f"checkpoint {path} nextTaskIndex {declared_next!r} does not match "
                f"{len(completed)} completed ids"
            )

        candidate.completed_ids = [str(i) for i in completed]
        candidate.next_task_index = len(completed)
        candidate.resumed_from_index = len(completed)
        candidate.attempts = list(payload.get("attempts") or [])
        candidate.durable_outputs = list(payload.get("durableOutputs") or [])
        candidate.cleanup = list(payload.get("cleanup") or [])
        candidate.status = str(payload.get("status") or "running")
        candidate.terminal_reason = payload.get("terminalReason")
        return candidate, True

    def record_attempt(self, attempt: dict[str, Any]) -> None:
        """Append attempt evidence. Attempts are never rewritten or removed."""
        entry = dict(attempt)
        entry["attemptIndex"] = len(self.attempts) + 1
        entry["recordedAt"] = now_iso()
        self.attempts.append(entry)
        self.save()

    def record_cleanup(self, record: CleanupRecord) -> None:
        self.cleanup.append(record.to_dict())
        self.save()

    def record_durable_output(self, output: DurableOutput) -> None:
        self.durable_outputs.append(output.to_dict())
        self.save()

    def complete_through(self, output: DurableOutput) -> None:
        """Advance the completed prefix. Refuses gaps, duplicates, reordering."""
        current = list(self.completed_ids)
        incoming = list(output.completed_ids)
        if incoming[: len(current)] != current:
            raise CheckpointError(
                f"refusing to checkpoint: new output prefix {incoming} does not extend "
                f"already-checkpointed prefix {current}"
            )
        self.completed_ids = incoming
        self.next_task_index = len(incoming)
        self.save()

    def mark_terminal(self, status: str, reason: str | None = None) -> None:
        if status not in TERMINAL_STATUSES:
            raise CheckpointError(f"{status!r} is not a terminal status")
        self.status = status
        self.terminal_reason = reason
        self.save()

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


def classify_terminal_status(
    returncode: int | None,
    child_summary: dict[str, Any] | None,
    durable: DurableOutput | None,
    interrupted: bool = False,
    manifest: TaskManifest | None = None,
) -> tuple[str, str]:
    """Map an outcome onto exactly one terminal status, plus a reason string."""
    child_status = (child_summary or {}).get("status")
    if returncode == 0 and child_status == "completed":
        return "completed", "child reported completed"
    if returncode == 0 and manifest is None:
        # Infrastructure units (preparation verification, Q0/Q1 gates) produce no
        # task rows and no stage summary; a clean exit is their success state.
        return "completed", "infrastructure unit exited 0"
    if child_status in _PRESERVED_CHILD_TERMINAL and returncode not in (0, None):
        return str(child_status), f"child reported {child_status}"
    if interrupted:
        if durable is not None and durable.completed_ids:
            return (
                "interrupted_resume_available",
                f"interrupted after {durable.next_index}/{durable.total} durable task rows",
            )
        return "infrastructure_failed", "interrupted before any durable task row"
    if child_status is None and returncode not in (0, None):
        return (
            "infrastructure_failed",
            f"run unit exited rc={returncode} without writing a summary",
        )
    if child_status in _PRESERVED_CHILD_TERMINAL:
        # rc=0 with a terminal child status that is not "completed" means the
        # wrapper exited 0 without a usable stage result.
        return str(child_status), f"child reported {child_status} with rc=0"
    if durable is not None and durable.complete:
        return "benchmark_failed", "durable rows exist but the child never reported completed"
    return (
        "benchmark_failed",
        f"run unit finished rc={returncode} childStatus={child_status!r} without a completed stage",
    )


# ---------------------------------------------------------------------------
# summary emission
# ---------------------------------------------------------------------------


def finalize_summary(
    summary_path: Path | str,
    terminal_status: str,
    provenance: Provenance,
    *,
    cleanup: CleanupRecord | None = None,
    extra: dict[str, Any] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Merge a canonical terminal status and provenance into a stage summary.

    The child's own summary is preserved; only the status, provenance, resume,
    and cleanup blocks are set, so no attempt or failure evidence is lost.
    """
    summary_path = Path(summary_path)
    payload: dict[str, Any] = {}
    if summary_path.is_file():
        try:
            loaded = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except json.JSONDecodeError:
            # Never delete a corrupt summary: move it aside and keep the evidence.
            preserved = summary_path.with_name(summary_path.name + ".corrupt")
            os.replace(summary_path, preserved)
            payload = {
                "preservedCorruptSummary": str(preserved),
                "previousStatus": "unreadable",
            }
    payload["status"] = terminal_status
    payload["terminal"] = True
    if reason:
        payload["terminalReason"] = reason
    payload["provenance"] = provenance.to_dict()
    if cleanup is not None:
        payload["processCleanup"] = cleanup.to_dict()
    if extra:
        payload.update(extra)
    atomic_write_json(summary_path, payload)
    return payload


# ---------------------------------------------------------------------------
# unit execution
# ---------------------------------------------------------------------------


@dataclass
class UnitResult:
    """Outcome of one checkpointed run unit."""

    status: str
    reason: str
    returncode: int | None
    durable: DurableOutput | None
    cleanup: CleanupRecord
    log_path: Path
    summary_path: Path | None
    checkpoint_path: Path
    attempts: int
    #: Every PID this unit provably launched, unioned across its whole
    #: lifetime. Issue #57 needs this so a supervisor can pass exactly the
    #: orchestrator-owned set to the GPU resource gate: only these PIDs may be
    #: treated as reapable residue, and every other GPU process stays foreign,
    #: is recorded, and is never signalled. Empty on a resume that launched
    #: nothing, which is different from "ran and owned nothing".
    owned_pids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "returnCode": self.returncode,
            "durable": self.durable.to_dict() if self.durable else None,
            "cleanup": self.cleanup.to_dict(),
            "log": str(self.log_path),
            "summary": str(self.summary_path) if self.summary_path else None,
            "checkpoint": str(self.checkpoint_path),
            "attempts": self.attempts,
            "ownedPids": sorted(self.owned_pids),
        }


def execute_unit(
    *,
    unit_id: str,
    unit_kind: str,
    cmd: Sequence[str],
    provenance: Provenance,
    checkpoint_path: Path | str,
    log_path: Path | str,
    manifest: TaskManifest | None = None,
    summary_path: Path | str | None = None,
    result_path: Path | str | None = None,
    resolve_result_path: Callable[[], Path | str | None] | None = None,
    timeout_seconds: float | None = None,
    stage: str | None = None,
    summary_extra: dict[str, Any] | None = None,
    on_resume_available: Callable[[dict[str, Any]], None] | None = None,
) -> UnitResult:
    """Run one checkpointed unit with crash-safe resume and terminal status.

    Ordering is deliberate: durable output is validated and recorded *before*
    the checkpoint advances, so a crash can only ever cost work, never invent
    it. Every exit path (normal, nonzero, exception, timeout, SIGINT, SIGTERM)
    terminates only the process group this call created and emits a terminal
    status.

    ``manifest`` may be ``None`` for units that produce no task rows (for
    example preparation verification); such units are still checkpointed,
    versioned, provenance-bound, and terminal, but skip task reconciliation.
    ``resolve_result_path`` lets a caller discover the child's durable result
    after the child exits, for wrappers that pick a per-attempt filename.
    """
    checkpoint_path = Path(checkpoint_path)
    log_path = Path(log_path)
    summary_path = Path(summary_path) if summary_path is not None else None
    result_path = Path(result_path) if result_path is not None else None
    if result_path is not None and manifest is None:
        raise CheckpointError(
            "execute_unit requires a task manifest to validate a durable result"
        )

    checkpoint, resumed = RunCheckpoint.load_or_create(
        checkpoint_path, unit_kind, unit_id, provenance, manifest
    )

    if resumed and checkpoint.is_terminal and checkpoint.status == "completed":
        return UnitResult(
            status="completed",
            reason="checkpoint already terminal and complete; nothing to redo",
            returncode=0,
            durable=None,
            cleanup=CleanupRecord(outcome="already_complete"),
            log_path=log_path,
            summary_path=summary_path,
            checkpoint_path=checkpoint.path,
            attempts=len(checkpoint.attempts),
            # Nothing was launched on this path, so there is no owned PID set to
            # report; an empty list means "no process was started", not
            # "residue exists and is unowned".
            owned_pids=[],
        )

    maybe_fault(
        "before_first_task",
        f"{unit_id} resumeIndex={checkpoint.resumed_from_index}",
    )

    child = OwnedProcessGroup(cmd, log_path)
    cleanup = CleanupRecord()
    durable: DurableOutput | None = None
    child_summary: dict[str, Any] | None = None
    returncode: int | None = None
    interrupted_reason: str | None = None
    resumed_from = checkpoint.resumed_from_index
    previous_handlers: dict[int, Any] = {}

    def _on_signal(signum: int, _frame: Any) -> None:
        nonlocal interrupted_reason
        interrupted_reason = f"received {signal.Signals(signum).name}"
        child.terminate_owned()
        raise KeyboardInterrupt(interrupted_reason)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            previous_handlers.pop(sig, None)

    try:
        child.start()
        checkpoint.record_attempt({
            "unit": unit_id,
            "kind": "launch",
            "command": list(cmd),
            "startedAt": now_iso(),
            "resumeIndex": checkpoint.next_task_index,
        })
        pre_snapshot = _sample_gpu_snapshot(f"{unit_id}:launch", child.owned_pids())
        try:
            returncode = child.wait(timeout=timeout_seconds)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out = True
            interrupted_reason = f"timeout after {timeout_seconds}s"
            # terminate_owned snapshots the group while it is still alive, so
            # the cleanup evidence names the exact PIDs this unit owned.
            cleanup = child.terminate_owned()
            returncode = child.returncode
            interrupted_reason = f"{interrupted_reason}; rc={returncode}"
        child.drain_output()
        del timed_out
    except KeyboardInterrupt as exc:
        cleanup = child.terminate_owned()
        returncode = child.returncode
        interrupted_reason = interrupted_reason or f"interrupted: {exc}"
        child.drain_output()
    except InjectedInterrupt:
        cleanup = child.terminate_owned()
        returncode = child.returncode
        child.drain_output()
        checkpoint.record_cleanup(cleanup)
        raise
    except Exception:
        cleanup = child.terminate_owned()
        returncode = child.returncode
        child.drain_output()
        checkpoint.record_cleanup(cleanup)
        raise
    finally:
        for sig, handler in previous_handlers.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass

    if cleanup.outcome in {"not_required", "never_started"}:
        cleanup = child.reap()
    maybe_fault("during_teardown", f"{unit_id} cleanup={cleanup.outcome}")
    checkpoint.record_cleanup(cleanup)

    # Post-teardown sampling is the honest cleanup proof: any GPU process still
    # attributed to our own process group after teardown would appear here.
    post_snapshot = _sample_gpu_snapshot(f"{unit_id}:post-teardown", child.owned_pids())
    try:
        import kaggle_telemetry

        resource_receipt = kaggle_telemetry.build_resource_receipt(
            run_identity={
                "unit": unit_id,
                "benchmarkRevision": provenance.benchmark_revision,
                "candidate": provenance.candidate_id,
                "stage": stage,
            },
            snapshots=[s for s in (pre_snapshot, post_snapshot) if s],
            nvidia_smi_available=bool(pre_snapshot.get("nvidiaSmiAvailable")),
            notes="bounded launch/post-teardown sampling; no loop, no cleanup claims beyond it",
        )
    except Exception as exc:  # noqa: BLE001 - telemetry must never fail a run
        resource_receipt = {
            "telemetryError": f"{type(exc).__name__}: {exc}",
            "nvidiaSmiAvailable": bool(pre_snapshot.get("nvidiaSmiAvailable")),
        }

    if summary_path is not None and summary_path.is_file():
        try:
            loaded = json.loads(summary_path.read_text(encoding="utf-8"))
            child_summary = loaded if isinstance(loaded, dict) else None
        except json.JSONDecodeError:
            child_summary = None

    # A wrapper may pick a per-attempt result filename, so the durable path can
    # only be resolved after the child has exited and written its summary.
    if manifest is not None and result_path is None and resolve_result_path is not None:
        resolved = resolve_result_path()
        result_path = Path(resolved) if resolved is not None else None

    if manifest is not None and result_path is not None and result_path.is_file():
        try:
            durable = validate_durable_output(result_path, manifest)
        except CheckpointError as exc:
            checkpoint.record_attempt({
                "unit": unit_id,
                "kind": "durable_output_rejected",
                "reason": str(exc),
                "returnCode": returncode,
            })
            status, reason = "benchmark_failed", str(exc)
            checkpoint.mark_terminal(status, reason)
            if summary_path is not None:
                finalize_summary(
                    summary_path, status, provenance, cleanup=cleanup, reason=reason
                )
            return UnitResult(
                status=status,
                reason=reason,
                returncode=returncode,
                durable=None,
                cleanup=cleanup,
                log_path=log_path,
                summary_path=summary_path,
                checkpoint_path=checkpoint.path,
                attempts=len(checkpoint.attempts),
                owned_pids=list(cleanup.owned_pids),
            )

        # Kill points #2/#4: durable rows exist but the checkpoint has not advanced.
        maybe_fault("midway_batch", f"{unit_id} rows={durable.next_index}/{durable.total}")
        if stage == "word-studio":
            maybe_fault("during_word_studio", f"{unit_id} rows={durable.next_index}")
        maybe_fault("after_output_before_checkpoint", f"{unit_id} rows={durable.next_index}")
        checkpoint.complete_through(durable)
        checkpoint.record_durable_output(durable)
        if durable.next_index > 0:
            print(
                f"resuming {unit_id} from durable task index "
                f"{durable.next_index}/{durable.total}",
                flush=True,
            )

    maybe_fault("after_checkpoint", f"{unit_id} next={checkpoint.next_task_index}")

    # Kill point #6: all tasks durable and checkpointed, summary not yet terminal.
    if durable is not None and durable.complete:
        maybe_fault("after_final_task_before_summary", unit_id)

    status, reason = classify_terminal_status(
        returncode,
        child_summary,
        durable,
        interrupted=interrupted_reason is not None,
        manifest=manifest,
    )
    if interrupted_reason:
        reason = f"{reason} ({interrupted_reason})"
    checkpoint.mark_terminal(status, reason)

    final_provenance = provenance.with_result(durable.sha256 if durable else None)
    if summary_path is not None:
        extra_block: dict[str, Any] = {
            "resume": {
                "schemaVersion": SCHEMA_VERSION,
                "checkpoint": str(checkpoint.path),
                "resumedFromTaskIndex": resumed_from,
                "completedTaskIds": list(checkpoint.completed_ids),
                "nextTaskIndex": checkpoint.next_task_index,
                "taskCount": len(manifest.ids) if manifest else None,
                "attempts": checkpoint.attempts,
                "taskManifest": manifest.as_provenance_entry() if manifest else None,
            },
        }
        if summary_extra:
            extra_block.update(summary_extra)
        extra_block["resourceReceipt"] = resource_receipt
        extra_block["telemetrySnapshots"] = [
            s for s in (pre_snapshot, post_snapshot) if s
        ]
        finalize_summary(
            summary_path,
            status,
            final_provenance,
            cleanup=cleanup,
            extra=extra_block,
            reason=reason,
        )

    if on_resume_available is not None and status == "interrupted_resume_available":
        on_resume_available({
            "unit": unit_id,
            "status": status,
            "reason": reason,
            "checkpoint": str(checkpoint.path),
            "nextTaskIndex": checkpoint.next_task_index,
            "taskCount": len(manifest.ids),
        })

    return UnitResult(
        status=status,
        reason=reason,
        returncode=returncode,
        durable=durable,
        cleanup=cleanup,
        log_path=log_path,
        summary_path=summary_path,
        checkpoint_path=checkpoint.path,
        attempts=len(checkpoint.attempts),
        # The cumulative set from the child wrapper, so a supervisor can hand
        # the gate exactly the PIDs this unit owned (Issue #57).
        owned_pids=list(child.owned_pids()),
    )
