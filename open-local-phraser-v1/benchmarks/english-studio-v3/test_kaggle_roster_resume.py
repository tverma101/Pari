#!/usr/bin/env python3
"""CPU integration test: the roster supervisor resumes safely.

`test_kaggle_fault_injection.py` proves the per-unit checkpoint engine. This
test drives `run-kaggle-roster.py` end to end against a synthetic roster,
dispatcher, matrix builder, and preparation verifier, then resumes after an
interrupted sweep. It asserts the roster-level Issue #30 contract:

* a resumed sweep does not duplicate already-terminal candidate-stage work;
* the orchestration artifact always ends in an explicit terminal status;
* incompatible roster provenance is refused rather than resumed;
* per-candidate-stage summaries carry the canonical provenance block.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import kaggle_run_checkpoint as K

HERE = Path(__file__).resolve().parent
ROSTER_SCRIPT = HERE / "run-kaggle-roster.py"


# --- synthetic collaborators ------------------------------------------------

# Stands in for the real candidate dispatcher. Each unit appends a marker so
# the test can prove a unit did not re-run on resume.
FAKE_DISPATCH = "\n".join([
    "import json",
    "import os",
    "import sys",
    "from pathlib import Path",
    "candidate = sys.argv[1]",
    'stage = sys.argv[sys.argv.index("--stage") + 1]',
    'results_dir = Path(sys.argv[sys.argv.index("--results-dir") + 1])',
    'manifest = Path(os.environ["SYNTH_MANIFEST"])',
    'unit_dir = results_dir / candidate / stage / "normal"',
    "unit_dir.mkdir(parents=True, exist_ok=True)",
    'ids = [json.loads(l)["id"] for l in manifest.read_text().splitlines() if l.strip()]',
    'marker = Path(os.environ["SYNTH_MARKERS"]) / f"{candidate}-{stage}-normal.run"',
    "marker.parent.mkdir(parents=True, exist_ok=True)",
    'runs = int(marker.read_text().strip()) + 1 if marker.exists() else 1',
    "marker.write_text(str(runs))",
    'rows = [{"id": i, "output": f"out-{i}"} for i in ids]',
    'result = unit_dir / "attempt-01-batch-1.result.json"',
    'result.write_text(json.dumps({"outputs": rows}, indent=2) + "\\n", encoding="utf-8")',
    '(unit_dir / "summary.json").write_text(json.dumps({',
    '    "schemaVersion": 3,',
    '    "status": "completed",',
    '    "result": str(result),',
    '    "candidate": candidate,',
    '}, indent=2) + "\\n", encoding="utf-8")',
    "sys.exit(0)",
    "",
])

FAKE_PREP = "import sys\nprint('preparation ok')\nsys.exit(0)\n"

FAKE_MATRIX = "import sys\nprint('matrix ok')\nsys.exit(0)\n"

#: Roster globals the driver repoints at synthetic fixtures, plus a stand-in
#: dispatcher module that reuses the real provenance builder contract.
STUB_DRIVER = "\n".join([
    "import importlib.util",
    "import json",
    "import sys",
    "from pathlib import Path",
    "sys.path.insert(0, {here!r})",
    "import kaggle_run_checkpoint as K",
    'spec = importlib.util.spec_from_file_location("roster", {script!r})',
    "roster = importlib.util.module_from_spec(spec)",
    'sys.modules["roster"] = roster',
    "spec.loader.exec_module(roster)",
    "manifest = Path({manifest!r})",
    "def summary_path_for(results_dir, candidate_id, stage, runtime, decode):",
    '    return Path(results_dir) / candidate_id / stage / decode / "summary.json"',
    "def result_path_from_summary(summary_path):",
    "    if not Path(summary_path).is_file():",
    "        return None",
    '    payload = json.loads(Path(summary_path).read_text(encoding="utf-8"))',
    '    return Path(payload["result"]) if payload.get("result") else None',
    "def stage_manifest(stage, tasks=None):",
    '    return K.load_task_manifest(manifest, "synthetic")',
    "def runtime_artifact_for(candidate, stage):",
    "    return None",
    "def build_provenance(*, candidate, benchmark_revision, stage, decode, preflight,",
    "                 runtime_artifact, manifest, git_identity=None,",
    "                 stage_identity=None):",
    "    return K.Provenance(",
    "        benchmark_revision=benchmark_revision,",
    '        candidate_id=candidate["id"],',
    '        candidate_revision=candidate["revision"],',
    "        candidate_config_sha256=K.sha256_json(",
    '            {"candidate": candidate, "stage": stage, "decode": decode}',
    "        ),",
    "        preflight_path=str(preflight),",
    "        preflight_sha256=K.sha256_file(preflight),",
    "        runtime_receipt_path=None,",
    "        runtime_receipt_sha256=None,",
    "        task_manifest_sha256s=(manifest.as_provenance_entry(),) if manifest else (),",
    "        task_files=(manifest.path,) if manifest else (),",
    '        parser_code_version="synthetic-parser-v1",',
    "        git_identity=git_identity.to_dict() if git_identity else None,",
    "    )",
    'roster.CAND = type("StubCandidate", (), {',
    '    "BENCHMARK_RELEVANT_PREFIX": "open-local-phraser-v1/benchmarks/english-studio-v3",',
    # run-kaggle-roster.py reads CAND.RUNTIME_DIR while building its argparse
    # defaults, so the stub must expose it even when the Q1 gate is skipped.
    '    "RUNTIME_DIR": Path("/kaggle/working/pari-runtimes"),',
    '    "PROTOCOL_SMOKE_TASKS": manifest,',
    '    "ENGLISH_TASKS": manifest,',
    '    "STRENGTH_TASKS": manifest,',
    '    "TRANSFORM_TASKS": manifest,',
    '    "stage_manifest": staticmethod(stage_manifest),',
    '    "summary_path_for": staticmethod(summary_path_for),',
    '    "result_path_from_summary": staticmethod(result_path_from_summary),',
    '    "runtime_artifact_for": staticmethod(runtime_artifact_for),',
    '    "build_provenance": staticmethod(build_provenance),',
    "})()",
    # The roster resolves its repo root for the git guard; point it at the
    # real checkout so verify_git_identity exercises the actual git plumbing.
    "roster.ROSTER = Path({roster!r})",
    "roster.DISPATCH = Path({dispatch!r})",
    "roster.MATRIX = Path({matrix!r})",
    "roster.VERIFY_PREP = Path({prep!r})",
    "sys.argv = [sys.argv[0], \"--benchmark-revision\", {head!r}, \"--phase\", \"smoke\",",
    "            \"--allow-dirty-tree\",",
    # Skip the real Q1 model-load gate and point the runtime dir at the fixture:
    # this test exercises orchestration/resume, not a Kaggle model launch.
    "            \"--skip-q1\", \"--runtime-dir\", {runtime_dir!r},",
    # No real GPU lease: this is a synthetic orchestration test, not a canonical
    # sweep, so it must not take (or require) the real /kaggle lease path.
    "            \"--no-gpu-lease\", \"--gpu-lease-path\", {lease!r},",
    "            \"--results-dir\", {results!r},",
    "            \"--preflight\", {preflight!r},",
    "            \"--preparation-receipt\", {prep_receipt!r}]",
    "roster.main()",
    "",
])


def build_fixture(root: Path) -> dict:
    """Create a synthetic roster, dispatcher, matrix, prep verifier, and manifest."""
    manifest = root / "tasks.jsonl"
    manifest.write_text(
        "\n".join(json.dumps({"id": i}) for i in ("t1", "t2", "t3", "t4")) + "\n",
        encoding="utf-8",
    )

    roster = {
        "version": 1,
        "candidates": [
            {"id": "cand-a", "revision": "a" * 40, "runtime": "vllm"},
            {"id": "cand-b", "revision": "b" * 40, "runtime": "vllm"},
        ],
    }
    roster_path = root / "roster.json"
    roster_path.write_text(json.dumps(roster, indent=2) + "\n", encoding="utf-8")

    dispatch = root / "dispatch.py"
    dispatch.write_text(FAKE_DISPATCH, encoding="utf-8")
    prep = root / "verify_prep.py"
    prep.write_text(FAKE_PREP, encoding="utf-8")
    matrix = root / "matrix.py"
    matrix.write_text(FAKE_MATRIX, encoding="utf-8")

    preflight = root / "preflight.json"
    preflight.write_text(json.dumps({"promotionEligibleEnvironment": True}) + "\n")
    prep_receipt = root / "preparation.json"
    prep_receipt.write_text(json.dumps({"status": "ok"}) + "\n")

    return {
        "manifest": manifest,
        "roster": roster_path,
        "dispatch": dispatch,
        "prep": prep,
        "matrix": matrix,
        "preflight": preflight,
        "prep_receipt": prep_receipt,
        "markers": root / "markers",
        "results": root / "results",
    }


def run_roster(root: Path, fx: dict, env_extra: dict) -> subprocess.CompletedProcess:
    """Run the roster supervisor as a subprocess against the synthetic fixture."""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(HERE),
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout.strip()
    driver = root / "roster_driver.py"
    driver.write_text(STUB_DRIVER.replace("{here!r}", repr(str(HERE)))
        .replace("{script!r}", repr(str(ROSTER_SCRIPT)))
        .replace("{manifest!r}", repr(str(fx["manifest"])))
        .replace("{roster!r}", repr(str(fx["roster"])))
        .replace("{dispatch!r}", repr(str(fx["dispatch"])))
        .replace("{matrix!r}", repr(str(fx["matrix"])))
        .replace("{prep!r}", repr(str(fx["prep"])))
        .replace("{results!r}", repr(str(fx["results"])))
        .replace("{preflight!r}", repr(str(fx["preflight"])))
        .replace("{prep_receipt!r}", repr(str(fx["prep_receipt"])))
        .replace("{head!r}", repr(head))
        .replace("{runtime_dir!r}", repr(str(fx["results"] / "runtimes")))
        .replace("{lease!r}", repr(str(fx["results"] / "gpu-lease.json"))),
        encoding="utf-8")
    env = {
        **os.environ,
        "SYNTH_MANIFEST": str(fx["manifest"]),
        "SYNTH_MARKERS": str(fx["markers"]),
        **env_extra,
    }
    return subprocess.run(
        [sys.executable, str(driver)],
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def read_markers(fx: dict) -> dict[str, int]:
    out = {}
    if fx["markers"].is_dir():
        for path in sorted(fx["markers"].glob("*.run")):
            out[path.stem] = int(path.read_text().strip())
    return out


def read_orchestration(results: Path) -> dict:
    return json.loads((results / "roster-orchestration.json").read_text(encoding="utf-8"))


def main() -> None:
    print("Issue #30 roster-supervisor resume integration test (CPU only)")
    with tempfile.TemporaryDirectory(prefix="pari-roster-") as tmpdir:
        root = Path(tmpdir)
        fx = build_fixture(root)

        # --- clean roster run emits terminal status and provenance ------------
        proc = run_roster(root, fx, {})
        assert proc.returncode == 0, proc.stdout
        orch = read_orchestration(fx["results"])
        assert orch["status"] == "completed", orch["status"]
        assert orch["terminal"] is True
        for key in K.Provenance.PROVENANCE_KEYS:
            assert key in orch["provenance"], f"roster provenance missing {key}"
        markers = read_markers(fx)
        assert markers == {"cand-a-smoke-normal": 1, "cand-b-smoke-normal": 1}, markers
        print(f"  clean roster terminal=completed units={len(orch['candidates'])}")

        # Per-candidate-stage summary carries the canonical provenance block.
        summary = json.loads(
            (fx["results"] / "cand-a" / "smoke" / "normal" / "summary.json").read_text()
        )
        for key in K.Provenance.PROVENANCE_KEYS:
            assert key in summary["provenance"], f"stage summary provenance missing {key}"
        assert summary["status"] == "completed"
        print("  stage summary carries canonical provenance")

        # --- resume a sweep whose first unit was killed mid-run --------------
        shutil.rmtree(fx["results"])
        shutil.rmtree(fx["markers"])
        killed = run_roster(root, fx, {K._ENV_FAULT: "hard:after_output_before_checkpoint"})
        assert killed.returncode != 0, killed.stdout
        # The roster artifact exists but is NOT terminal yet.
        partial = read_orchestration(fx["results"])
        assert partial["terminal"] is False, partial
        assert partial["status"] == "running", partial["status"]

        # Resume without a fault. The interrupted unit is re-entered, but its
        # already-durable rows must not be duplicated or reordered, and the
        # roster must reach an explicit terminal status.
        resumed = run_roster(root, fx, {})
        assert resumed.returncode == 0, resumed.stdout
        orch = read_orchestration(fx["results"])
        assert orch["status"] == "completed", orch["status"]
        assert orch["terminal"] is True
        markers = read_markers(fx)
        # At most one interrupted launch plus one resumed launch per unit.
        for unit, count in markers.items():
            assert count <= 2, f"{unit} ran {count} times; resume duplicated work"
        result = fx["results"] / "cand-a" / "smoke" / "normal" / "attempt-01-batch-1.result.json"
        rows = [r["id"] for r in json.loads(result.read_text())["outputs"]]
        assert rows == ["t1", "t2", "t3", "t4"], rows
        print(f"  resume after mid-sweep kill: terminal=completed markers={markers}")

        # --- incompatible roster provenance is refused -----------------------
        orch_path = fx["results"] / "roster-orchestration.json"
        stored = json.loads(orch_path.read_text())
        stored["provenance"]["benchmarkRevision"] = "DIFFERENT-REV"
        orch_path.write_text(json.dumps(stored, indent=2) + "\n")
        proc = run_roster(root, fx, {})
        assert proc.returncode != 0, "incompatible roster provenance was NOT refused"
        assert "refusing to resume" in proc.stdout, proc.stdout
        print("  incompatible roster provenance refused (no silent splice)")

    print("Roster supervisor resume integration test passed.")


if __name__ == "__main__":
    main()
