#!/usr/bin/env python3
"""CPU/synthetic tests for the frozen native BLiMP lane (Issue #68).

No GPU, no model, no network, no harness. These tests prove the ten claims
the issue asks for, using synthetic harness output and an injected fake
llama-server:

1. the pinned harness commit and task definitions verify, and drift is caught;
2. the vLLM backend contract is enforced and its loglikelihood mechanism is
   the one the pin describes;
3. the GGUF backend contract is enforced and a tiny synthetic BLiMP smoke
   through a fake owned llama-server yields loglikelihood-based evidence;
4. accidental ``--apply_chat_template`` or equivalent drift is rejected;
5. a server without usable logprobs cannot silently fall back to generation or
   prompted scoring;
6. ``--limit``/``--samples`` are debug-only and can never become full
   evidence;
7. a dataset revision mismatch blocks promotion;
8. the parity fixture detects intentionally changed BOS/EOS/tokenization
   behaviour;
9. a full 67-task run preserves subtask coverage and exact harness outputs;
10. a runtime failure stays a runtime failure and never becomes grammar
    accuracy zero.

Run with ``python3 test_native_blimp.py`` from this directory, or ``pytest``.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import native_blimp_protocol as P

HERE = Path(__file__).resolve().parent

CHECKOUT = Path("/tmp/lmeval-pin-68")
HAS_REAL_CHECKOUT = (
    (CHECKOUT / "lm_eval/tasks/blimp/_blimp.yaml").is_file()
    and (CHECKOUT / ".git").exists()
)

PINNED_SUBTASKS = P.pinned_subtasks()
ROWS = P.load_protocol()["task"]["rowsPerConfig"]


def vllm_config(**overrides) -> dict:
    config = {
        "schema": "native-blimp-config-1",
        "laneId": "native-blimp",
        "candidateId": "qwen35-2b",
        "backend": "vllm",
        "mode": "full",
        "promotable": True,
        "model": {
            "repo": "Qwen/Qwen3.5-2B",
            "revision": "15852e8c16360a2fea060d615a32b45270f8a8fc",
            "tokenizer": "Qwen/Qwen3.5-2B",
            "tokenizerRevision": "15852e8c16360a2fea060d615a32b45270f8a8fc",
        },
        "runtime": {
            "modelArgs": {
                "pretrained": "Qwen/Qwen3.5-2B",
                "dtype": "float16",
                "revision": "15852e8c16360a2fea060d615a32b45270f8a8fc",
                "tokenizer": "Qwen/Qwen3.5-2B",
                "tokenizer_revision": "15852e8c16360a2fea060d615a32b45270f8a8fc",
                "max_model_len": 4096,
                "seed": 1234,
                "quantization": None,
                "tensor_parallel_size": 1,
                "add_bos_token": True,
            },
            "vllmVersion": "0.30.0",
        },
        "benchmarkRevision": "deadbeefcafe",
        "outputs": {
            "resultsDir": "/kaggle/working/results/native-blimp",
            "logSamples": True,
        },
    }
    config.update(overrides)
    return config


def gguf_config(**overrides) -> dict:
    config = {
        "schema": "native-blimp-config-1",
        "laneId": "native-blimp",
        "candidateId": "bonsai-8b-q1_0",
        "backend": "gguf",
        "mode": "full",
        "promotable": True,
        "model": {
            "repo": "prism-ml/Bonsai-8B-gguf",
            "revision": "48516770dd04643643e9f9019a2a349cf26c5dbd",
            "tokenizer": "prism-ml/Bonsai-8B-gguf",
            "ggufFile": "Bonsai-8B-Q1_0.gguf",
            "ggufSha256": "ab" * 32,
        },
        "runtime": {
            "modelArgs": {
                "base_url": "http://127.0.0.1:8080",
                "model": "bonsai-8b",
                "parallel": 2,
                "timeout": 300,
            },
            "llamaCppBuild": {
                "repository": "https://github.com/PrismML-Eng/llama.cpp.git",
                "revision": "842b1880415d6f508f03b789e5ce70194def7bfd",
                "buildFlags": ["-DGGML_CUDA=ON"],
                "serverArgs": [
                    "--model", "/kaggle/working/Bonsai-8B-Q1_0.gguf",
                    "--parallel", "2", "--host", "127.0.0.1", "--port", "8080",
                ],
                "serverBuild": "build 9999",
            },
            "server": {
                "baseUrl": "http://127.0.0.1:8080",
                "pid": 4242,
                "port": 8080,
                "totalSlots": 2,
            },
        },
        "benchmarkRevision": "deadbeefcafe",
        "outputs": {
            "resultsDir": "/kaggle/working/results/native-blimp",
            "logSamples": True,
        },
    }
    config.update(overrides)
    return config


def synthetic_results(
    acc: float = 0.62,
    rows: int = ROWS,
    model: str = "vllm",
    tasks: list[str] | None = None,
) -> dict:
    """Build a harness results document shaped like the pinned harness output."""
    names = tasks if tasks is not None else PINNED_SUBTASKS
    per_task = {name: {"acc": acc, "acc_stderr": 0.015} for name in names}
    mean = sum(per_task[n]["acc"] for n in names) / len(names)
    return {
        "results": per_task,
        "groups": {"blimp": {"acc": mean, "acc_stderr": 0.0018}},
        "group_subtasks": {"blimp": list(names)},
        "configs": {
            names[0]: {
                "dataset_path": "nyu-mll/blimp",
                "dataset_name": "adjunct_island",
                "validation_split": "train",
                "output_type": "multiple_choice",
                "doc_to_text": "",
                "doc_to_target": 0,
                "doc_to_choice": "{{[sentence_good, sentence_bad]}}",
                "num_fewshot": 0,
            }
        },
        "versions": {name: 1.0 for name in names},
        "n-shot": {name: 0 for name in names},
        "higher_is_better": {name: {"acc": True} for name in names},
        "n-samples": {
            name: {"original": ROWS, "effective": rows} for name in names
        },
        "config": {
            "model": model,
            "model_args": {},
            "batch_size": 1,
            "device": "cuda:0",
            "use_cache": None,
            "limit": None,
            "bootstrap_iters": None,
            "gen_kwargs": None,
            "random_seed": 1234,
            "numpy_seed": 1234,
            "torch_seed": 1234,
            "fewshot_seed": 1234,
        },
        "git_hash": P.load_protocol()["harness"]["pinnedCommit"],
        "date": 1758000000.0,
        "lm_eval_version": P.load_protocol()["harness"]["packageVersion"],
        "transformers_version": "4.57.1",
    }


DATASET_REV = "877fba0801ffb7cbd8c39c1ff314a46f053f6036"
HARNESS_COMMIT = "d6de81643928d653435c431bae19945d41d32520"


class FakeServer:
    """An injected in-process stand-in for an owned llama.cpp server.

    It records every request so a test can assert that the pinned gguf backend
    scores through exactly the routes it claims: /tokenize with add_special,
    and /v1/completions with a token-id prompt, logprobs, and a logit_bias
    list of [token_id, bias] pairs.
    """

    def __init__(self, total_slots=2, with_tokenize=True, with_logprobs=True,
                 forced_token_mismatch=False, with_top_logprobs=True, bos=True):
        self.total_slots = total_slots
        self.with_tokenize = with_tokenize
        self.with_logprobs = with_logprobs
        self.forced_token_mismatch = forced_token_mismatch
        self.with_top_logprobs = with_top_logprobs
        self.bos = bos
        self.requests = []

    def __call__(self, url, payload=None):
        self.requests.append((url, payload))
        if url.endswith("/props"):
            return {"total_slots": self.total_slots, "model_path": "/fake.gguf"}
        if url.endswith("/tokenize"):
            if not self.with_tokenize:
                raise ConnectionError("no /tokenize route on this server")
            content = payload.get("content", "") if payload else ""
            # Token ids must depend on the content, otherwise the pinned
            # context/continuation split can never see a real difference.
            body = [700 + 7 * index for index, _ in enumerate(content.split())]
            head = [1] if self.bos else []
            return {"tokens": head + body}
        if url.endswith("/v1/completions"):
            assert isinstance(payload.get("prompt"), list), "prefix must be token ids"
            bias = payload.get("logit_bias")
            assert isinstance(bias, list), "logit_bias must be a list of pairs"
            assert isinstance(bias[0], list) and len(bias[0]) == 2, "pair form"
            target = bias[0][0]
            if not self.with_logprobs:
                return {"choices": [{"text": " dog", "logprobs": None}]}
            sampled = target + 1 if self.forced_token_mismatch else target
            # A real server's logprob depends on which token is forced, so a
            # changed BOS/tokenization convention shifts it. Deriving the
            # value from the token id is what makes the parity fixture's
            # loglikelihood tolerance meaningful in these CPU tests.
            value = -0.01 * (target % 17) - 0.125
            entry = {"id": sampled, "token": "x", "logprob": value}
            if self.with_top_logprobs:
                entry["top_logprobs"] = [
                    {"id": sampled, "token": "x", "logprob": value},
                    {"id": target, "token": "y", "logprob": -9.5},
                ]
            return {"choices": [{"text": "", "logprobs": {"content": [entry]}}]}
        raise AssertionError("unexpected route " + url)

    def routes(self):
        return [url.rsplit("/", 1)[-1] for url, _ in self.requests]


def expect_protocol_error(code, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except P.ProtocolError as exc:
        assert exc.code == code, "expected %s, got %s: %s" % (code, exc.code, exc.detail)
        return exc
    raise AssertionError("expected ProtocolError " + code + ", but the call succeeded")


def probe(server):
    return P.probe_gguf_server("http://127.0.0.1:8080", model=None, opener=server)


# --------------------------------------------------------------------------
# 1. pinned harness commit and task definitions verify
# --------------------------------------------------------------------------


def test_pin_is_self_consistent():
    protocol = P.load_protocol()
    assert protocol["harness"]["pinnedCommit"] == HARNESS_COMMIT
    assert protocol["harness"]["packageVersion"] == "0.4.14.dev0"
    assert len(PINNED_SUBTASKS) == 67
    assert len(set(PINNED_SUBTASKS)) == 67
    assert all(name.startswith("blimp_") for name in PINNED_SUBTASKS)
    assert protocol["task"]["datasetConfigs"] == 67
    assert protocol["task"]["rowsPerConfig"] == 1000
    assert protocol["task"]["totalRows"] == 67000
    assert protocol["task"]["pinnedDatasetRevision"] == DATASET_REV
    assert protocol["task"]["groupAggregate"]["weightBySize"] is False
    assert protocol["task"]["groupAggregate"]["aggregation"] == "mean"
    assert protocol["task"]["outputType"] == "multiple_choice"
    assert protocol["task"]["docToTarget"] == 0
    assert protocol["task"]["numFewshot"] == 0


def test_pinned_subtasks_match_the_real_harness_group_file():
    if not HAS_REAL_CHECKOUT:
        print("  (skipped: no pinned harness checkout available)")
        return
    import re

    text = (CHECKOUT / "lm_eval/tasks/blimp/_blimp.yaml").read_text()
    actual = re.findall(r'-\s+"(blimp_[A-Za-z0-9_]+)"', text)
    assert actual == PINNED_SUBTASKS


def test_harness_identity_verifies_and_detects_drift():
    if not HAS_REAL_CHECKOUT:
        print("  (skipped: no pinned harness checkout available)")
        return
    identity = P.verify_harness_identity(CHECKOUT)
    assert identity.commit_matches is True
    assert identity.file_hashes_match is True
    assert identity.tree_hashes_match is True
    assert identity.subtask_count == 67
    assert identity.all_identities_match is True
    assert identity.problems() == []

    with tempfile.TemporaryDirectory() as tmp:
        subset = Path(tmp) / "harness"
        for rel in P.load_protocol()["harness"]["pinnedFileSha256"]:
            src = CHECKOUT / rel
            if not src.is_file():
                continue
            dst = subset / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
        target = subset / "lm_eval/models/gguf.py"
        target.write_text(target.read_text() + "\n# a silent edit\n")
        drifted = P.verify_harness_identity(subset)
        assert drifted.all_identities_match is False
        assert "lm_eval/models/gguf.py" in drifted.mismatched_files
        assert drifted.problems()


def test_harness_tree_hash_detects_a_task_yaml_edit():
    if not HAS_REAL_CHECKOUT:
        print("  (skipped: no pinned harness checkout available)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        blimp = Path(tmp) / "blimp"
        blimp.mkdir()
        for name in ("adjunct_island.yaml", "causative.yaml", "transitive.yaml"):
            source = CHECKOUT / "lm_eval/tasks/blimp" / name
            (blimp / name).write_bytes(source.read_bytes())
        before = P.subtask_tree_hash(blimp)
        (blimp / "causative.yaml").write_text("task: blimp_causative\n")
        assert P.subtask_tree_hash(blimp) != before


def test_pinned_backend_hashes_match_the_checkout():
    if not HAS_REAL_CHECKOUT:
        print("  (skipped: no pinned harness checkout available)")
        return
    pinned = P.load_protocol()["harness"]["pinnedFileSha256"]
    assert P.sha256_file(CHECKOUT / "lm_eval/models/gguf.py") == pinned["lm_eval/models/gguf.py"]
    vllm = pinned["lm_eval/models/vllm_causallms.py"]
    assert P.sha256_file(CHECKOUT / "lm_eval/models/vllm_causallms.py") == vllm
    template = pinned["lm_eval/tasks/blimp/_template_yaml"]
    assert P.sha256_file(CHECKOUT / "lm_eval/tasks/blimp/_template_yaml") == template


def test_vllm_backend_scores_through_prompt_logprobs():
    """The pinned vLLM lane must be the prompt_logprobs path, not echo."""
    if not HAS_REAL_CHECKOUT:
        print("  (skipped: no pinned harness checkout available)")
        return
    source = (CHECKOUT / "lm_eval/models/vllm_causallms.py").read_text()
    assert "prompt_logprobs=1" in source
    assert "max_tokens=1" in source
    # A harness regression that reintroduces echo-based scoring, or an
    # accidentally applied chat template as the default, must be caught.
    spec = P.load_protocol()["backends"]["vllm"]
    assert spec["chatTemplateDefault"] == "off"
    assert "--apply_chat_template" in P.forbidden_flags()[0]


# --------------------------------------------------------------------------
# 2. vLLM backend contract and tiny smoke
# --------------------------------------------------------------------------


def test_vllm_config_builds_a_native_argv():
    config = vllm_config()
    invocation = P.build_invocation(config, CHECKOUT, python="/usr/bin/python3")
    argv = invocation.argv
    assert argv[1:3] == ["-m", "lm_eval"]
    assert "--model" in argv and argv[argv.index("--model") + 1] == "vllm"
    assert argv[argv.index("--tasks") + 1] == "blimp"
    assert invocation.smoke is False
    assert invocation.limit is None
    joined = " ".join(argv)
    for flag in P.forbidden_flags()[0]:
        assert flag not in joined, flag
    assert "prompted" not in joined.lower()
    metadata = json.loads(argv[argv.index("--metadata") + 1])
    assert metadata["native_blimp_lane"] == "native-blimp"
    assert metadata["harness_pinned_commit"] == HARNESS_COMMIT
    assert metadata["dataset_pinned_revision"] == DATASET_REV


def test_vllm_requires_explicit_max_model_len():
    # Leaving both max_model_len and max_length unset would let the backend
    # resolve the context from the model config, unbinding the
    # no-hidden-truncation guarantee. That is a hard protocol error.
    config = vllm_config()
    del config["runtime"]["modelArgs"]["max_model_len"]
    exc = expect_protocol_error(
        "context_length_unbound", P.build_invocation, config, CHECKOUT
    )
    assert exc.gate == "no_truncation"


def test_vllm_rejects_conflicting_length_arguments():
    config = vllm_config()
    config["runtime"]["modelArgs"]["max_length"] = 4096
    expect_protocol_error(
        "backend_arg_conflict", P.validate_backend_model_args, "vllm",
        config["runtime"]["modelArgs"],
    )


def test_vllm_accepts_max_length_alone():
    config = vllm_config()
    del config["runtime"]["modelArgs"]["max_model_len"]
    config["runtime"]["modelArgs"]["max_length"] = 4096
    P.validate_backend_model_args("vllm", config["runtime"]["modelArgs"])
    invocation = P.build_invocation(config, CHECKOUT, python="/usr/bin/python3")
    assert "max_length=4096" in invocation.argv[invocation.argv.index("--model_args") + 1]


def test_vllm_rejects_enable_thinking():
    config = vllm_config()
    config["runtime"]["modelArgs"]["enable_thinking"] = True
    expect_protocol_error(
        "enable_thinking_set", P.validate_backend_model_args, "vllm",
        config["runtime"]["modelArgs"],
    )


def test_vllm_smoke_records_loglikelihood_evidence_and_stays_unpromotable():
    config = vllm_config(mode="smoke", promotable=False, smokeLimit=4)
    invocation = P.build_invocation(config, CHECKOUT, python="/usr/bin/python3")
    assert invocation.smoke is True
    assert "--limit" in invocation.argv
    summary = P.validate_harness_results(
        synthetic_results(rows=4), expect_full=False, expected_tasks={"blimp_causative"}
    )
    assert summary["observedSubtasks"] == 1
    assert summary["aggregate"]["matches"] is True
    assert summary["perSubtaskAcc"]["blimp_causative"] == 0.62


# --------------------------------------------------------------------------
# 3. GGUF backend contract and tiny smoke through an owned server
# --------------------------------------------------------------------------


def test_gguf_probe_succeeds_against_a_compatible_server():
    server = FakeServer()
    result = probe(server)
    assert result.ok is True, result.failures
    assert result.detail["logprobsShape"] == "modern-openai-content"
    assert result.detail["forcedTokenRoundTrip"] is True
    assert result.detail["totalSlots"] == 2
    assert set(server.routes()) == {"props", "tokenize", "completions"}
    assert all("/v1/completions" in url for url, _ in server.requests
               if url.endswith("completions"))


def test_gguf_probe_records_the_bos_convention():
    server = FakeServer(bos=True)
    result = probe(server)
    assert result.ok is True
    tokenize = [payload for url, payload in server.requests if url.endswith("/tokenize")]
    assert tokenize, "the pinned backend must tokenize through the server"
    assert tokenize[0]["add_special"] is True
    assert tokenize[0]["content"] == "The"
    # A changed BOS convention changes the ids the server returns, which is the
    # signal the parity fixture exists to catch.
    no_bos = probe(FakeServer(bos=False))
    assert no_bos.ok is True
    assert no_bos.detail["forcedTokenLogprob"] != result.detail["forcedTokenLogprob"]


def test_gguf_scores_minimal_pairs_by_teacher_forcing():
    """Replay the pinned backend's own scoring loop against the fake server."""
    if not HAS_REAL_CHECKOUT:
        print("  (skipped: no pinned harness checkout available)")
        return
    gguf_class = load_pinned_gguf_class()
    backend = gguf_class(base_url="http://127.0.0.1:8080", model=None, parallel=1)
    server = FakeServer()
    backend._post_with_retries = lambda url, payload, retries=3, delay=0: server(url, payload)
    backend._detect_total_slots = lambda: 1
    # The pinned loop takes ((context, continuation), id_slot).
    item = ((("", "The dog barks."), 0))
    scores = backend._loglikelihood_one(item)
    loglikelihood, is_greedy = scores
    assert loglikelihood < 0
    assert isinstance(is_greedy, bool)
    # The scoring loop must have hit /tokenize and /v1/completions, never a
    # chat route and never a text-prompt echo request.
    assert "tokenize" in server.routes()
    assert "completions" in server.routes()
    assert all("chat" not in url for url, _ in server.requests)


def load_pinned_gguf_class():
    """Load the pinned GGUFLM class with stubbed third-party imports.

    The pinned ``gguf.py`` imports ``requests``, ``tqdm`` and ``lm_eval.api.*``
    at module scope. Rather than install anything, this loads the real source
    with lightweight stand-ins so the test exercises the actual upstream
    scoring loop byte-for-byte, not a copy of it.
    """
    import importlib.util
    import sys
    import types

    def stub(name, **attrs):
        module = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(module, key, value)
        sys.modules[name] = module
        return module

    saved = {key: sys.modules.get(key) for key in
             ("requests", "requests.exceptions", "tqdm", "lm_eval",
              "lm_eval.api", "lm_eval.api.model", "lm_eval.api.registry",
              "lm_eval.models", "lm_eval.models.utils")}

    class _RequestException(Exception):
        pass

    class _LM:
        def __init__(self):
            pass

    def _register_model(*names):
        def decorate(cls):
            return cls
        return decorate

    stub("requests", RequestException=_RequestException)
    stub("requests.exceptions", RequestException=_RequestException)
    stub("tqdm", tqdm=lambda iterable, **kw: iterable)
    stub("lm_eval")
    stub("lm_eval.api")
    stub("lm_eval.api.model", LM=_LM)
    stub("lm_eval.api.registry", register_model=_register_model)
    stub("lm_eval.models")
    stub("lm_eval.models.utils", normalize_gen_kwargs=lambda kwargs, default: kwargs)
    try:
        spec = importlib.util.spec_from_file_location(
            "pinned_gguf_under_test", CHECKOUT / "lm_eval/models/gguf.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.GGUFLM
    finally:
        for key, value in saved.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value


def test_gguf_config_builds_a_native_argv():
    config = gguf_config()
    invocation = P.build_invocation(config, CHECKOUT, python="/usr/bin/python3")
    assert invocation.argv[argv_index(invocation.argv, "--model") + 1] == "gguf"
    assert "base_url=http://127.0.0.1:8080" in invocation.argv[argv_index(invocation.argv, "--model_args") + 1]
    assert "--limit" not in invocation.argv


def argv_index(argv, flag):
    return argv.index(flag)


# --------------------------------------------------------------------------
# 4. chat-template drift is rejected
# --------------------------------------------------------------------------


def test_chat_template_drift_is_rejected_on_every_route():
    flags, reasons = P.forbidden_flags()
    for flag in ("--apply_chat_template", "--fewshot_as_multiturn", "--system_instruction"):
        assert flag in flags
        assert reasons[flag]
    exc = expect_protocol_error(
        "enable_thinking_set", P.validate_backend_model_args, "vllm",
        vllm_config()["runtime"]["modelArgs"] | {"enable_thinking": True},
    )
    assert exc.gate == "chat_template_off"


def test_apply_chat_template_in_harness_output_is_rejected():
    results = synthetic_results()
    results["config"]["apply_chat_template"] = True
    expect_protocol_error(
        "apply_chat_template_in_config", P.validate_harness_results, results, True
    )
    results = synthetic_results()
    results["config"]["fewshot_as_multiturn"] = True
    expect_protocol_error(
        "fewshot_as_multiturn_in_config", P.validate_harness_results, results, True
    )


def test_fewshot_drift_is_rejected():
    results = synthetic_results()
    results["n-shot"]["blimp_causative"] = 5
    expect_protocol_error("fewshot_drift", P.validate_harness_results, results, True)


def test_gguf_chat_only_base_url_is_rejected():
    args = gguf_config()["runtime"]["modelArgs"]
    args["base_url"] = "http://127.0.0.1:8080/v1/chat/completions"
    expect_protocol_error("chat_route_forbidden", P.validate_backend_model_args, "gguf", args)


# --------------------------------------------------------------------------
# 5. a server without usable logprobs cannot silently degrade
# --------------------------------------------------------------------------


def test_server_without_logprobs_fails_instead_of_falling_back():
    server = FakeServer(with_logprobs=False)
    result = probe(server)
    assert result.ok is False
    assert any("logprobs.content" in f for f in result.failures)
    assert result.detail["logprobsShape"] == "missing"
    # The probe never silently re-routes to a chat or generation endpoint.
    assert all("chat" not in url for url, _ in server.requests)


def test_server_without_tokenize_is_protocol_unavailable():
    server = FakeServer(with_tokenize=False)
    result = probe(server)
    assert result.ok is False
    assert any("/tokenize" in f for f in result.failures)


def test_server_that_will_not_force_the_token_is_a_protocol_failure():
    result = probe(FakeServer(forced_token_mismatch=True))
    assert result.ok is False
    assert result.detail["logprobsShape"] == "forced-token-mismatch"


def test_server_without_top_logprobs_leaves_the_decision_undefined():
    result = probe(FakeServer(with_top_logprobs=False))
    assert result.ok is False
    assert result.detail["logprobsShape"] == "no-top-logprobs"


def test_missing_logprobs_in_run_output_is_a_runtime_error():
    log = "RuntimeError: Missing logprobs in scoring response: {'choices': []}"
    runtime, contract = P.scan_run_output(log)
    assert [r["kind"] for r in runtime] == ["missing_logprobs"]
    assert contract == []


def test_unexpected_backend_is_rejected():
    results = synthetic_results()
    results["config"]["model"] = "local-completions"
    expect_protocol_error("unexpected_backend", P.validate_harness_results, results, True)


def test_legacy_echo_backends_are_documented_as_unusable():
    gguf_spec = P.load_protocol()["backends"]["gguf"]
    assert gguf_spec["chatOnlyServerSatisfiesBackend"] is False
    legacy = {entry["harnessModelArg"] for entry in gguf_spec["unsupportedBackends"]}
    assert "local-completions" in legacy
    reason = gguf_spec["unsupportedBackends"][0]["reason"]
    assert "token_logprobs" in reason


# --------------------------------------------------------------------------
# 6. --limit / --samples are debug-only
# --------------------------------------------------------------------------


def test_smoke_cannot_be_marked_promotable():
    config = vllm_config(mode="smoke", promotable=True, smokeLimit=2)
    expect_protocol_error("smoke_marked_promotable", P.build_invocation, config, CHECKOUT)


def test_smoke_requires_a_recorded_limit():
    config = vllm_config(mode="smoke", promotable=False)
    expect_protocol_error("smoke_limit_missing", P.build_invocation, config, CHECKOUT)


def test_full_run_cannot_carry_a_smoke_limit():
    config = vllm_config()
    config["smokeLimit"] = 4
    expect_protocol_error("smoke_limit_on_full_run", P.build_invocation, config, CHECKOUT)


def test_limit_in_harness_output_blocks_promotion():
    results = synthetic_results()
    results["config"]["limit"] = 8
    expect_protocol_error("limit_in_harness_config", P.validate_harness_results, results, True)


def test_samples_subset_in_harness_output_blocks_promotion():
    results = synthetic_results()
    results["config"]["samples"] = {"blimp_causative": [0, 1, 2]}
    expect_protocol_error("samples_in_harness_config", P.validate_harness_results, results, True)


def test_reduced_effective_count_cannot_be_sold_as_full():
    results = synthetic_results(rows=8)
    exc = expect_protocol_error(
        "subset_reported_as_full", P.validate_harness_results, results, True
    )
    assert exc.gate == "no_subset"
    assert "debug output" in exc.detail


# --------------------------------------------------------------------------
# 7. dataset revision mismatch blocks promotion
# --------------------------------------------------------------------------


def test_dataset_revision_match_and_mismatch():
    good = P.dataset_identity_block(DATASET_REV)
    assert good["revisionMatches"] is True
    bad = P.dataset_identity_block("0" * 40)
    assert bad["revisionMatches"] is False
    unknown = P.dataset_identity_block(None)
    assert unknown["revisionMatches"] is False, "unresolvable is never a pass"


def test_dataset_revision_mismatch_is_a_recorded_error():
    receipt = P.build_receipt(
        vllm_config(),
        Path(__file__),
        outcome="fail",
        promotable=False,
        harness=P.verify_harness_identity(CHECKOUT).as_receipt_block(),
        dataset=P.dataset_identity_block("0" * 40),
        backend={"name": "vllm"},
        argv=[],
        adaptation={
            "chatTemplate": "disabled",
            "likelihoodNormalization": "summed",
            "numFewshot": 0,
            "bosHandling": "explicit",
            "eosHandling": "never appended",
        },
        outputs={"resultsDir": "/tmp/x", "files": []},
        coverage={
            "expectedSubtasks": 67, "observedSubtasks": 0, "missing": [],
            "unexpected": [], "complete": False, "rowsPerSubtask": {},
            "reducedEffectiveCountTasks": [],
        },
        aggregate=None,
        per_subtask_acc={},
        gate_results={},
        runtime_errors=[],
        errors=[{
            "gate": "dataset_revision",
            "code": "dataset_revision_mismatch",
            "detail": "resolved to the wrong revision",
        }],
        notes=[],
        failure_reason="dataset_revision_mismatch",
    )
    assert receipt["promotable"] is False
    assert receipt["datasetObserved"]["revisionMatches"] is False
    assert receipt["errors"][0]["code"] == "dataset_revision_mismatch"


def test_dataset_revision_note_is_explicit():
    task = P.load_protocol()["task"]
    assert task["datasetRevisionIsHarnessPinned"] is False
    assert "no dataset revision key" in task["datasetRevisionNote"]


def test_resolve_dataset_revision_tolerates_transport_failure():
    def boom(url):
        raise OSError("no network in the CPU tests")

    assert P.resolve_dataset_revision("nyu-mll/blimp", opener=boom) is None


def test_resolve_dataset_revision_reads_the_opener():
    payload = {"sha": DATASET_REV}
    assert P.resolve_dataset_revision(
        "nyu-mll/blimp", opener=lambda url: payload
    ) == DATASET_REV


# --------------------------------------------------------------------------
# 8. parity fixture detects changed BOS/EOS/tokenization
# --------------------------------------------------------------------------


def parity_fixture(**overrides):
    fixture = {
        "laneId": P.PARITY_SCHEMA_ID,
        "modelArtifactSha256": "ab" * 32,
        "leftReceipt": "/tmp/left.json",
        "rightReceipt": "/tmp/right.json",
        "leftBackend": "vllm",
        "rightBackend": "gguf",
        "loglikelihoodTolerance": 0.05,
        "decisionTolerance": 0.0,
        "subtaskAccuracyTolerance": 0.02,
    }
    fixture.update(overrides)
    return fixture


def parity_receipt(backend, artifact="ab" * 32, offset=0.0, flips=False):
    acc = {name: 0.62 for name in PINNED_SUBTASKS}
    items = {}
    for name in PINNED_SUBTASKS[:8]:
        preferred = "sentence_bad" if flips else "sentence_good"
        items[name + "#0"] = {"loglikelihood": -12.5 + offset, "preferred": preferred}
    return {
        "schema": "native-blimp-receipt-1",
        "laneId": "native-blimp",
        "backend": {"name": backend},
        "model": {"artifactSha256": artifact},
        "coverage": {"complete": True, "expectedSubtasks": 67, "observedSubtasks": 67},
        "perSubtaskAcc": acc,
        "perItemLoglikelihood": items,
    }


def test_parity_passes_for_two_backends_on_the_same_artifact():
    result = P.compare_parity(
        parity_receipt("vllm"), parity_receipt("gguf", offset=0.001), parity_fixture()
    )
    assert result["ok"] is True, result["findings"]
    assert result["details"]["itemsCompared"] == 8


def test_parity_detects_a_changed_bos_or_tokenization_convention():
    result = P.compare_parity(
        parity_receipt("vllm"), parity_receipt("gguf", offset=4.2), parity_fixture()
    )
    assert result["ok"] is False
    assert any("loglikelihood" in f for f in result["findings"])
    assert result["details"]["worstLoglikelihoodDelta"] > 4.0


def test_parity_detects_systematic_decision_flips():
    result = P.compare_parity(
        parity_receipt("vllm"), parity_receipt("gguf", flips=True), parity_fixture()
    )
    assert result["ok"] is False
    assert result["details"]["decisionFlips"] == 8
    assert any("decisions differ" in f for f in result["findings"])


def test_parity_refuses_to_compare_a_backend_with_itself():
    expect_protocol_error(
        "not_cross_backend",
        P.compare_parity,
        parity_receipt("vllm"),
        parity_receipt("vllm"),
        parity_fixture(leftBackend="vllm", rightBackend="vllm"),
    )


def test_parity_refuses_to_mix_different_model_artifacts():
    result = P.compare_parity(
        parity_receipt("vllm", artifact="cd" * 32), parity_receipt("gguf"), parity_fixture()
    )
    assert result["ok"] is False
    assert any("model evidence" in f for f in result["findings"])


def test_parity_refuses_incomplete_runs():
    left = parity_receipt("vllm")
    left["coverage"]["complete"] = False
    result = P.compare_parity(left, parity_receipt("gguf"), parity_fixture())
    assert result["ok"] is False
    assert any("complete 67-subtask" in f for f in result["findings"])


def test_parity_fixture_loader_requires_every_key():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fixture.json"
        incomplete = parity_fixture()
        del incomplete["loglikelihoodTolerance"]
        path.write_text(json.dumps(incomplete))
        expect_protocol_error("fixture_incomplete", P.load_parity_fixture, path)
        path.write_text(json.dumps({"laneId": "wrong"}))
        expect_protocol_error("fixture_lane_mismatch", P.load_parity_fixture, path)


# --------------------------------------------------------------------------
# 9. a full 67-task run preserves coverage and exact harness outputs
# --------------------------------------------------------------------------


def test_full_run_passes_every_gate():
    summary = P.validate_harness_results(synthetic_results(), expect_full=True)
    assert summary["complete"] is True
    assert summary["observedSubtasks"] == 67
    assert summary["missing"] == [] and summary["unexpected"] == []
    assert summary["reducedEffectiveCountTasks"] == []
    assert set(summary["rowsPerSubtask"].values()) == {ROWS}
    assert len(summary["perSubtaskAcc"]) == 67
    assert summary["aggregate"]["matches"] is True
    assert summary["aggregate"]["weightBySize"] is False


def test_missing_subtask_is_coverage_incomplete():
    results = synthetic_results()
    del results["results"]["blimp_wh_island"]
    del results["groups"]["blimp"]
    exc = expect_protocol_error(
        "coverage_incomplete", P.validate_harness_results, results, True
    )
    assert exc.gate == "task_identity"
    assert "blimp_wh_island" in exc.detail


def test_unexpected_subtask_is_rejected():
    results = synthetic_results()
    results["results"]["blimp_not_a_real_phenomenon"] = {"acc": 0.5}
    expect_protocol_error(
        "coverage_unexpected", P.validate_harness_results, results, True
    )


def test_group_aggregate_is_recomputed_independently():
    results = synthetic_results()
    results["groups"]["blimp"]["acc"] = 0.99
    exc = expect_protocol_error(
        "aggregate_mismatch", P.validate_harness_results, results, True
    )
    assert exc.gate == "aggregate_recomputed"
    assert "unweighted mean" in exc.detail


def test_aggregate_is_unweighted_mean_not_size_weighted():
    results = synthetic_results()
    results["n-samples"]["blimp_causative"] = {"original": ROWS, "effective": 3}
    summary = P.validate_harness_results(results, expect_full=False)
    assert summary["aggregate"]["matches"] is True


def test_task_definition_drift_is_rejected():
    results = synthetic_results()
    results["configs"][PINNED_SUBTASKS[0]]["output_type"] = "loglikelihood"
    expect_protocol_error(
        "task_definition_drift", P.validate_harness_results, results, True
    )


def test_lm_eval_version_drift_is_rejected():
    results = synthetic_results()
    results["lm_eval_version"] = "0.4.13"
    expect_protocol_error(
        "lm_eval_version_mismatch", P.validate_harness_results, results, True
    )


def test_exact_harness_outputs_are_hashed_and_reverified():
    with tempfile.TemporaryDirectory() as tmp:
        results_dir = Path(tmp)
        results_file = results_dir / "results_2026-10-03T00-00-00.json"
        results_file.write_text(json.dumps(synthetic_results(), indent=2))
        files = P.collect_output_files(results_dir)
        assert len(files) == 1
        assert P.sha256_file(results_file) == files[0]["sha256"]
        assert P.find_harness_results_file(results_dir) == results_file
        P.validate_harness_results(P.read_json(results_file), expect_full=True)


# --------------------------------------------------------------------------
# 10. runtime failure never becomes grammar accuracy zero
# --------------------------------------------------------------------------


def fake_harness_block():
    return {
        "checkout": "/tmp/lmeval-pin-68",
        "headCommit": HARNESS_COMMIT,
        "commitMatches": True,
        "fileSha256": {},
        "fileHashesMatch": True,
        "treeHashes": {},
        "treeHashesMatch": True,
        "allIdentitiesMatch": True,
    }


def fake_adaptation():
    return {
        "chatTemplate": "disabled",
        "likelihoodNormalization": "summed over the continuation span",
        "numFewshot": 0,
        "bosHandling": "vLLM add_bos_token=True",
        "eosHandling": "EOS is never appended to a scored continuation",
        "maxContextTokens": 4096,
        "truncationObserved": False,
    }


def test_runtime_error_patterns_are_classified():
    samples = {
        "Missing logprobs in scoring response: {}": "missing_logprobs",
        "RuntimeError: Invalid scoring response: None": "invalid_scoring_response",
        "Server did not sample the forced token id 42": "forced_token_mismatch",
        "Failed to get a valid response after 3 retries.": "server_retries_exhausted",
        "NotImplementedError: loglikelihood_rolling not yet supported": "unsupported_request_type",
        "torch.cuda.OutOfMemoryError: CUDA out of memory.": "cuda_oom",
        "Traceback (most recent call last):": "python_traceback",
    }
    for text, kind in samples.items():
        runtime, contract = P.scan_run_output(text)
        assert contract == [], text
        assert kind in [r["kind"] for r in runtime], text


def test_clean_run_output_produces_no_errors():
    clean = "Running loglikelihood requests: 100%|####| 67000/67000\n"
    assert P.scan_run_output(clean) == ([], [])


def test_truncation_warning_is_a_contract_error_not_a_score():
    log = "Context length 9001 exceeds max length (4096). Truncating context.\n"
    runtime, contract = P.scan_run_output(log)
    assert runtime == []
    assert contract, "hidden truncation must be a hard protocol failure"
    assert "hidden truncation" in contract[0]


def test_a_failed_run_cannot_be_promotable_even_with_full_coverage():
    receipt = P.build_receipt(
        vllm_config(),
        Path(__file__),
        outcome="fail",
        promotable=True,
        harness=fake_harness_block(),
        dataset=P.dataset_identity_block(DATASET_REV),
        backend={"name": "vllm"},
        argv=[],
        adaptation=fake_adaptation(),
        outputs={"resultsDir": "/tmp/x", "files": []},
        coverage={
            "expectedSubtasks": 67, "observedSubtasks": 67, "missing": [],
            "unexpected": [], "complete": True, "rowsPerSubtask": {},
            "reducedEffectiveCountTasks": [],
        },
        aggregate=None,
        per_subtask_acc={name: 0.0 for name in PINNED_SUBTASKS},
        gate_results={},
        runtime_errors=[{"kind": "missing_logprobs", "message": "no logprobs"}],
        errors=[],
        notes=[],
        failure_reason="missing_logprobs",
    )
    # build_receipt demotes a run that recorded any error, and every subtask
    # reads 0.0 here, which is exactly the laundering this lane forbids.
    assert receipt["promotable"] is False
    assert receipt["runtimeErrors"][0]["kind"] == "missing_logprobs"


def test_recorded_contract_error_demotes_a_promotable_receipt():
    receipt = P.build_receipt(
        vllm_config(),
        Path(__file__),
        outcome="pass",
        promotable=True,
        harness=fake_harness_block(),
        dataset=P.dataset_identity_block(DATASET_REV),
        backend={"name": "vllm"},
        argv=[],
        adaptation=fake_adaptation(),
        outputs={"resultsDir": "/tmp/x", "files": []},
        coverage={
            "expectedSubtasks": 67, "observedSubtasks": 67, "missing": [],
            "unexpected": [], "complete": True, "rowsPerSubtask": {},
            "reducedEffectiveCountTasks": [],
        },
        aggregate=None,
        per_subtask_acc={},
        gate_results={},
        runtime_errors=[],
        errors=[{
            "gate": "chat_template_off",
            "code": "apply_chat_template_in_config",
            "detail": "a chat template was applied",
        }],
        notes=[],
        failure_reason="apply_chat_template_in_config",
    )
    assert receipt["promotable"] is False


def test_nonzero_exit_is_a_failure_not_an_accuracy():
    runtime, contract = P.scan_run_output("RuntimeError: CUDA out of memory.\n")
    assert [r["kind"] for r in runtime] == ["cuda_oom"]
    assert contract == []


def test_receipt_schema_rejects_a_malformed_receipt():
    assert P.validate_receipt_document(
        {"schema": "native-blimp-receipt-1", "laneId": "native-blimp"}
    )


def test_clean_run_receipt_validates_against_its_schema():
    receipt = P.build_receipt(
        vllm_config(),
        Path(__file__),
        outcome="pass",
        promotable=True,
        harness=fake_harness_block(),
        dataset=P.dataset_identity_block(DATASET_REV),
        backend={"name": "vllm", "harnessModelArg": "vllm", "modelArgs": {},
                 "modelArgsRendered": ""},
        argv=["python", "-m", "lm_eval", "--model", "vllm"],
        adaptation=fake_adaptation(),
        outputs={
            "resultsDir": "/tmp/x",
            "files": [],
            "harnessResultsSha256": "cd" * 32,
        },
        coverage={
            "expectedSubtasks": 67, "observedSubtasks": 67, "missing": [],
            "unexpected": [], "complete": True, "rowsPerSubtask": {},
            "reducedEffectiveCountTasks": [],
        },
        aggregate={
            "harnessGroupAcc": 0.62,
            "recomputedUnweightedMeanAcc": 0.62,
            "absoluteDifference": 0.0,
            "matches": True,
            "aggregation": "mean",
            "weightBySize": False,
        },
        per_subtask_acc={name: 0.62 for name in PINNED_SUBTASKS},
        gate_results={"task_identity": {"status": "pass", "detail": "67/67"}},
        runtime_errors=[],
        errors=[],
        notes=[],
        failure_reason=None,
    )
    receipt["model"] = {
        "repo": "Qwen/Qwen3.5-2B",
        "revision": "15852e8c16360a2fea060d615a32b45270f8a8fc",
        "tokenizer": "Qwen/Qwen3.5-2B",
    }
    receipt["exitCode"] = 0
    assert P.validate_receipt_document(receipt) == []
    assert receipt["promotable"] is True


# --------------------------------------------------------------------------
# Lane separation and CLI smoke
# --------------------------------------------------------------------------


def test_lane_is_separate_from_prompted_blimp():
    protocol = P.load_protocol()
    assert protocol["laneId"] == "native-blimp"
    separation = protocol["laneSeparation"]
    assert "public-fast" in separation["promptedLane"]
    assert "never averaged" in separation["rule"]
    for name in ("native-blimp-protocol.json",
                 "native-blimp-config.schema.json",
                 "native-blimp-receipt.schema.json",
                 "native_blimp_protocol.py",
                 "run_native_blimp.py",
                 "test_native_blimp.py"):
        assert (HERE / name).is_file(), name
    # The lane's production code must not reach into the prompted BLiMP
    # artifacts. This is the check that keeps the two evidence lanes from
    # quietly merging.
    prompted_artifacts = (
        "score-" + "english-core-public-fast.py",
        "build-" + "english-core-public-fast.py",
        "english-core-" + "public-anchors.json",
    )
    for name in ("native_blimp_protocol.py", "run_native_blimp.py"):
        source = (HERE / name).read_text()
        for forbidden in prompted_artifacts:
            assert forbidden not in source, name + " references " + forbidden
    # And the lane must not have created or touched any prompted output.
    assert not (HERE / "english-core-public-fast").exists()


def test_config_schema_rejects_a_prompted_lane_config():
    config = vllm_config()
    config["laneId"] = "prompted-blimp"
    expect_protocol_error("config_schema_violation", P.validate_config_document, config)
    other = vllm_config()
    other["schema"] = "english-core-config-1"
    expect_protocol_error("config_schema_violation", P.validate_config_document, other)


def test_module_cli_check_harness_against_the_real_checkout():
    if not HAS_REAL_CHECKOUT:
        print("  (skipped: no pinned harness checkout available)")
        return
    completed = subprocess.run(
        [sys.executable, str(HERE / "native_blimp_protocol.py"),
         "check-harness", "--checkout", str(CHECKOUT)],
        capture_output=True, text=True, cwd=str(HERE),
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["allIdentitiesMatch"] is True
    assert payload["problems"] == []


def test_runner_plan_cli_prints_the_frozen_argv():
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.json"
        config_path.write_text(json.dumps(vllm_config(), indent=2))
        completed = subprocess.run(
            [sys.executable, str(HERE / "run_native_blimp.py"), "plan",
             "--config", str(config_path), "--checkout", str(CHECKOUT)],
            capture_output=True, text=True, cwd=str(HERE),
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        payload = json.loads(completed.stdout)
        assert payload["laneId"] == "native-blimp"
        assert payload["promotable"] is True
        joined = " ".join(payload["argv"])
        assert "--apply_chat_template" not in joined
        assert "--limit" not in joined
        assert payload["warnings"] == []


def test_runner_refuses_a_smoke_run_marked_promotable():
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.json"
        bad = vllm_config(mode="smoke", promotable=True, smokeLimit=2)
        config_path.write_text(json.dumps(bad, indent=2))
        completed = subprocess.run(
            [sys.executable, str(HERE / "run_native_blimp.py"), "plan",
             "--config", str(config_path), "--checkout", str(CHECKOUT)],
            capture_output=True, text=True, cwd=str(HERE),
        )
        assert completed.returncode != 0
        assert "smoke_marked_promotable" in completed.stderr


def test_runner_writes_a_non_promotable_receipt_when_identity_fails():
    """A failed run still gets a receipt; it just cannot be evidence."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        results = root / "results"
        results.mkdir()
        # A checkout that is not the pinned commit, with no task directory.
        fake = root / "harness"
        (fake / "lm_eval/tasks/blimp").mkdir(parents=True)
        config = vllm_config(mode="smoke", promotable=False, smokeLimit=2)
        config["outputs"]["resultsDir"] = str(results)
        config_path = root / "config.json"
        config_path.write_text(json.dumps(config, indent=2))
        completed = subprocess.run(
            [sys.executable, str(HERE / "run_native_blimp.py"), "execute",
             "--config", str(config_path), "--checkout", str(fake),
             "--offline", "--results-dir", str(results)],
            capture_output=True, text=True, cwd=str(HERE),
        )
        assert completed.returncode == 1, completed.stdout + completed.stderr
        receipt_path = results / "native-blimp-receipt.json"
        assert receipt_path.is_file(), "a failed run must still write a receipt"
        receipt = json.loads(receipt_path.read_text())
        assert receipt["outcome"] == "fail"
        assert receipt["promotable"] is False
        assert P.validate_receipt_document(receipt) == []
        codes = {e["code"] for e in receipt["errors"]}
        assert "harness_identity_mismatch" in codes
        assert "dataset_revision_mismatch" in codes
        assert receipt["gateResults"]["harness_identity"]["status"] == "fail"
        assert receipt["gateResults"]["dataset_revision"]["status"] == "fail"


def test_runner_verify_rejects_a_drifted_harness_output():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        results = root / "results"
        results.mkdir()
        results_file = results / "results_2026-10-03T00-00-00.json"
        results_file.write_text(json.dumps(synthetic_results(), indent=2))
        config = vllm_config()
        config["outputs"]["resultsDir"] = str(results)
        config_path = root / "config.json"
        config_path.write_text(json.dumps(config, indent=2))
        receipt = P.build_receipt(
            config,
            config_path,
            outcome="pass",
            promotable=True,
            harness=fake_harness_block(),
            dataset=P.dataset_identity_block(DATASET_REV),
            backend={"name": "vllm", "harnessModelArg": "vllm", "modelArgs": {},
                     "modelArgsRendered": ""},
            argv=["python", "-m", "lm_eval"],
            adaptation=fake_adaptation(),
            outputs={
                "resultsDir": str(results),
                "files": P.collect_output_files(results),
                "harnessResultsSha256": P.sha256_file(results_file),
            },
            coverage={
                "expectedSubtasks": 67, "observedSubtasks": 67, "missing": [],
                "unexpected": [], "complete": True, "rowsPerSubtask": {},
                "reducedEffectiveCountTasks": [],
            },
            aggregate={
                "harnessGroupAcc": 0.62, "recomputedUnweightedMeanAcc": 0.62,
                "absoluteDifference": 0.0, "matches": True,
                "aggregation": "mean", "weightBySize": False,
            },
            per_subtask_acc={name: 0.62 for name in PINNED_SUBTASKS},
            gate_results={"task_identity": {"status": "pass", "detail": "67/67"}},
            runtime_errors=[],
            errors=[],
            notes=[],
            failure_reason=None,
        )
        receipt["model"] = {
            "repo": "Qwen/Qwen3.5-2B",
            "revision": "15852e8c16360a2fea060d615a32b45270f8a8fc",
            "tokenizer": "Qwen/Qwen3.5-2B",
        }
        receipt["exitCode"] = 0
        receipt_path = root / "receipt.json"
        P.write_json_atomic(receipt_path, receipt)

        clean = subprocess.run(
            [sys.executable, str(HERE / "run_native_blimp.py"), "verify",
             "--receipt", str(receipt_path)],
            capture_output=True, text=True, cwd=str(HERE),
        )
        assert clean.returncode == 0, clean.stdout + clean.stderr
        report = json.loads(clean.stdout)
        assert report["ok"] is True
        assert report["checks"]["harnessOutputHash"]["status"] == "pass"

        # Now drift the harness output and prove verify catches it.
        results_file.write_text(json.dumps(synthetic_results(acc=0.61), indent=2))
        drifted = subprocess.run(
            [sys.executable, str(HERE / "run_native_blimp.py"), "verify",
             "--receipt", str(receipt_path)],
            capture_output=True, text=True, cwd=str(HERE),
        )
        assert drifted.returncode == 1
        report = json.loads(drifted.stdout)
        assert report["ok"] is False
        assert report["checks"]["harnessOutputHash"]["status"] == "fail"


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_")
    ]
    for test in tests:
        test()
        print("ok " + test.__name__)
    print("Native BLiMP lane tests passed (%d cases)." % len(tests))


if __name__ == "__main__":
    main()
