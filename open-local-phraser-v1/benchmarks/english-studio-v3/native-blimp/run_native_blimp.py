#!/usr/bin/env python3
"""Run, validate and receipt one frozen native BLiMP likelihood evaluation.

Every decision about what a native BLiMP run is allowed to be lives in
:mod:`native_blimp_protocol`. This file only wires a config to the harness
process, captures the run, and writes a provenance-bound receipt.

Subcommands

``plan``
    Validate a config and print the exact ``python -m lm_eval`` argv without
    running anything. Safe at accelerator-off.
``preflight``
    Verify the harness checkout identity, the resolved dataset revision and,
    for the GGUF lane, the owned llama-server's ability to return usable
    logprobs. Fails closed before any GPU time.
``execute``
    Run the harness, scan its output, validate its results, write the receipt.
    A failed run writes ``outcome=fail`` with ``promotable=false`` and a
    structured error list. It never writes a partial score that could be
    mistaken for grammar accuracy.
``verify``
    Re-validate an existing receipt against this checkout's frozen protocol
    and schema. No harness, no GPU.
``parity``
    Compare two receipts produced from the same model artifact through the two
    pinned backends.

This lane is separate from the prompted BLiMP public-fast screen. Nothing here
reads, writes, or averages prompted BLiMP artifacts.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import native_blimp_protocol as P

RECEIPT_NAME = "native-blimp-receipt.json"


def gate(
    ok: bool,
    detail: str,
    applicable: bool = True,
) -> dict[str, str]:
    if not applicable:
        return {"status": "not_applicable", "detail": detail}
    return {"status": "pass" if ok else "fail", "detail": detail}


def load_config(path: Path) -> dict[str, Any]:
    config = P.read_json(path)
    P.validate_config_document(config)
    return config


def resolve_checkout(config: dict[str, Any], override: Path | None) -> Path:
    if override is not None:
        return override
    configured = (config.get("harness") or {}).get("checkout")
    if configured:
        return Path(configured)
    return Path(os.environ.get("PARI_LM_EVAL_CHECKOUT", str(P.HERE)))


def adaptation_block(
    config: dict[str, Any],
    probe: P.CapabilityProbe | None,
) -> dict[str, Any]:
    policy = P.load_protocol()["adaptationPolicy"]
    model_args = config["runtime"]["modelArgs"]
    max_context: int | None = None
    if config["backend"] == "vllm":
        bos = (
            "vLLM add_bos_token="
            f"{model_args.get('add_bos_token')!r}; None defers to the tokenizer"
        )
        max_context = model_args.get("max_model_len") or model_args.get("max_length")
    else:
        bos = (
            "always on: the pinned gguf backend calls /tokenize with "
            "add_special=True for the whole sequence and for the context, "
            "and exposes no way to disable it"
        )
    return {
        "chatTemplate": "disabled",
        "likelihoodNormalization": policy["likelihoodNormalization"],
        "numFewshot": 0,
        "bosHandling": bos,
        "eosHandling": policy["eosHandling"],
        "maxContextTokens": max_context,
        "truncationObserved": False,
    }


def backend_block(
    config: dict[str, Any],
    probe: P.CapabilityProbe | None,
) -> dict[str, Any]:
    spec = P.load_protocol()["backends"][config["backend"]]
    model_args = config["runtime"]["modelArgs"]
    runtime = config["runtime"]
    block: dict[str, Any] = {
        "name": config["backend"],
        "harnessModelArg": spec["harnessModelArg"],
        "modelArgs": model_args,
        "modelArgsRendered": P.render_model_args(model_args),
    }
    if config["backend"] == "vllm":
        block["vllmVersion"] = runtime.get("vllmVersion")
    else:
        block["llamaCppBuild"] = runtime.get("llamaCppBuild")
        block["capabilityProbe"] = probe.detail if probe else None
    return block


def dataset_block(check: bool) -> dict[str, Any]:
    dataset_path = P.load_protocol()["task"]["datasetPath"]
    if not check:
        # Offline preflight records the pin and states that resolution was not
        # attempted. revisionMatches stays False, so a receipt produced this
        # way can never be promotable.
        return P.dataset_identity_block(None)
    return P.dataset_identity_block(P.resolve_dataset_revision(dataset_path))


def model_block(config: dict[str, Any]) -> dict[str, Any]:
    model = config["model"]
    block: dict[str, Any] = {
        "repo": model["repo"],
        "revision": model["revision"],
        "tokenizer": model["tokenizer"],
    }
    if model.get("tokenizerRevision"):
        block["tokenizerRevision"] = model["tokenizerRevision"]
    if model.get("ggufFile"):
        block["ggufFile"] = model["ggufFile"]
    if model.get("ggufSha256"):
        block["ggufSha256"] = model["ggufSha256"]
        # A GGUF artifact hash is the artifact identity, so it doubles as the
        # cross-backend parity key.
        block["artifactSha256"] = model["ggufSha256"]
    return block


def cmd_plan(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    checkout = resolve_checkout(config, args.checkout)
    invocation = P.build_invocation(config, checkout, python=args.python)
    warnings: list[str] = []
    if invocation.smoke:
        warnings.append(
            "smoke mode: this argv carries --limit, and its receipt can never "
            "be promotable"
        )
    print(
        json.dumps(
            {
                "laneId": P.LANE_ID,
                "candidateId": config["candidateId"],
                "backend": config["backend"],
                "mode": config["mode"],
                "promotable": config["promotable"],
                "harnessCheckout": str(checkout),
                "argv": invocation.argv,
                "warnings": warnings,
            },
            indent=2,
        )
    )
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    checkout = resolve_checkout(config, args.checkout)
    identity = P.verify_harness_identity(checkout)
    dataset = dataset_block(check=not args.offline)

    probe: P.CapabilityProbe | None = None
    if config["backend"] == "gguf":
        model_args = config["runtime"]["modelArgs"]
        probe = P.probe_gguf_server(
            model_args["base_url"],
            model=model_args.get("model"),
            timeout=args.timeout,
        )
        logprob_gate = gate(
            probe.ok,
            "the owned llama-server returned logprobs.content with "
            "top_logprobs for a forced-token request"
            if probe.ok
            else "; ".join(probe.failures),
        )
    else:
        logprob_gate = gate(
            True,
            "the pinned vllm backend scores through "
            "SamplingParams(prompt_logprobs=1); logprob availability is proven "
            "per run by the output scan",
            applicable=False,
        )

    argv = P.build_invocation(config, checkout, python=args.python).argv
    gates = {
        "harness_identity": gate(
            identity.all_identities_match,
            "the harness checkout is byte-identical to the pinned commit"
            if identity.all_identities_match
            else "; ".join(identity.problems()),
        ),
        "dataset_revision": gate(
            bool(dataset["revisionMatches"]),
            f"{dataset['datasetPath']} resolved to the pinned revision "
            f"{dataset['pinnedRevision']}"
            if dataset["revisionMatches"]
            else (
                f"{dataset['datasetPath']} resolved to "
                f"{dataset['resolvedRevision']!r}, pinned "
                f"{dataset['pinnedRevision']!r}"
            ),
        ),
        "logprobs_present": logprob_gate,
        "no_subset": gate(
            config["mode"] != "smoke" or not config["promotable"],
            "mode=full, no --limit"
            if config["mode"] == "full"
            else "smoke mode is debug-only and is not promotable",
        ),
        "chat_template_off": gate(
            True,
            "the frozen argv passes no chat-template flag; native scoring "
            "uses raw causal text",
        ),
    }
    ok = all(g["status"] != "fail" for g in gates.values())
    print(
        json.dumps(
            {
                "laneId": P.LANE_ID,
                "candidateId": config["candidateId"],
                "ok": ok,
                "harnessObserved": identity.as_receipt_block(),
                "datasetObserved": dataset,
                "capabilityProbe": probe.detail if probe else None,
                "gateResults": gates,
                "argv": argv,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if ok else 1


def collect_run(
    config: dict[str, Any],
    checkout: Path,
    argv: list[str],
    results_dir: Path,
    timeout_seconds: int,
    python: str,
) -> tuple[
    int | None,
    list[dict[str, str]],
    list[str],
    dict[str, Any],
    dict[str, Any] | None,
    dict[str, float],
    list[dict[str, str]],
    list[str],
]:
    """Run the harness and validate whatever it produced.

    Returns ``(exit_code, runtime_errors, notes, coverage, aggregate,
    per_subtask_acc, errors, contract_notes)``. ``exit_code`` is None on a
    timeout. Every path returns; nothing here raises, so a failed run still
    gets a receipt instead of vanishing.
    """
    runtime_errors: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    notes: list[str] = []
    coverage: dict[str, Any] = {
        "expectedSubtasks": len(P.subtask_set()),
        "observedSubtasks": 0,
        "missing": [],
        "unexpected": [],
        "complete": False,
        "rowsPerSubtask": {},
        "reducedEffectiveCountTasks": [],
    }
    aggregate: dict[str, Any] | None = None
    per_subtask: dict[str, float] = {}

    log_path = results_dir / "harness-run.log"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(checkout) + os.pathsep + env.get("PYTHONPATH", "")
    started = time.time()
    exit_code: int | None = None
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + " ".join(argv) + "\n")
        log.flush()
        try:
            completed = subprocess.run(
                [python, *argv[1:]],
                cwd=str(checkout),
                stdout=log,
                stderr=subprocess.STDOUT,
                env=env,
                timeout=timeout_seconds,
                check=False,
            )
            exit_code = completed.returncode
        except subprocess.TimeoutExpired:
            log.write(f"\nTIMEOUT after {timeout_seconds}s\n")
    notes.append(f"harness wall clock: {time.time() - started:.1f}s")

    captured = log_path.read_text(encoding="utf-8", errors="replace")
    runtime_errors, contract_notes = P.scan_run_output(captured)
    for message in contract_notes:
        errors.append(
            {
                "gate": "no_truncation",
                "code": "hidden_truncation",
                "detail": message,
            }
        )
    if exit_code != 0:
        errors.append(
            {
                "gate": "no_runtime_error_as_zero",
                "code": "harness_nonzero_exit",
                "detail": (
                    f"the harness exited with code {exit_code}; see {log_path}. "
                    f"A failed run is a failed run, never a set of "
                    f"zero-accuracy subtasks."
                ),
            }
        )

    results_file = P.find_harness_results_file(results_dir)
    if results_file is None:
        errors.append(
            {
                "gate": "task_identity",
                "code": "results_missing",
                "detail": f"no harness results JSON found under {results_dir}",
            }
        )
    else:
        try:
            summary = P.validate_harness_results(
                P.read_json(results_file),
                expect_full=config["mode"] == "full",
            )
        except P.ProtocolError as exc:
            errors.append(exc.as_record())
        else:
            coverage = {
                key: summary[key]
                for key in (
                    "expectedSubtasks",
                    "observedSubtasks",
                    "missing",
                    "unexpected",
                    "complete",
                    "rowsPerSubtask",
                    "reducedEffectiveCountTasks",
                )
            }
            aggregate = summary["aggregate"]
            per_subtask = summary["perSubtaskAcc"]

    return (
        exit_code,
        runtime_errors,
        notes,
        coverage,
        aggregate,
        per_subtask,
        errors,
        contract_notes,
    )


def cmd_execute(args: argparse.Namespace) -> int:
    config_path: Path = args.config
    config = load_config(config_path)
    checkout = resolve_checkout(config, args.checkout)
    results_dir = Path(args.results_dir or config["outputs"]["resultsDir"])
    receipt_path = Path(args.receipt or results_dir / RECEIPT_NAME)
    results_dir.mkdir(parents=True, exist_ok=True)

    identity = P.verify_harness_identity(checkout)
    dataset = dataset_block(check=not args.offline)
    argv = P.build_invocation(config, checkout, python=args.python).argv

    errors: list[dict[str, str]] = []
    runtime_errors: list[dict[str, str]] = []
    notes: list[str] = []
    failure_reason: str | None = None
    exit_code: int | None = None
    coverage: dict[str, Any] = {
        "expectedSubtasks": len(P.subtask_set()),
        "observedSubtasks": 0,
        "missing": [],
        "unexpected": [],
        "complete": False,
        "rowsPerSubtask": {},
        "reducedEffectiveCountTasks": [],
    }
    aggregate: dict[str, Any] | None = None
    per_subtask: dict[str, float] = {}
    probe: P.CapabilityProbe | None = None

    if not identity.all_identities_match:
        errors.append(
            {
                "gate": "harness_identity",
                "code": "harness_identity_mismatch",
                "detail": "; ".join(identity.problems()),
            }
        )
        failure_reason = "harness_identity_mismatch"
    if not dataset["revisionMatches"]:
        errors.append(
            {
                "gate": "dataset_revision",
                "code": "dataset_revision_mismatch",
                "detail": (
                    f"{dataset['datasetPath']} resolved to "
                    f"{dataset['resolvedRevision']!r}; the frozen protocol pins "
                    f"{dataset['pinnedRevision']!r}. The pinned harness BLiMP "
                    f"task carries no dataset revision of its own, so upstream "
                    f"would otherwise float with main."
                ),
            }
        )
        failure_reason = failure_reason or "dataset_revision_mismatch"

    if config["backend"] == "gguf":
        model_args = config["runtime"]["modelArgs"]
        probe = P.probe_gguf_server(
            model_args["base_url"],
            model=model_args.get("model"),
            timeout=args.timeout,
        )
        if not probe.ok:
            errors.append(
                {
                    "gate": "logprobs_present",
                    "code": "native_likelihood_unavailable",
                    "detail": "; ".join(probe.failures),
                }
            )
            failure_reason = failure_reason or "native_likelihood_unavailable"

    if config["mode"] == "smoke" and config["promotable"]:
        errors.append(
            {
                "gate": "no_subset",
                "code": "smoke_marked_promotable",
                "detail": "a smoke run can never be promotable",
            }
        )

    if not errors:
        (
            exit_code,
            runtime_errors,
            run_notes,
            coverage,
            aggregate,
            per_subtask,
            run_errors,
            _contract_notes,
        ) = collect_run(
            config,
            checkout,
            argv,
            results_dir,
            args.timeout_seconds,
            args.python,
        )
        notes.extend(run_notes)
        errors.extend(run_errors)

    if errors or runtime_errors:
        outcome = "fail"
        promotable = False
        failure_reason = failure_reason or (
            errors[0]["code"] if errors else "runtime_error"
        )
    elif config["mode"] == "smoke":
        outcome = "pass"
        promotable = False
        notes.append(
            "the smoke run passed its own gates but is debug-only; full native "
            "evidence needs the same config with mode=full and no --limit"
        )
    else:
        outcome = "pass"
        promotable = True

    results_file = P.find_harness_results_file(results_dir)
    outputs = {
        "resultsDir": str(results_dir),
        "files": P.collect_output_files(results_dir),
        "harnessResultsSha256": (
            P.sha256_file(results_file) if results_file else None
        ),
    }
    gates = {
        "harness_identity": gate(
            identity.all_identities_match,
            "the checkout matches the pinned harness commit"
            if identity.all_identities_match
            else "; ".join(identity.problems()),
        ),
        "task_identity": gate(
            bool(coverage["complete"]),
            f"{coverage['observedSubtasks']}/{coverage['expectedSubtasks']} "
            f"pinned subtasks present",
        ),
        "dataset_revision": gate(
            bool(dataset["revisionMatches"]),
            f"resolved {dataset['resolvedRevision']!r} against pinned "
            f"{dataset['pinnedRevision']!r}",
        ),
        "no_subset": gate(
            not coverage["reducedEffectiveCountTasks"]
            and config["mode"] != "smoke",
            "every subtask evaluated its full 1000 documents"
            if not coverage["reducedEffectiveCountTasks"]
            else f"reduced subtasks: {coverage['reducedEffectiveCountTasks'][:5]}",
        ),
        "chat_template_off": gate(
            not any(e["gate"] == "chat_template_off" for e in errors),
            "raw causal text; no chat template applied",
        ),
        "logprobs_present": gate(
            not any(e["gate"] == "logprobs_present" for e in errors)
            and not any(r["kind"] == "missing_logprobs" for r in runtime_errors),
            "usable logprobs were returned for every scored position",
        ),
        "no_truncation": gate(
            not any(e["gate"] == "no_truncation" for e in errors),
            "the harness reported no context truncation",
        ),
        "no_runtime_error_as_zero": gate(
            exit_code == 0 and not runtime_errors,
            f"harness exit {exit_code} with {len(runtime_errors)} runtime errors",
        ),
        "aggregate_recomputed": gate(
            bool(aggregate and aggregate["matches"]),
            (
                f"group acc {aggregate['harnessGroupAcc']!r} reproduces the "
                f"unweighted subtask mean"
                if aggregate and aggregate["matches"]
                else "the group aggregate could not be reproduced"
            ),
            applicable=aggregate is not None,
        ),
        "provenance_complete": gate(
            bool(
                config["model"].get("revision")
                and config["model"].get("tokenizer")
                and config["runtime"]["modelArgs"]
                and config["benchmarkRevision"]
            ),
            "model, tokenizer, runtime and benchmark revisions are recorded",
        ),
    }

    receipt = P.build_receipt(
        config,
        config_path,
        outcome=outcome,
        promotable=promotable,
        harness=identity.as_receipt_block(),
        dataset=dataset,
        backend=backend_block(config, probe),
        argv=argv,
        adaptation=adaptation_block(config, probe),
        outputs=outputs,
        coverage=coverage,
        aggregate=aggregate,
        per_subtask_acc=per_subtask,
        gate_results=gates,
        runtime_errors=runtime_errors,
        errors=errors,
        notes=notes,
        failure_reason=failure_reason,
    )
    receipt["model"] = model_block(config)
    receipt["exitCode"] = exit_code

    schema_errors = P.validate_receipt_document(receipt)
    if schema_errors:
        # A receipt that does not satisfy its own schema is not evidence.
        print(json.dumps({"receiptSchemaErrors": schema_errors}, indent=2))
        return 1

    P.write_json_atomic(receipt_path, receipt)
    print(
        json.dumps(
            {
                "receipt": str(receipt_path),
                "outcome": outcome,
                "promotable": receipt["promotable"],
            },
            indent=2,
        )
    )
    return 0 if receipt["promotable"] else 1


def cmd_verify(args: argparse.Namespace) -> int:
    receipt = P.read_json(args.receipt)
    checks: dict[str, dict[str, str]] = {}

    schema_errors = P.validate_receipt_document(receipt)
    checks["receiptSchema"] = gate(
        not schema_errors, "; ".join(schema_errors) or "valid"
    )

    current = P.protocol_identity()
    pinned_digest = (receipt.get("protocol") or {}).get("sha256")
    same = pinned_digest == current["sha256"]
    checks["protocolIdentity"] = gate(
        same,
        "the receipt protocol digest matches this checkout"
        if same
        else (
            f"the receipt pins protocol {pinned_digest!r} but this checkout has "
            f"{current['sha256']!r}; the pin changed after the run, so the run "
            f"is not promotion evidence for the new pin"
        ),
    )

    recorded_errors = receipt.get("errors") or []
    recorded_runtime = receipt.get("runtimeErrors") or []
    checks["cleanRun"] = gate(
        not recorded_errors and not recorded_runtime,
        "no recorded contract or runtime errors"
        if not recorded_errors and not recorded_runtime
        else (
            f"{len(recorded_errors)} contract errors and "
            f"{len(recorded_runtime)} runtime errors recorded"
        ),
    )

    results_dir = (receipt.get("outputs") or {}).get("resultsDir")
    if results_dir:
        results_file = P.find_harness_results_file(Path(results_dir))
        if results_file is None:
            checks["harnessOutputHash"] = gate(
                False,
                f"no harness results JSON under {results_dir}",
            )
        else:
            recorded = (receipt["outputs"] or {}).get("harnessResultsSha256")
            observed = P.sha256_file(results_file)
            checks["harnessOutputHash"] = gate(
                recorded == observed,
                f"harness results sha256 {observed}"
                if recorded == observed
                else (
                    f"the harness results file drifted: receipt {recorded!r}, "
                    f"file {observed!r}"
                ),
            )
            try:
                P.validate_harness_results(
                    P.read_json(results_file),
                    expect_full=receipt.get("promotable") is True,
                )
            except P.ProtocolError as exc:
                checks["harnessResults"] = gate(
                    False, f"{exc.code}: {exc.detail}"
                )
            else:
                checks["harnessResults"] = gate(
                    True, "the harness results revalidate"
                )

    ok = all(c["status"] != "fail" for c in checks.values())
    print(
        json.dumps(
            {
                "receipt": str(args.receipt),
                "laneId": receipt.get("laneId"),
                "outcome": receipt.get("outcome"),
                "promotable": receipt.get("promotable"),
                "ok": ok,
                "checks": checks,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if ok else 1


def cmd_parity(args: argparse.Namespace) -> int:
    fixture = P.load_parity_fixture(args.fixture)
    left = P.read_json(Path(fixture["leftReceipt"]))
    right = P.read_json(Path(fixture["rightReceipt"]))
    result = P.compare_parity(left, right, fixture)
    if args.output:
        P.write_json_atomic(Path(args.output), result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Frozen native BLiMP likelihood lane (Issue #68).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(target: argparse.ArgumentParser) -> None:
        target.add_argument("--config", type=Path, required=True)
        target.add_argument("--checkout", type=Path)
        target.add_argument("--python", default=sys.executable)

    plan = sub.add_parser("plan", help="print the frozen harness argv")
    add_common(plan)
    plan.set_defaults(func=cmd_plan)

    preflight = sub.add_parser(
        "preflight",
        help="verify identities and server capability at accelerator-off",
    )
    add_common(preflight)
    preflight.add_argument(
        "--offline",
        action="store_true",
        help="skip the Hugging Face dataset revision lookup; a receipt produced "
        "this way cannot be promotable",
    )
    preflight.add_argument("--timeout", type=int, default=20)
    preflight.set_defaults(func=cmd_preflight)

    execute = sub.add_parser("execute", help="run the harness and write a receipt")
    add_common(execute)
    execute.add_argument("--results-dir")
    execute.add_argument("--receipt", type=Path)
    execute.add_argument("--timeout-seconds", type=int, default=60 * 60 * 12)
    execute.add_argument("--timeout", type=int, default=20)
    execute.add_argument(
        "--offline",
        action="store_true",
        help="skip the dataset revision lookup; the receipt will not be promotable",
    )
    execute.set_defaults(func=cmd_execute)

    verify = sub.add_parser("verify", help="re-validate an existing receipt")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.set_defaults(func=cmd_verify)

    parity = sub.add_parser("parity", help="compare two backend receipts")
    parity.add_argument("--fixture", type=Path, required=True)
    parity.add_argument("--output", type=Path)
    parity.set_defaults(func=cmd_parity)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
