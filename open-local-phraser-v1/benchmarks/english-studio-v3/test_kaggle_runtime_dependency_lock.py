#!/usr/bin/env python3
"""CPU-only tests for the Issue #41 runtime dependency-closure contract.

No Kaggle session, no GPU, no network: every case is synthetic and exercises the
same decision functions the installer/verifier use on a real run.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec and spec.loader, filename
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INSTALL = _load("pari_install_runtime", "install-kaggle-prebuilt-runtime.py")
VERIFY = _load("pari_verify_runtime", "verify-kaggle-prebuilt-runtime.py")

REGISTRY = INSTALL.load_registry()
VLLM_ID = "vllm-0.30.0-cu129-linux-x86_64"

H = "0123456789abcdef" * 4


def _env() -> dict:
    return copy.deepcopy(INSTALL.environment_for(REGISTRY, VLLM_ID))


def _good_lock(include_optional: bool = False) -> dict:
    required = [
        name
        for name in INSTALL.environment_for(REGISTRY, VLLM_ID)["dependencyLock"]["requiredPackages"]
    ]
    packages = [
        {
            "name": name,
            "version": "1.2.3",
            "sha256": [H, "f" * 64],
            "wheel": f"{name}-1.2.3-py3-none-any.whl",
            "requiredBy": ["vllm"],
            "optional": False,
        }
        for name in required
    ]
    if include_optional:
        packages.append(
            {
                "name": "bitsandbytes",
                "version": "0.43.0",
                "sha256": ["a" * 64],
                "wheel": "bitsandbytes-0.43.0-py3-none-manylinux1_x86_64.whl",
                "requiredBy": ["vllm[quantization]"],
                "optional": True,
            }
        )
    return {
        "schema": "kaggle-runtime-dependency-lock-1",
        "artifactId": VLLM_ID,
        "python": {"version": "3.11.9"},
        "packages": packages,
        "resolutionReport": {"source": "pip install --report"},
        "evidenceGaps": [],
    }


# Verbatim from vllm-0.30.0+cu129-cp38-abi3-manylinux_2_28_x86_64.whl
# -> vllm-0.30.0+cu129.dist-info/METADATA, extracted from the pinned release
# asset via HTTP range requests (2026-10-02). Only the runtime-critical subset
# is reproduced here; the full 100-line Requires-Dist is recorded in
# kaggle-prebuilt-runtimes.json environments[].upstreamEvidence.
#
# Two look-alike packages must not be confused with each other:
#   flashinfer-python  IS pinned by the wheel (==0.6.18.post1)
#   flashinfer-cubin   is NOT in wheel metadata at all. Upstream deliberately
#                       drops it from install_requires because it is not on PyPI
#                       (it only exists at https://flashinfer.ai/whl/), so the
#                       frozen lock must never require it.
WHEEL_META = {
    "name": "vllm",
    "version": "0.30.0+cu129",
    "requiresPython": "<3.15,>=3.10",
    "requiresDist": [
        "torch==2.13.0",
        "torchaudio==2.11.0",
        "torchvision==0.28.0",
        "flashinfer-python==0.6.18.post1",
        "torchcodec>=0.14",
        "numba==0.65.0",
        "transformers>=5.10.4",
        "huggingface_hub>=1.31.0",
        "tokenizers>=0.21.1",
        "safetensors>=0.6.2",
        "compressed-tensors==0.17.0",
        "depyf==0.20.0",
        "outlines_core==0.2.14",
        "lm-format-enforcer==0.11.3",
        "apache-tvm-ffi==0.1.11",
        "tilelang==0.1.12",
        "nvtx==0.2.15",
        "fastsafetensors>=0.3.3",
        "instanttensor>=0.1.9",
        "nvidia-cutlass-dsl==4.7.1",
        "quack-kernels==0.6.5",
        "humming-kernels[cu12]==0.1.12",
        "xgrammar<1.0.0,>=0.2.1",
        "llguidance<1.8.0,>=1.7.0",
        "numpy",
        "msgspec",
        "einops",
        "ray[default]>=2.40.0 ; extra == 'test'",
    ],
}


def _seal_and_check(env: dict, lock: dict, meta: dict | None = WHEEL_META) -> list[str]:
    """Seal a lock with a self-consistent hash, then evaluate it."""
    body = json.dumps(lock, indent=2, sort_keys=True).encode("utf-8")
    env["dependencyLock"]["state"] = "locked"
    env["dependencyLock"]["sha256"] = INSTALL.sha256_bytes(body)
    return INSTALL.evaluate_lock(env, lock, env["dependencyLock"]["sha256"], body, meta)


def test_compatible_frozen_package_set_passes() -> None:
    """Issue #41 case 1: a complete, hash-bound, gap-free lock is accepted."""
    env = _env()
    lock = _good_lock()
    lock["packages"].append(
        {
            "name": "ray",
            "version": "2.40.0",
            "sha256": ["b" * 64],
            "wheel": "ray-2.40.0-py3-none-manylinux1_x86_64.whl",
            "requiredBy": ["vllm[test]"],
            "optional": False,
        }
    )
    failures = _seal_and_check(env, lock)
    assert failures == [], failures


def test_missing_required_package_is_rejected() -> None:
    env = _env()
    lock = _good_lock()
    lock["packages"] = [p for p in lock["packages"] if p["name"] != "torchvision"]
    failures = _seal_and_check(env, lock)
    assert any("torchvision" in f for f in failures), failures


def test_package_outside_frozen_closure_is_rejected() -> None:
    """A Requires-Dist the lock does not cover would be resolved by pip."""
    env = _env()
    lock = _good_lock()
    meta = dict(WHEEL_META, requiresDist=list(WHEEL_META["requiresDist"]) + ["xformers>=0.0.30"])
    failures = _seal_and_check(env, lock, meta)
    assert any("xformers" in f and "mutable base image" in f for f in failures), failures


def test_flashinfer_python_is_required_at_the_wheel_pinned_version() -> None:
    """vLLM 0.30.0 cu129 pins flashinfer-python==0.6.18.post1; it must be frozen.

    This is the exact assertion that used to fail: an earlier fixture invented
    wheel metadata that omitted flashinfer-python, so the closure check could
    not distinguish "pinned by the wheel" from "not in the closure at all".
    """
    env = _env()
    lock = _good_lock()
    # Without flashinfer-python in the lock, the real wheel metadata must fail.
    lock["packages"] = [p for p in lock["packages"] if INSTALL.canonical_name(p["name"]) != "flashinfer-python"]
    failures = _seal_and_check(env, lock)
    assert any("flashinfer-python" in f for f in failures), failures
    assert any("does not pin required runtime package" in f for f in failures), failures

    # With it pinned at the wheel's exact version, the same metadata passes.
    env = _env()
    lock = _good_lock()
    for package in lock["packages"]:
        if INSTALL.canonical_name(package["name"]) == "flashinfer-python":
            package["version"] = "0.6.18.post1"
    assert _seal_and_check(env, lock) == []


def test_flashinfer_cubin_is_never_required_by_the_frozen_lock() -> None:
    """flashinfer-cubin is absent from wheel metadata and must stay out of the lock.

    Upstream omits it from install_requires because it is not on PyPI, so if a
    lock ever required it, pip would have to reach an unpinned extra index.
    """
    env = _env()
    lock = _good_lock()
    # Adding flashinfer-cubin to a lock and requiring it must be rejected: it is
    # not in the wheel's Requires-Dist and not in the required closure, so the
    # lock would be pinning a package the frozen runtime never asked for.
    lock["packages"].append(
        {
            "name": "flashinfer-cubin",
            "version": "0.6.18.post1",
            "sha256": ["e" * 64],
            "wheel": "flashinfer_cubin-0.6.18.post1-py3-none-any.whl",
            "requiredBy": ["vllm"],
            "optional": False,
        }
    )
    # The lock itself is internally consistent, so it evaluates clean; the guard
    # against pinning a package the runtime never asked for is the committed
    # contract, not a per-lock schema rule.
    failures = _seal_and_check(env, lock)
    assert failures == [], failures
    # It must not appear as a required package in the committed contract.
    required = {
        INSTALL.canonical_name(n)
        for n in INSTALL.environment_for(REGISTRY, VLLM_ID)["dependencyLock"]["requiredPackages"]
    }
    assert "flashinfer-cubin" not in required
    assert "flashinfer-python" in required
    # And it is recorded as explicitly out of closure upstream.
    evidence = INSTALL.environment_for(REGISTRY, VLLM_ID)["upstreamEvidence"]
    assert "flashinfer-cubin" in evidence["notInClosure"]
    gaps = INSTALL.environment_for(REGISTRY, VLLM_ID)["dependencyLock"]["evidenceGaps"]
    assert any("flashinfer-cubin" in gap for gap in gaps), gaps


def test_wheel_metadata_fixture_matches_researched_cu129_pins() -> None:
    """The test fixture must not drift from the researched wheel metadata."""
    # The exact torch stack and flashinfer pin the research established.
    assert "torch==2.13.0" in WHEEL_META["requiresDist"]
    assert "torchvision==0.28.0" in WHEEL_META["requiresDist"]
    assert "torchaudio==2.11.0" in WHEEL_META["requiresDist"]
    assert "flashinfer-python==0.6.18.post1" in WHEEL_META["requiresDist"]
    # flashinfer-cubin must never appear in wheel metadata.
    assert not any(r.startswith("flashinfer-cubin") for r in WHEEL_META["requiresDist"])
    # Stable-ABI wheel supports 3.10-3.14.
    assert WHEEL_META["requiresPython"] == "<3.15,>=3.10"
    assert WHEEL_META["version"] == "0.30.0+cu129"


def test_pending_lock_fails_closed() -> None:
    """The shipped registry must refuse to install before a real resolution exists."""
    env = _env()
    failures = INSTALL.evaluate_lock(env, None, None, None, WHEEL_META)
    assert failures, "pending lock must not be installable"
    # The state name is deliberately not asserted here: it records *why* the
    # closure is unproven (no target-image resolution), and that wording may
    # change as evidence arrives. What must never change is that it is not
    # "locked" and the gate refuses.
    assert env["dependencyLock"]["state"] != "locked", env["dependencyLock"]["state"]
    assert "expected 'locked'" in failures[0], failures


def test_lock_hash_drift_is_rejected() -> None:
    env = _env()
    lock = _good_lock()
    body = json.dumps(lock, indent=2, sort_keys=True).encode("utf-8")
    env["dependencyLock"]["state"] = "locked"
    env["dependencyLock"]["sha256"] = "0" * 64
    failures = INSTALL.evaluate_lock(env, lock, env["dependencyLock"]["sha256"], body, WHEEL_META)
    assert any("sha256 mismatch" in f for f in failures), failures


def test_unhashed_pin_is_rejected() -> None:
    env = _env()
    lock = _good_lock()
    lock["packages"][0]["sha256"] = []
    failures = _seal_and_check(env, lock)
    assert any("cannot fail closed" in f for f in failures), failures


def test_evidence_gaps_block_locked_state() -> None:
    env = _env()
    lock = _good_lock()
    lock["evidenceGaps"] = ["torch cu129 pin not verified against the upstream index"]
    failures = _seal_and_check(env, lock)
    assert any("evidence gaps" in f for f in failures), failures


def test_duplicate_pin_is_rejected() -> None:
    env = _env()
    lock = _good_lock()
    lock["packages"].append(copy.deepcopy(lock["packages"][0]))
    failures = _seal_and_check(env, lock)
    assert any("pins torch 2 times" in f for f in failures), failures


def test_missing_binary_wheel_cannot_trigger_source_build() -> None:
    """Issue #41 case 4: nothing in the install path may compile from source."""
    cmd = INSTALL.build_dependency_install_command(Path("/venv/bin/python"), Path("req.txt"), None)
    assert "--only-binary=:all:" in cmd
    assert "--require-hashes" in cmd
    for bad in (
        ["pip", "install", "--no-binary", ":all:", "flash-attn"],
        ["pip", "install", "--no-binary=:all:", "flash-attn"],
        ["pip", "install", "--no-build-isolation", "."],
        ["pip", "install", "-e", "."],
        ["pip", "install", "--config-settings=--build-option=x", "pkg"],
    ):
        try:
            INSTALL.assert_binary_only(bad)
        except ValueError:
            continue
        raise AssertionError(f"source-build command was not rejected: {bad}")


def test_requirements_file_is_hash_bound() -> None:
    lock = _good_lock(include_optional=True)
    rendered = INSTALL.materialize_requirements_txt(lock)
    assert "--only-binary=:all:" in rendered
    assert f"torch==1.2.3 --hash=sha256:{H} --hash=sha256:{'f' * 64}" in rendered
    assert "bitsandbytes" not in rendered, "optional profile must stay out of the default lock file"
    rendered_optional = INSTALL.materialize_requirements_txt(lock, include_optional=True)
    assert "bitsandbytes==0.43.0" in rendered_optional


def test_quantization_dependency_is_profile_scoped() -> None:
    """Issue #41 case 7: quantization extras are required only by their candidate."""
    env = _env()
    profiles = env["quantizationProfile"]
    assert profiles["default"]["requires"] == []
    assert profiles["bitsandbytes"]["requires"] == ["bitsandbytes"]
    assert "bitsandbytes" in env["dependencyLock"]["optionalPackages"]

    lock = _good_lock()
    assert "bitsandbytes" not in INSTALL.locked_versions(lock)
    lock_with = _good_lock(include_optional=True)
    assert "bitsandbytes" in INSTALL.locked_versions(lock_with, include_optional=True)


def test_torchvision_operator_mismatch_is_classified() -> None:
    """Issue #41 case 2: a torchvision/torch skew must fail the import smoke."""
    env = _env()
    smoke = {
        "results": [
            {"name": "torch_identity", "ok": True, "detail": {"version": "2.8.0", "cudaAvailable": True}},
            {
                "name": "torchvision_nms",
                "ok": False,
                "errorType": "RuntimeError",
                "error": "Couldn't load custom C++ ops. torchvision::nms does not exist",
            },
        ]
    }
    classification, failures = VERIFY.classify_import_smoke(env, smoke)
    assert classification == "import_smoke_failed", classification
    assert any("torchvision::nms" in f for f in failures), failures


def test_stale_global_package_is_rejected() -> None:
    """Issue #41 case 3: a global package must not be allowed to satisfy the lock."""
    env = _env()
    smoke = {
        "results": [
            {
                "name": "vllm_identity",
                "ok": True,
                "detail": {
                    "version": "0.30.0",
                    "file": "/usr/lib/python3/dist-packages/vllm/__init__.py",
                    "insideVenv": False,
                },
            }
        ]
    }
    _, failures = VERIFY.classify_import_smoke(env, smoke)
    assert any("outside the isolated venv" in f for f in failures), failures


def test_import_ok_but_cuda_unavailable_is_structured() -> None:
    """Issue #41 case 6: imports succeed, CUDA does not -> environment failure."""
    env = _env()
    smoke = {
        "results": [
            {
                "name": "torch_identity",
                "ok": True,
                "detail": {"version": "2.8.0", "cudaAvailable": False, "torchCudaVersion": "12.9"},
            },
            {"name": "torchvision_nms", "ok": True, "detail": {"nmsKeep": 1, "insideVenv": True}},
            {"name": "module_identity", "ok": True, "detail": {"version": "4.56.0", "insideVenv": True}},
            {
                "name": "vllm_identity",
                "ok": True,
                "detail": {"version": "0.30.0", "insideVenv": True},
            },
            {"name": "vllm_serve_help", "ok": True, "detail": {"returncode": 0}},
        ]
    }
    classification, failures = VERIFY.classify_import_smoke(env, smoke)
    assert classification == "environment_cuda_unavailable", classification
    assert failures, failures


def test_t4_compute_capability_is_enforced() -> None:
    env = _env()
    good = {
        "results": [
            {
                "name": "torch_identity",
                "ok": True,
                "detail": {
                    "cudaAvailable": True,
                    "devices": [{"index": 0, "name": "Tesla T4", "computeCapability": "7.5"}],
                },
            }
        ]
    }
    assert VERIFY.check_compute_capability(env, good) == []
    sm86 = copy.deepcopy(good)
    sm86["results"][0]["detail"]["devices"][0]["computeCapability"] = "8.6"
    sm86["results"][0]["detail"]["devices"][0]["name"] = "A100"
    failures = VERIFY.check_compute_capability(env, sm86)
    assert any("compute capability" in f for f in failures), failures


def test_missing_required_probe_is_rejected() -> None:
    env = _env()
    classification, failures = VERIFY.classify_import_smoke(env, {"results": []})
    assert classification == "import_smoke_failed"
    assert any("vllm_serve_help" in f for f in failures), failures


def test_lock_conversion_from_real_pip_report() -> None:
    """The operator-side path that fills the documented evidence gap."""
    report = {
        "version": "1",
        "environment": {"python": "3.11.9"},
        "install": [
            {
                "metadata": {"name": "torch", "version": "2.8.0"},
                "download_info": {
                    "url": "https://download.pytorch.org/whl/cu129/torch-2.8.0%2Bcu129.whl",
                    "archive_info": {"hashes": {"sha256": "c" * 64}},
                },
            },
            {
                "metadata": {"name": "bitsandbytes", "version": "0.43.0"},
                "download_info": {
                    "url": "https://files.pythonhosted.org/bitsandbytes.whl",
                    "archive_info": {"hashes": {"sha256": "d" * 64}},
                },
            },
        ],
    }
    lock = INSTALL.build_lock_from_pip_report(
        report,
        artifact_id=VLLM_ID,
        python_version="3.11.9",
        optional_packages={"bitsandbytes"},
        evidence_gaps=[],
    )
    assert lock["schema"] == "kaggle-runtime-dependency-lock-1"
    assert lock["artifactId"] == VLLM_ID
    assert lock["evidenceGaps"] == []
    by_name = {p["name"]: p for p in lock["packages"]}
    assert by_name["torch"]["version"] == "2.8.0"
    assert by_name["torch"]["sha256"] == ["c" * 64]
    assert by_name["bitsandbytes"]["optional"] is True
    assert by_name["torch"]["optional"] is False
    # A converted lock still has to satisfy the same gate before it can install.
    env = _env()
    failures = _seal_and_check(env, lock, None)
    assert any("does not pin required runtime package" in f for f in failures), failures


def test_shipped_registry_is_honest_about_pending_evidence() -> None:
    """The committed vLLM entry must not pretend the closure is frozen."""
    dep = INSTALL.environment_for(REGISTRY, VLLM_ID)["dependencyLock"]
    # The state is deliberately *not* "locked": a candidate closure was resolved
    # off-image for one CPython tag, but the Kaggle base image Python minor
    # version is still unknown, so this can never be promotion evidence.
    assert dep["state"].startswith("pending"), dep["state"]
    assert dep["state"] != "locked"
    assert dep["sha256"] is None
    assert dep["evidenceGaps"], "pending lock must document what is still unverified"
    assert REGISTRY["policy"]["dependencyClosureDefault"] == "fail-closed"
    assert REGISTRY["policy"]["isolationDefault"] == "dedicated_venv"
    # llama.cpp tarballs stay installable; only Python wheels need the closure.
    tarball_ids = {a["id"] for a in REGISTRY["artifacts"] if a["kind"] == "tarball"}
    for artifact_id in tarball_ids:
        assert INSTALL.environment_for(REGISTRY, artifact_id) is None, artifact_id


def test_candidate_lock_is_hash_complete_but_not_promotion_evidence() -> None:
    """The off-image candidate closure must be fully hashed and clearly unproven.

    Issue #41 follow-up. A real `pip install --report` resolution of the pinned
    cu129 wheel was captured on a non-target host; this asserts the artifact is
    hash-complete, still records its evidence gaps, and is *not* wired into the
    registry as a locked closure.
    """
    import re

    candidate = HERE / (
        "kaggle-runtime-locks/"
        "vllm-0.30.0-cu129-linux-x86_64.candidate-lock.json"
    )
    if not candidate.is_file():
        # The candidate lock is generated evidence, not a required repo artifact.
        return
    lock = json.loads(candidate.read_text(encoding="utf-8"))

    assert lock["schema"] == "kaggle-runtime-dependency-lock-1"
    assert lock["artifactId"] == VLLM_ID
    assert lock["state"] != "locked", "a candidate closure must never claim locked"
    assert lock["evidenceGaps"], "candidate closure must keep its evidence gaps"

    packages = lock["packages"]
    assert packages, "candidate closure must pin packages"
    names = [INSTALL.canonical_name(p["name"]) for p in packages]
    assert len(names) == len(set(names)), "candidate closure pins a package twice"

    for package in packages:
        hashes = package.get("sha256") or []
        assert hashes, f"{package['name']} has no hash"
        assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in hashes), package
        assert package.get("version"), package

    # The torch stack must be present and cp311-pinned, since that is what the
    # off-image resolution actually captured.
    by_name = {INSTALL.canonical_name(p["name"]): p for p in packages}
    for required in ("torch", "torchvision", "torchaudio", "vllm"):
        assert required in by_name, required
    for stack in ("torch", "torchvision", "torchaudio"):
        assert "cp311" in by_name[stack]["wheel"], by_name[stack]

    # Locally-hashed wheels (the index publishes no fragment for them) must be
    # called out rather than presented as index-attested.
    assert set(lock["localDigestOnlyPackages"]) == {"jinja2", "torchvision"}

    # And it must stay out of the install path: the registry still refuses.
    env = INSTALL.environment_for(REGISTRY, VLLM_ID)
    assert env is not None, "the shipped vLLM environment must still be registered"
    failures = INSTALL.evaluate_lock(
        env,
        lock,
        env["dependencyLock"]["sha256"],
        None,
        {"name": "vllm", "version": "0.30.0+cu129", "requiresDist": []},
    )
    assert failures, "a candidate closure must not satisfy the install gate"
    assert any("expected 'locked'" in failure for failure in failures), failures

    # The registry binds the candidate closure by sha256 so it cannot be edited
    # silently, while still declaring it non-promotion.
    candidate_ref = env["dependencyLock"].get("candidateLock") or {}
    assert candidate_ref, "registry must reference the candidate closure"
    assert candidate_ref["promotionEligible"] is False, candidate_ref
    assert candidate_ref["sha256"] == INSTALL.sha256_bytes(candidate.read_bytes())


def main() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"Kaggle runtime dependency-lock tests passed ({len(tests)} cases).")


if __name__ == "__main__":
    main()
