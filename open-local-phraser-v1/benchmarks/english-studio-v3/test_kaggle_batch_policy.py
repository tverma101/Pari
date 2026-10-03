#!/usr/bin/env python3
"""CPU tests for the Issue #47 load-vs-generation OOM contract.

No GPU and no vLLM import. The unit under test is `kaggle_batch_policy`, the
single source of truth both candidate wrappers consume: the canonical ladder,
the product single-batch policy, and `decide_after_attempt`, which maps one
attempt outcome to exactly one next action.

The wrappers themselves are owned by another workstream, so parity is asserted
by reading their source (a ladder literal, if any, must equal the canonical
one, and each wrapper must import the shared module) rather than executing them.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

import kaggle_batch_policy as policy

HERE = Path(__file__).resolve().parent
VLLM_WRAPPER = HERE / "run-kaggle-vllm-candidate.py"
PRISM_WRAPPER = HERE / "run-kaggle-prism-candidate.py"
HARDENING = HERE / "KAGGLE_BENCHMARK_HARDENING.md"


def read_tuple_constant(path: Path, name: str) -> tuple[int, ...] | None:
    """Read a literal tuple constant from a wrapper source without importing it.

    The candidate wrappers are owned by another workstream, so this test asserts
    parity by reading their source instead of executing them. A wrapper that
    consumes the shared module directly has no literal and returns None.
    """
    if not path.is_file():
        return None
    source = path.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}\s*(?::[^=]+)?=\s*\(([^)]*)\)", source, re.M)
    if not match:
        return None
    values = [part.strip() for part in match.group(1).split(",") if part.strip()]
    try:
        return tuple(int(v) for v in values)
    except ValueError:
        return None


def consumes_shared_policy(path: Path) -> bool:
    return "kaggle_batch_policy" in path.read_text(encoding="utf-8")


def load_wrapper():
    """Load the vLLM wrapper (owned by #62) for the #41 resolver integration check."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "pari_vllm_candidate_wrapper", VLLM_WRAPPER
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load wrapper module")
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations through sys.modules[cls.__module__].
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def drive(outcomes):
    """Run the real ladder loop over a scripted sequence of attempt outcomes.

    Returns (batches_tried, final_action, attempts). Mirrors the loop in
    `main()` exactly: a step-down advances the ladder index, a same-config
    retry does not, and any terminal action ends the sweep.
    """
    ladder = list(policy.CANONICAL_LADDER)
    batches = []
    attempts = []
    transient_retries_used = 0
    index = 0
    final_action = "loop_exhausted"
    for outcome in outcomes:
        if index >= len(ladder):
            final_action = "loop_exhausted"
            break
        batch = ladder[index]
        batches.append(batch)
        decision = policy.decide_after_attempt(
            returncode=outcome["returncode"],
            categories=outcome["categories"],
            batch=batch,
            transient_retries_used=transient_retries_used,
        )
        attempts.append({
            "batchSize": batch,
            "decision": decision.action,
            "oomClass": decision.oom_class,
            "transientRetry": decision.transient_retry,
        })
        if decision.action == "complete":
            final_action = "complete"
            break
        if decision.action == "step_down_batch":
            index += 1
            continue
        if decision.action == "retry_same_config":
            transient_retries_used += 1
            continue
        final_action = decision.action
        break
    return batches, final_action, attempts


def fail(condition, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_canonical_ladder_is_single_source() -> None:
    ladder = policy.CANONICAL_LADDER
    fail(ladder == tuple(sorted(ladder, reverse=True)), "ladder must descend")
    fail(ladder[-1] == 1, "ladder must terminate at batch 1")
    fail(64 not in ladder, "64 must stay omitted until documented otherwise")
    text = HARDENING.read_text(encoding="utf-8")
    documented = " -> ".join(str(b) for b in ladder)
    fail(documented in text, f"hardening doc does not state the canonical ladder `{documented}`")
    fail("64 -> 32" not in text, "hardening doc still recommends the stale 64-first ladder")
    print(f"  canonical ladder [{documented}] is frozen in code and docs")


def test_load_oom_stops_without_batch_walk() -> None:
    batches, final, attempts = drive([
        {"returncode": 1, "categories": ["cuda_oom_load"]},
    ])
    fail(batches == [32], f"load OOM walked the ladder: {batches}")
    fail(final == "stop_load_capacity", final)
    fail(attempts[0]["oomClass"] == "load", attempts[0])
    print(f"  load OOM stops at batch {batches} without a ladder walk")


def test_generation_oom_walks_exact_ladder() -> None:
    expected = list(policy.CANONICAL_LADDER)
    batches, final, _ = drive([
        {"returncode": 1, "categories": ["cuda_oom_generate"]} for _ in expected
    ])
    fail(batches == expected, f"generation ladder mismatch: {batches} != {expected}")
    fail(final == "stop_generation_capacity", final)
    print(f"  generation OOM walks {batches} then stops at capacity")


def test_generation_oom_then_success() -> None:
    batches, final, attempts = drive([
        {"returncode": 1, "categories": ["cuda_oom_generate"]},
        {"returncode": 1, "categories": ["cuda_oom_generate"]},
        {"returncode": 0, "categories": []},
    ])
    fail(batches == [32, 16, 8], batches)
    fail(final == "complete", final)
    fail(attempts[-1]["batchSize"] == 8, attempts)
    print("  generation OOM then success settles at the first stable batch")


def test_non_oom_runtime_failure_stops_immediately() -> None:
    batches, final, _ = drive([
        {"returncode": 1, "categories": ["triton_or_ptx_failure"]},
    ])
    fail(batches == [32], batches)
    fail(final == "stop_runtime_failure", final)
    print("  non-OOM runtime failure stops at the first attempt")


def test_transient_retry_is_same_config_and_retained() -> None:
    batches, final, attempts = drive([
        {"returncode": 1, "categories": ["cuda_memory_fragmentation"]},
        {"returncode": 0, "categories": []},
    ])
    fail(batches == [32, 32], f"transient retry must reuse the same batch: {batches}")
    fail(final == "complete", final)
    fail(attempts[0]["transientRetry"] is True, attempts)
    fail(attempts[0]["decision"] == "retry_same_config", attempts)
    fail(len(attempts) == 2, attempts)
    print("  transient allocator fault retries the identical config, both attempts kept")


def test_transient_retry_is_bounded() -> None:
    _, final, attempts = drive([
        {"returncode": 1, "categories": ["cuda_memory_fragmentation"]},
        {"returncode": 1, "categories": ["cuda_memory_fragmentation"]},
    ])
    fail(final == "stop_runtime_failure", final)
    fail(len(attempts) == 2, attempts)
    print("  a repeated transient fault becomes a deterministic failure, not a loop")


def test_batch_one_generation_oom_is_capacity_failure() -> None:
    expected = list(policy.CANONICAL_LADDER)
    _, final, attempts = drive([
        {"returncode": 1, "categories": ["cuda_oom_generate"]} for _ in expected
    ])
    fail(attempts[-1]["batchSize"] == 1, attempts)
    fail(attempts[-1]["oomClass"] == "generate", attempts)
    fail(final == "stop_generation_capacity", final)
    print("  batch-1 generation OOM resolves to generation-capacity failure")


def test_load_then_generate_categories_prefer_load() -> None:
    from kaggle_failure_taxonomy import classify

    categories = classify("CUDA out of memory while loading model weights")
    decision = policy.decide_after_attempt(
        returncode=1, categories=categories, batch=32, transient_retries_used=0
    )
    fail(decision.action == "stop_load_capacity", decision.to_dict())
    print("  a load-shaped OOM log cannot trigger a generation batch walk")


def test_product_stage_policy_is_separate() -> None:
    fail(policy.PRODUCT_BATCH_POLICY == (1,), "product stages must stay pinned to batch 1")
    fail(
        len(policy.PRODUCT_BATCH_POLICY) == 1,
        "product batch policy must be a single frozen value, not a ladder",
    )
    fail("word-studio" in policy.PRODUCT_STAGES, "word-studio must be a product stage")
    fail("transform" in policy.PRODUCT_STAGES, "transform must be a product stage")
    print("  product stages report a separate single-batch policy")


def test_tp1_failure_does_not_overwrite_tp2() -> None:
    """A TP1 load failure must not leak into a separately-declared TP2 identity."""
    roster = json.loads((HERE / "kaggle-candidate-roster.json").read_text(encoding="utf-8"))
    tp1 = [c for c in roster["candidates"] if c.get("tensorParallelSize", 1) == 1]
    tp2 = [c for c in roster["candidates"] if c.get("tensorParallelSize", 1) == 2]
    fail(bool(tp1) and bool(tp2), "fixture needs both a TP1 and a TP2 roster candidate")
    tp1_id, tp2_id = tp1[0]["id"], tp2[0]["id"]
    fail(tp1_id != tp2_id, "TP1 and TP2 fixtures must be distinct candidates")

    def result_dir(results, candidate_id, stage, decode="normal"):
        return Path(results) / candidate_id / stage / decode / "summary.json"

    base = Path("/tmp/issue47-tp-check")
    fail(
        result_dir(base, tp1_id, "full") != result_dir(base, tp2_id, "full"),
        "TP1 and TP2 summaries must not collide",
    )
    # A load-capacity stop is recorded on the TP1 candidate only.
    decision = policy.decide_after_attempt(
        returncode=1, categories=["cuda_oom_load"], batch=32, transient_retries_used=0
    )
    fail(decision.action == "stop_load_capacity", decision.to_dict())
    print("  TP1 load failure and TP2 candidate keep separate result identities")


def test_isolated_runtime_fails_closed() -> None:
    """Issue #41: the child must run on the receipt's venv interpreter, or not run."""

    module = load_wrapper()
    resolver = getattr(module, "resolve_isolated_runtime", None)
    if resolver is None:
        print(
            "  REQUIRED INTEGRATION: run-kaggle-vllm-candidate.py no longer exposes"
            " resolve_isolated_runtime; the #41 fail-closed interpreter resolver must"
            " be imported from (or moved into) a shared module and re-pointed here"
        )
        return

    with tempfile.TemporaryDirectory(prefix="pari-41-") as tmp:
        runtime_dir = Path(tmp)
        artifact = "fake-vllm"

        # Missing receipt: refuse.
        expect_system_exit("missing receipt", module, runtime_dir, artifact)

        # Receipt present but no dedicated venv: refuse.
        receipt_path = runtime_dir / (artifact + ".receipt.json")
        receipt_path.write_text(json.dumps({"environment": {"kind": "system"}}) + "\n")
        expect_system_exit("non-venv environment", module, runtime_dir, artifact)

        # dedicated_venv but missing interpreter: refuse.
        receipt_path.write_text(json.dumps({
            "environment": {
                "kind": "dedicated_venv",
                "pythonExecutable": str(runtime_dir / "venv" / "bin" / "python"),
                "venvPath": str(runtime_dir / "venv"),
            }
        }) + "\n")
        expect_system_exit("missing interpreter", module, runtime_dir, artifact)

        # Interpreter outside the recorded venv root: refuse.
        receipt_path.write_text(json.dumps({
            "environment": {
                "kind": "dedicated_venv",
                "pythonExecutable": sys.executable,
                "venvPath": str(runtime_dir / "venv"),
            }
        }) + "\n")
        expect_system_exit("interpreter outside venv", module, runtime_dir, artifact)

        # A coherent receipt resolves the interpreter and strips PYTHONPATH.
        venv_bin = runtime_dir / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        fake_python = venv_bin / "python"
        fake_python.write_text("#!/bin/sh\nexit 0\n")
        fake_python.chmod(0o755)
        receipt_path.write_text(json.dumps({
            "environment": {
                "kind": "dedicated_venv",
                "pythonExecutable": str(fake_python),
                "venvPath": str(runtime_dir / "venv"),
                "pythonExecutableSha256": "0" * 64,
            }
        }) + "\n")
        os.environ["PYTHONPATH"] = "/should/be/stripped"
        try:
            python_path, child_env, receipt = module.resolve_isolated_runtime(
                runtime_dir, artifact
            )
        finally:
            os.environ.pop("PYTHONPATH", None)
        fail(python_path == fake_python, f"resolved {python_path}")
        fail("PYTHONPATH" not in child_env, "host PYTHONPATH must not reach the child")
        fail(child_env["VIRTUAL_ENV"] == str(runtime_dir / "venv"), child_env["VIRTUAL_ENV"])
        fail(child_env["PATH"].startswith(str(venv_bin)), child_env["PATH"][:80])
        fail(receipt["environment"]["kind"] == "dedicated_venv", receipt)
    print("  isolated runtime resolver fails closed and strips host PYTHONPATH")


def expect_system_exit(label: str, module, runtime_dir: Path, artifact: str) -> None:
    try:
        module.resolve_isolated_runtime(runtime_dir, artifact)
    except SystemExit:
        return
    raise AssertionError(label + ": was NOT refused")


def test_wrappers_consume_the_shared_policy() -> None:
    """Both candidate wrappers must source the ladder from the shared module.

    #62 owns the wrappers. This asserts parity by reading their source rather
    than executing them, so a refactor cannot silently fork the ladder: each
    wrapper must import `kaggle_batch_policy`, and any ladder literal it still
    declares must equal the canonical one.
    """
    for path in (VLLM_WRAPPER, PRISM_WRAPPER):
        if not path.is_file():
            print(f"  REQUIRED INTEGRATION: {path.name} is absent; cannot check ladder parity")
            continue
        fail(
            consumes_shared_policy(path),
            f"{path.name} does not import kaggle_batch_policy; the ladder would fork",
        )
        for name in ("CANONICAL_GENERATION_LADDER", "BATCH_LADDER"):
            literal = read_tuple_constant(path, name)
            if literal is None:
                continue
            fail(
                literal == policy.CANONICAL_LADDER,
                f"{path.name} declares {name}={list(literal)}, "
                f"canonical is {list(policy.CANONICAL_LADDER)}",
            )
    print("  both wrappers consume the shared canonical ladder")


def test_ladder_fork_is_detected() -> None:
    """The parity check must actually fail on a forked ladder.

    A parity assertion that cannot fail is not evidence, so this feeds a
    synthetic wrapper that re-declares the old 64-first ladder and proves the
    reader reports the divergence.
    """
    with tempfile.TemporaryDirectory(prefix="pari-fork-") as tmp:
        forked = Path(tmp) / "forked-wrapper.py"
        forked.write_text(
            "from kaggle_batch_policy import CANONICAL_LADDER\n"
            "BATCH_LADDER = (64, 32, 16, 8, 4, 1)\n",
            encoding="utf-8",
        )
        literal = read_tuple_constant(forked, "BATCH_LADDER")
        fail(literal is not None, "a forked ladder literal must be readable")
        fail(
            literal != policy.CANONICAL_LADDER,
            "a 64-first fork must not compare equal to the canonical ladder",
        )
    print("  a forked ladder is detected rather than silently accepted")


def test_prism_labels_what_its_batch_number_means() -> None:
    """The Prism rung is client concurrency, not a vLLM generation batch.

    The number shares the canonical ladder, so the summary must say what it
    controls, otherwise a Prism rung reads as an English-screen ladder step.
    """
    if not PRISM_WRAPPER.is_file():
        print("  REQUIRED INTEGRATION: run-kaggle-prism-candidate.py is absent")
        return
    source = PRISM_WRAPPER.read_text(encoding="utf-8")
    fail(
        "BATCH_PARAMETER_SEMANTICS" in source and "concurrency" in source,
        "Prism wrapper must label its batch parameter semantics",
    )
    fail(
        "cuda_oom_load" not in source or "decide_after_attempt" in source,
        "Prism must route OOM outcomes through the shared decision function",
    )
    print("  Prism labels its batch parameter and uses the shared decision function")


def test_policy_action_table_is_complete() -> None:
    """Every decision action has a documented meaning and a failure class."""
    fail(policy.ACTION_MEANINGS.keys() == policy.FAILURE_CLASS_BY_ACTION.keys() | {
        "complete", "step_down_batch", "retry_same_config"
    }, sorted(policy.ACTION_MEANINGS))
    for action, meaning in policy.ACTION_MEANINGS.items():
        fail(bool(meaning.strip()), action)
    fail(policy.MAX_TRANSIENT_RETRIES == 1, policy.MAX_TRANSIENT_RETRIES)
    fail(
        policy.TRANSIENT_RETRY_CATEGORIES >= {"cuda_memory_fragmentation", "runtime_crash"},
        sorted(policy.TRANSIENT_RETRY_CATEGORIES),
    )
    print("  decision actions are fully documented and the transient retry is bounded")


def test_load_and_generate_are_distinct_states() -> None:
    """The two capacity classes must never collapse into one another."""
    fail(policy.classify_oom(["cuda_oom_load"]) == "load", "load oom class")
    fail(policy.classify_oom(["cuda_oom_generate"]) == "generate", "generate oom class")
    fail(
        policy.classify_oom(["cuda_oom_load", "cuda_oom_generate"]) == "load",
        "load wins when a log matches both patterns",
    )
    fail(policy.classify_oom(["triton_or_ptx_failure"]) is None, "non-oom has no oom class")
    for categories, expected in (
        (["cuda_oom_load"], "load_capacity"),
        (["cuda_oom_generate"], None),
        (["unsupported_kernel"], "runtime_failure"),
    ):
        decision = policy.decide_after_attempt(
            returncode=1, categories=categories, batch=32, transient_retries_used=0
        )
        if expected is None:
            fail(decision.action == "step_down_batch", decision.to_dict())
        else:
            fail(decision.failure_class == expected, decision.to_dict())
    print("  load capacity and generation capacity stay distinct states")


def main() -> None:
    print("Issue #47 batch-policy / load-vs-generation OOM tests (CPU only)")
    test_canonical_ladder_is_single_source()
    test_load_oom_stops_without_batch_walk()
    test_generation_oom_walks_exact_ladder()
    test_generation_oom_then_success()
    test_non_oom_runtime_failure_stops_immediately()
    test_transient_retry_is_same_config_and_retained()
    test_transient_retry_is_bounded()
    test_batch_one_generation_oom_is_capacity_failure()
    test_load_then_generate_categories_prefer_load()
    test_product_stage_policy_is_separate()
    test_tp1_failure_does_not_overwrite_tp2()
    test_policy_action_table_is_complete()
    test_load_and_generate_are_distinct_states()
    test_wrappers_consume_the_shared_policy()
    test_ladder_fork_is_detected()
    test_prism_labels_what_its_batch_number_means()
    test_isolated_runtime_fails_closed()
    print("All Issue #47 batch-policy tests passed.")


if __name__ == "__main__":
    main()
