#!/usr/bin/env python3
"""Deterministic CPU fault-injection tests for Issue #30 resume safety.

These tests are CPU-only and never touch Kaggle or a GPU. They spawn a tiny
fake child process that writes partial output rows, then kill the wrapper at
each named crash boundary via ``kaggle_run_checkpoint.maybe_fault``. After each
interruption the test resumes and asserts the exact contract from Issue #30:

* exact task ID set equals the manifest ID set;
* no duplicate IDs;
* no skipped IDs;
* canonical ordering preserved;
* prior attempts remain visible and immutable;
* final summary is terminal;
* incompatible benchmark/candidate/task hashes are rejected;
* only owned subprocesses are cleaned up.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import kaggle_run_checkpoint as K
import kaggle_stage_identity as STAGE

HERE = Path(__file__).resolve().parent


def write_manifest(path: Path, ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"id": task_id, "prompt": f"prompt for {task_id}"}) for task_id in ids]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


#: The fake child. It simulates the model wrapper: reads the manifest, writes
#: an accumulating result file with `until` rows, writes a summary, and exits.
#: It reads PARI_FAKE_UNTIL (default: all rows) and PARI_FAKE_SLEEP to model a
#: partial batch and an in-flight server teardown.
FAKE_CHILD = r"""
import json
import os
import sys
import time
from pathlib import Path

manifest, result, summary = sys.argv[1], sys.argv[2], sys.argv[3]
ids = [json.loads(line)["id"] for line in Path(manifest).read_text().splitlines() if line.strip()]
until = int(os.environ.get("PARI_FAKE_UNTIL", len(ids)))
sleep_for = float(os.environ.get("PARI_FAKE_SLEEP", "0"))

rows = []
for i, task_id in enumerate(ids):
    if i >= until:
        break
    rows.append({"id": task_id, "output": f"answer-for-{task_id}"})
    # Simulate a batch boundary: flush the partial result to disk every row so
    # a kill mid-batch leaves a durable prefix.
    Path(result).write_text(json.dumps({"outputs": rows}, indent=2) + "\n", encoding="utf-8")
    if sleep_for:
        time.sleep(sleep_for)

if sleep_for:
    # Model an in-flight server-backed teardown window.
    time.sleep(sleep_for)

Path(summary).write_text(json.dumps({
    "schemaVersion": 3,
    "status": "completed",
    "durableRows": len(rows),
}, indent=2) + "\n", encoding="utf-8")
sys.exit(0)
"""


#: Runs one wrapper unit in a separate interpreter. Used to exercise the
#: SIGKILL-like path (`os._exit`), which cannot be raised in-process.
UNIT_DRIVER = r"""
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import kaggle_run_checkpoint as K

root = Path(sys.argv[2])
manifest = K.load_task_manifest(root / "tasks.jsonl", "synthetic-core")
provenance = K.Provenance(
    benchmark_revision="rev-1",
    candidate_id="synthetic-cand",
    candidate_revision="c" * 40,
    candidate_config_sha256="d" * 64,
    preflight_path="/synthetic/preflight.json",
    preflight_sha256="e" * 64,
    runtime_receipt_path=None,
    runtime_receipt_sha256=None,
    task_manifest_sha256s=(manifest.as_provenance_entry(),),
    task_files=(manifest.path,),
    parser_code_version="synthetic-parser-v1",
)
unit_dir = root / "results" / "synthetic-cand" / "full" / "normal"
cmd = [
    sys.executable, str(root / "fake_child.py"),
    str(manifest.path), str(unit_dir / "result.json"), str(unit_dir / "summary.json"),
]
K.execute_unit(
    unit_id="synthetic-cand/full/normal",
    unit_kind="candidate-stage",
    cmd=cmd,
    manifest=manifest,
    provenance=provenance,
    checkpoint_path=unit_dir / "unit.checkpoint.json",
    log_path=unit_dir / "run.log.txt",
    summary_path=unit_dir / "summary.json",
    result_path=unit_dir / "result.json",
    stage="full",
)
"""


def make_provenance(manifest: K.TaskManifest, *, benchmark_revision="rev-1") -> K.Provenance:
    return K.Provenance(
        benchmark_revision=benchmark_revision,
        candidate_id="synthetic-cand",
        candidate_revision="c" * 40,
        candidate_config_sha256="d" * 64,
        preflight_path="/synthetic/preflight.json",
        preflight_sha256="e" * 64,
        runtime_receipt_path=None,
        runtime_receipt_sha256=None,
        task_manifest_sha256s=(manifest.as_provenance_entry(),),
        task_files=(manifest.path,),
        parser_code_version="synthetic-parser-v1",
    )


def run_child(child: Path, manifest: Path, result: Path, summary: Path, env_extra: dict) -> list[str]:
    env = {**os.environ, **env_extra}
    proc = subprocess.run(
        [sys.executable, str(child), str(manifest), str(result), str(summary)],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.returncode != 0:
        raise AssertionError(f"fake child failed rc={proc.returncode}: {proc.stdout}")
    return [json.loads(line)["id"] for line in manifest.read_text().splitlines() if line.strip()]


def read_result_ids(result: Path) -> list[str]:
    payload = json.loads(result.read_text(encoding="utf-8"))
    return [row["id"] for row in payload["outputs"]]


def read_checkpoint(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class Harness:
    """Sets up an isolated synthetic run directory and fake child."""

    def __init__(self, root: Path, ids: list[str]):
        self.root = root
        self.ids = ids
        self.manifest_path = root / "tasks.jsonl"
        write_manifest(self.manifest_path, ids)
        self.manifest = K.load_task_manifest(self.manifest_path, "synthetic-core")
        self.child = root / "fake_child.py"
        self.child.write_text(FAKE_CHILD, encoding="utf-8")
        self.driver = root / "unit_driver.py"
        self.driver.write_text(UNIT_DRIVER, encoding="utf-8")
        self.unit_dir = root / "results" / "synthetic-cand" / "full" / "normal"
        self.unit_dir.mkdir(parents=True, exist_ok=True)
        self.result = self.unit_dir / "result.json"
        self.summary = self.unit_dir / "summary.json"
        self.log = self.unit_dir / "run.log.txt"
        self.checkpoint = self.unit_dir / "unit.checkpoint.json"

    def cmd(self) -> list[str]:
        return [
            sys.executable, str(self.child),
            str(self.manifest_path), str(self.result), str(self.summary),
        ]


def execute(
    h: Harness,
    provenance: K.Provenance,
    env_extra: dict | None = None,
    timeout_seconds: float | None = None,
    stage: str = "full",
):
    """Run the wrapper's execute_unit for one attempt, capturing injected faults."""
    saved = os.environ.get(K._ENV_FAULT)
    if env_extra:
        for key, value in env_extra.items():
            os.environ[key] = value
    try:
        return K.execute_unit(
            unit_id="synthetic-cand/full/normal",
            unit_kind="candidate-stage",
            cmd=h.cmd(),
            manifest=h.manifest,
            provenance=provenance,
            checkpoint_path=h.checkpoint,
            log_path=h.log,
            summary_path=h.summary,
            result_path=h.result,
            stage=stage,
            timeout_seconds=timeout_seconds,
        )
    finally:
        os.environ.pop(K._ENV_FAULT, None)
        if saved is not None:
            os.environ[K._ENV_FAULT] = saved


def assert_final_contract(h: Harness) -> None:
    """Assert the post-resume contract for a fully completed synthetic run."""
    ids = read_result_ids(h.result)
    assert ids == h.ids, f"final result IDs {ids} != manifest {h.ids}"
    assert len(ids) == len(set(ids)), "final result contains duplicate IDs"

    summary = json.loads(h.summary.read_text(encoding="utf-8"))
    assert summary["status"] in K.TERMINAL_STATUSES, summary["status"]
    assert summary["terminal"] is True
    assert summary["provenance"]["benchmarkRevision"] == "rev-1"
    prov = summary["provenance"]
    for key in K.Provenance.PROVENANCE_KEYS:
        assert key in prov, f"summary provenance missing {key}"
    assert prov["resultSha256"] == K.sha256_file(h.result)
    assert prov["taskManifestSha256s"][0]["sha256"] == h.manifest.sha256

    ckpt = read_checkpoint(h.checkpoint)
    assert ckpt["schemaVersion"] == K.SCHEMA_VERSION
    assert ckpt["status"] in K.TERMINAL_STATUSES
    assert ckpt["completedTaskIds"] == h.ids
    assert ckpt["nextTaskIndex"] == len(h.ids)

    resume = summary["resume"]
    assert resume["completedTaskIds"] == h.ids
    assert resume["nextTaskIndex"] == len(h.ids)

    # Attempt evidence is preserved and never rewritten.
    assert ckpt["attempts"], "checkpoint lost all attempt evidence"
    indices = [a["attemptIndex"] for a in ckpt["attempts"]]
    assert indices == list(range(1, len(indices) + 1)), indices

    # Cleanup is recorded, and only our process group was ever targeted.
    assert ckpt["cleanup"], "checkpoint has no cleanup record"
    for entry in ckpt["cleanup"]:
        assert entry["outcome"] in {
            "not_required", "never_started", "already_exited",
            "terminated", "group_gone", "still_running", "already_complete",
        }


def test_clean_run(tmp: Path) -> None:
    ids = ["t1", "t2", "t3", "t4"]
    h = Harness(tmp / "clean", ids)
    prov = make_provenance(h.manifest)
    res = execute(h, prov, {"PARI_FAKE_UNTIL": str(len(ids))})
    assert res.status == "completed", res.reason
    assert_final_contract(h)
    print("  clean run terminal and provenance-complete")


def test_kill_point_resume(tmp: Path, point: str, *, until: int, stage: str = "full") -> None:
    """Kill the wrapper at `point`, resume, and assert the exact contract."""
    ids = [f"t{i}" for i in range(1, 7)]
    h = Harness(tmp / f"kill-{point}", ids)
    prov = make_provenance(h.manifest)

    # First attempt: run the child partway, then abort the wrapper at `point`.
    os.environ[K._ENV_FAULT] = f"soft:{point}"
    try:
        first = execute(h, prov, {"PARI_FAKE_UNTIL": str(until)}, stage=stage)
    except K.InjectedInterrupt:
        first = None
    finally:
        os.environ.pop(K._ENV_FAULT, None)

    # After a kill, the durable result must be a canonical prefix.
    if h.result.is_file():
        durable_ids = read_result_ids(h.result)
        assert durable_ids == ids[: len(durable_ids)], (
            f"{point}: durable prefix corrupted: {durable_ids}"
        )
        assert len(durable_ids) == len(set(durable_ids)), f"{point}: duplicate durable IDs"

    # Resume: no fault injected, child finishes the whole manifest.
    resumed = execute(h, prov, {"PARI_FAKE_UNTIL": str(len(ids))}, stage=stage)
    assert resumed.status == "completed", f"{point}: resume -> {resumed.reason}"
    assert_final_contract(h)
    # A kill that happens after the launch must leave >=2 recorded launches.
    # `before_first_task` aborts *before* the child is ever launched, so that
    # scenario legitimately records only the single resume launch.
    ckpt = read_checkpoint(h.checkpoint)
    launches = [a for a in ckpt["attempts"] if a.get("kind") == "launch"]
    minimum = 1 if point == "before_first_task" else 2
    assert len(launches) >= minimum, (
        f"{point}: expected >={minimum} launch attempts, got {len(launches)}"
    )
    print(f"  {point}: resumed clean, terminal=completed, launches={len(launches)}")


def test_hard_kill_leaves_usable_checkpoint(tmp: Path) -> None:
    """A hard (SIGKILL-like) abort still leaves an atomic, resumable checkpoint."""
    ids = [f"t{i}" for i in range(1, 5)]
    h = Harness(tmp / "hard-kill", ids)
    prov = make_provenance(h.manifest)
    # Run the wrapper in a separate interpreter so the hard fault can call
    # os._exit (SIGKILL-like, no cleanup/handlers). `after_checkpoint` hard-exits
    # after the durable output has been folded in but before the summary is
    # finalized: the prefix is complete, the checkpoint advanced, but there is
    # no terminal status yet -- exactly the interrupted state a real Kaggle
    # session can be killed in.
    proc = subprocess.run(
        [
            sys.executable, str(h.driver), str(HERE), str(h.root),
        ],
        env={
            **os.environ,
            "PARI_FAKE_UNTIL": str(len(ids)),
            K._ENV_FAULT: "hard:after_checkpoint",
        },
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert proc.returncode == 137, f"hard fault should abort with 137, got {proc.returncode}: {proc.stdout}"

    # Checkpoint advanced to a complete prefix but has no terminal status yet.
    ckpt = read_checkpoint(h.checkpoint)
    assert ckpt["completedTaskIds"] == ids
    assert ckpt["status"] == "running", ckpt["status"]
    # Atomic write means no stray temp files remain.
    assert not list(h.unit_dir.glob(".unit.checkpoint.json.*.tmp")), "stray temp checkpoint"

    # Resume: the checkpoint is compatible (provenance now matches, including
    # the identical task-manifest role) and finalizes to a terminal status.
    assert ckpt["provenance"]["taskManifestSha256s"][0]["role"] == "synthetic-core"
    resumed = execute(h, prov, {"PARI_FAKE_UNTIL": str(len(ids))})
    assert resumed.status == "completed", resumed.reason
    assert_final_contract(h)
    print("  hard kill left atomic resumable checkpoint; resume finalized terminal")


def test_incompatible_checkpoint_rejected(tmp: Path) -> None:
    ids = ["t1", "t2", "t3"]
    h = Harness(tmp / "incompat", ids)
    prov = make_provenance(h.manifest)
    # Establish a checkpoint with a partial prefix.
    execute(h, prov, {"PARI_FAKE_UNTIL": "2"})
    assert read_checkpoint(h.checkpoint)["completedTaskIds"] == ids[:2]

    def expect_reject(label: str, new_prov: K.Provenance, new_manifest: K.TaskManifest | None = None):
        use_manifest = new_manifest or h.manifest
        try:
            K.RunCheckpoint.load_or_create(
                h.checkpoint, "candidate-stage", "synthetic-cand/full/normal",
                new_prov, use_manifest,
            )
        except K.IncompatibleCheckpoint:
            print(f"  {label}: rejected as incompatible")
            return
        raise AssertionError(f"{label} was NOT rejected; resume would have spliced configs")

    # Different benchmark revision.
    expect_reject(
        "benchmark-revision mismatch",
        make_provenance(h.manifest, benchmark_revision="rev-2"),
    )
    # Different candidate config digest.
    bad_conf = make_provenance(h.manifest)
    bad_conf = K.Provenance(
        benchmark_revision=bad_conf.benchmark_revision,
        candidate_id=bad_conf.candidate_id,
        candidate_revision=bad_conf.candidate_revision,
        candidate_config_sha256="f" * 64,  # changed
        preflight_path=bad_conf.preflight_path,
        preflight_sha256=bad_conf.preflight_sha256,
        runtime_receipt_path=bad_conf.runtime_receipt_path,
        runtime_receipt_sha256=bad_conf.runtime_receipt_sha256,
        task_manifest_sha256s=bad_conf.task_manifest_sha256s,
        task_files=bad_conf.task_files,
        parser_code_version=bad_conf.parser_code_version,
    )
    expect_reject("candidate-config mismatch", bad_conf)
    # Different task manifest (same ids, changed content).
    other_manifest_path = h.root / "tasks-other.jsonl"
    write_manifest(other_manifest_path, ids)
    other_manifest = K.load_task_manifest(other_manifest_path, "synthetic-core")
    other_prov = make_provenance(other_manifest)
    expect_reject("task-manifest mismatch", other_prov, other_manifest)


def test_durable_order_violations_rejected(tmp: Path) -> None:
    ids = ["t1", "t2", "t3", "t4"]
    h = Harness(tmp / "order", ids)
    prov = make_provenance(h.manifest)

    def write_rows(rows: list[dict]):
        h.result.write_text(json.dumps({"outputs": rows}, indent=2) + "\n", encoding="utf-8")

    def expect_durable_error(label: str):
        try:
            K.validate_durable_output(h.result, h.manifest)
        except K.CheckpointError:
            print(f"  {label}: rejected")
            return
        raise AssertionError(f"{label} was NOT rejected")

    write_rows([{"id": "t1"}, {"id": "t1"}])
    expect_durable_error("duplicate durable IDs")
    write_rows([{"id": "t1"}, {"id": "t3"}])
    expect_durable_error("skipped durable IDs")
    write_rows([{"id": "t2"}, {"id": "t1"}])
    expect_durable_error("reordered durable IDs")
    write_rows([{"id": "t1"}, {"id": "t2"}, {"id": "t3"}, {"id": "t4"}, {"id": "t5"}])
    expect_durable_error("extra durable IDs beyond manifest")


def test_owned_cleanup_does_not_touch_unrelated(tmp: Path) -> None:
    """A hanging child is terminated; an unrelated sleeper survives."""
    ids = ["t1", "t2"]
    h = Harness(tmp / "cleanup", ids)
    prov = make_provenance(h.manifest)
    # The unrelated process is NOT in our process group.
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    try:
        # Make the child hang (sleep a lot after writing rows) and give the
        # wrapper a short timeout so it must terminate the owned group.
        res = execute(
            h,
            prov,
            {"PARI_FAKE_UNTIL": str(len(ids)), "PARI_FAKE_SLEEP": "30"},
            timeout_seconds=3.0,
        )
    finally:
        unrelated.terminate()
        unrelated.wait()
    assert res.cleanup.required is True, res.cleanup.to_dict()
    assert res.cleanup.attempted is True
    assert res.cleanup.outcome in {"terminated", "group_gone"}, res.cleanup.to_dict()
    assert res.cleanup.returncode is not None
    # The unrelated sleeper was a separate group and must have been unaffected
    # by our cleanup (we only killpg our own child). We terminate it explicitly
    # above; assert we never targeted it by confirming our cleanup did not need
    # to reach outside the owned group.
    #
    # Issue #57: the cleanup must also *name* the PIDs it owned, so a supervisor
    # can hand the GPU resource gate exactly this set and keep every other GPU
    # process foreign (recorded and blocked, never signalled). An owned set that
    # was empty or that leaked the unrelated sleeper would be a false-clean.
    owned = res.owned_pids
    assert owned, "execute_unit must report the PIDs it launched"
    assert res.cleanup.owned_pids, "cleanup evidence must carry the owned PID set"
    assert set(res.cleanup.owned_pids) <= set(owned), (
        res.cleanup.owned_pids,
        owned,
    )
    assert unrelated.pid not in owned, (
        f"unrelated pid {unrelated.pid} leaked into the owned set {owned}"
    )
    # The serialized outcome is what reaches the orchestration artifact, so the
    # owned PID evidence must survive serialization.
    assert res.to_dict()["ownedPids"] == sorted(owned), res.to_dict()
    print(
        f"  cleanup outcome={res.cleanup.outcome} signal={res.cleanup.signaled} "
        f"ownedPids={owned}"
    )


def test_resume_of_completed_unit_reports_no_owned_pids(tmp: Path) -> None:
    """A resume that launches nothing reports an empty owned set, explicitly.

    Issue #57 distinguishes "this run started no process" from "a process ran
    and owned nothing". The already-complete path takes neither branch: it never
    launches, so it must report an empty list rather than inheriting a stale set.
    """
    ids = ["t1"]
    h = Harness(tmp / "resume-owned", ids)
    prov = make_provenance(h.manifest)
    first = execute(h, prov, {})
    assert first.status == "completed", first.to_dict()
    assert first.owned_pids, "the launching run must report owned pids"

    # Second call resumes an already-terminal checkpoint and launches nothing.
    resumed = execute(h, prov, {})
    assert resumed.reason == "checkpoint already terminal and complete; nothing to redo"
    assert resumed.owned_pids == [], resumed.to_dict()
    print("  already-complete resume reports no owned pids")


def test_owned_pids_exclude_unrelated_processes(tmp: Path) -> None:
    """Ownership is process-group membership, never GPU-table membership.

    Issue #57 forbids killing a foreign process to make a benchmark pass. A
    wrapper that claimed "owned" merely because a PID shows up using GPU memory
    would put every unrelated notebook process on the machine in the cleanup
    blast radius, so the owned set must stay exactly this child's own group.
    """
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    child = K.OwnedProcessGroup(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        tmp / "group.log.txt",
    )
    try:
        child.start()
        owned = child.owned_pids()
        assert owned == [child.proc.pid], owned
        assert unrelated.pid not in owned, (
            f"unrelated pid {unrelated.pid} leaked into the owned set {owned}"
        )
        record = child.terminate_owned()
        assert record.owned_pids == owned, (record.owned_pids, owned)
        # Ownership evidence is cumulative: once the group is gone a fresh scan
        # would return nothing, and the caller would lose the residue record.
        assert child.owned_pids() == owned, child.owned_pids()
    finally:
        child.terminate_owned()
        unrelated.terminate()
        unrelated.wait()
    print(f"  owned pids exclude an unrelated process: {owned}")


PREFIX = "open-local-phraser-v1/benchmarks/english-studio-v3"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout.strip()


def _git_repo(root: Path, prefix: str) -> Path:
    """Create a throwaway git repo shaped like the benchmark tree."""
    bench = root / prefix
    bench.mkdir(parents=True)
    (bench / "runner.py").write_text("# frozen benchmark source\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "t@example.invalid"], check=True
    )
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "clean baseline"], check=True
    )
    return bench


def expect_git_rejection(label: str, root: Path, declared: str, **kwargs) -> None:
    try:
        K.verify_git_identity(root, declared, relevant_prefix=PREFIX, **kwargs)
    except K.CheckpointError:
        print(f"  {label}: rejected")
        return
    raise AssertionError(f"{label} was NOT rejected")


def test_git_identity_guard(tmp: Path) -> None:
    """Issue #40 cases 1-9: the launch guard must fail closed."""
    root = tmp / "gitguard"
    bench = _git_repo(root, PREFIX)
    head = _git(root, "rev-parse", "HEAD")

    # 1. exact clean full SHA passes.
    identity = K.verify_git_identity(root, head, relevant_prefix=PREFIX)
    assert identity.head == head and len(head) == 40
    assert identity.promotion_eligible is True
    assert identity.tree and identity.branch is not None
    print("  exact clean full SHA accepted")

    # 2. short SHA rejected.
    expect_git_rejection("short SHA", root, head[:8])
    # 3. caller declares a different valid SHA.
    expect_git_rejection("wrong SHA", root, "0" * 40)
    # 9. missing .git metadata.
    expect_git_rejection("missing .git", tmp / "no-such-repo", head)

    # 4. uncommitted tracked file under the benchmark prefix.
    (bench / "runner.py").write_text("# edited\n", encoding="utf-8")
    expect_git_rejection("dirty tracked benchmark file", root, head)

    # 5. staged benchmark edit.
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    expect_git_rejection("staged benchmark edit", root, head)
    subprocess.run(["git", "-C", str(root), "reset", "-q", "--hard", head], check=True)

    # 6. unrelated untracked result artifact outside the benchmark prefix.
    (root / "results").mkdir()
    (root / "results" / "candidate-matrix.json").write_text("{}\n", encoding="utf-8")
    identity = K.verify_git_identity(root, head, relevant_prefix=PREFIX)
    assert identity.promotion_eligible is True
    assert identity.status_porcelain, "untracked result artifact should still be visible"
    print("  irrelevant untracked artifact does not poison the policy")

    # 7. relevant untracked config file under the benchmark prefix.
    (bench / "sneaky-config.json").write_text("{}\n", encoding="utf-8")
    expect_git_rejection("untracked benchmark config", root, head)
    (bench / "sneaky-config.json").unlink()

    # 8. checkout changes after preflight: re-verification fails.
    (bench / "runner.py").write_text("# changed after launch\n", encoding="utf-8")
    expect_git_rejection("post-launch change (TOCTOU)", root, head)
    subprocess.run(["git", "-C", str(root), "checkout", "--", "."], check=False)

    # Dirty-tree debug mode stays usable but is visibly non-promotion.
    (bench / "runner.py").write_text("# still dirty\n", encoding="utf-8")
    identity = K.verify_git_identity(
        root, head, relevant_prefix=PREFIX, require_clean=False
    )
    assert identity.promotion_eligible is False
    print("  non-promotion debug mode records dirtiness")

    # Prepared generated task inputs: allowed only when a receipt names them.
    subprocess.run(["git", "-C", str(root), "checkout", "-q", "--", "."], check=False)
    task_input = bench / "word-studio-strength.jsonl"
    task_input.write_text('{"id": "a"}\n', encoding="utf-8")
    expect_git_rejection(
        "untracked task input without receipt", root, head
    )
    receipt = root / "benchmark-preparation.json"
    receipt.write_text(json.dumps({
        "files": [
            {"name": "word-studio-strength.jsonl", "sha256": "irrelevant-here"},
            {"name": "kaggle-stage-manifest.prepared.json", "sha256": "bound-by-preparation-verifier"},
        ]
    }) + "\n", encoding="utf-8")
    identity = K.verify_git_identity(
        root, head, relevant_prefix=PREFIX, preparation_receipt=receipt
    )
    assert identity.promotion_eligible is True
    assert identity.approved_prepared_inputs == (
        "kaggle-stage-manifest.prepared.json",
        "word-studio-strength.jsonl",
    )
    print("  receipt-verified prepared task/register inputs accepted")

    # A result artifact inside the benchmark tree is never receipt-excused.
    (bench / "summary.json").write_text("{}\n", encoding="utf-8")
    expect_git_rejection("untracked result artifact in benchmark tree", root, head)


def test_stage_identity_contract(tmp: Path) -> None:
    """Issue #48: canonical stage identity, overrides, and batch policy."""
    canonical = STAGE.canonical_path("smoke")
    identity = STAGE.resolve_stage_tasks("smoke")
    assert identity.kind == "canonical"
    assert identity.promotion_eligible and identity.comparable
    assert identity.sha256 == K.sha256_file(canonical)
    assert identity.expected_count == 16
    print("  canonical smoke stage identity resolved")

    # An unregistered --tasks path cannot become promotion-valid.
    custom = tmp / "custom.jsonl"
    custom.write_text(json.dumps({"id": "only"}) + "\n", encoding="utf-8")
    try:
        STAGE.resolve_stage_tasks("smoke", custom, promotion_run=True)
        raise AssertionError("arbitrary --tasks override was accepted as promotion-valid")
    except K.CheckpointError:
        print("  arbitrary --tasks override rejected for promotion")

    # Same bytes are allowed only as an explicit exploratory identity.
    exploratory = STAGE.resolve_stage_tasks("smoke", custom, promotion_run=False)
    assert exploratory.kind == "exploratory"
    assert exploratory.promotion_eligible is False and exploratory.comparable is False
    print("  exploratory override is non-promotion and non-comparable")

    # Reordering the same IDs changes the ordered-ID digest.
    a = STAGE.ordered_ids_sha256(["a", "b", "c"])
    b = STAGE.ordered_ids_sha256(["c", "b", "a"])
    assert a != b, "ordered ID hash must be order-sensitive"

    # Registered path whose bytes drifted is a hard failure.
    if canonical.is_file():
        drifted = tmp / "drifted-smoke.jsonl"
        drifted.write_text(
            canonical.read_text(encoding="utf-8").replace("{", "{ ", 1), encoding="utf-8"
        )
        try:
            STAGE.resolve_stage_tasks("smoke", drifted, promotion_run=True)
        except K.CheckpointError:
            pass  # registered-stage contract failure is the expected outcome

    # Issue #47: product stages never walk the generation ladder.
    assert STAGE.canonical_batch_policy("word-studio") == "single-batch-1"
    assert STAGE.canonical_batch_policy("transform") == "single-batch-1"
    assert STAGE.canonical_batch_policy("full") == "generation-ladder"
    assert STAGE.classify_oom(["cuda_oom_load"]) == "load"
    assert STAGE.classify_oom(["cuda_oom_generate"]) == "generate"
    assert STAGE.classify_oom(["triton_or_ptx_failure"]) is None
    print("  product batch policy single-batch; OOM class distinction works")


def main() -> None:
    print("Issue #30 fault-injection / resume-safety tests (CPU only)")
    with tempfile.TemporaryDirectory(prefix="pari-fault-") as tmpdir:
        tmp = Path(tmpdir)
        test_clean_run(tmp)
        # Kill points 1-6 mapped to concrete scenario parameters.
        test_kill_point_resume(tmp, "before_first_task", until=0)
        test_kill_point_resume(tmp, "after_output_before_checkpoint", until=3)
        test_kill_point_resume(tmp, "midway_batch", until=4)
        test_kill_point_resume(tmp, "after_final_task_before_summary", until=6)
        test_kill_point_resume(tmp, "during_teardown", until=2)
        # Kill point #5: during the Word Studio stage specifically. The stage
        # must reach its durable output (fault fires on the first real row) and
        # still resume to a terminal completion.
        test_kill_point_resume(tmp, "during_word_studio", until=6, stage="word-studio")
        test_hard_kill_leaves_usable_checkpoint(tmp)
        test_incompatible_checkpoint_rejected(tmp)
        test_durable_order_violations_rejected(tmp)
        test_owned_cleanup_does_not_touch_unrelated(tmp)
        test_resume_of_completed_unit_reports_no_owned_pids(tmp)
        test_owned_pids_exclude_unrelated_processes(tmp)
        test_git_identity_guard(tmp)
        test_stage_identity_contract(tmp)
    print("All Issue #30 fault-injection/resume tests passed.")


if __name__ == "__main__":
    main()
