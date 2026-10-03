#!/usr/bin/env python3
"""Focused checks for the CPU benchmark data-preparation dependency lock.

Runs on a bare base Python with no third-party packages: the builder resolves
its requirement parser from pip, and this suite substitutes a deliberately
narrow pin-only parser when the host interpreter ships without pip, so the
lock gate stays runnable without installing anything. See
`requirement_parser_provenance` for which parser actually executed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
from unittest.mock import patch
import re


PINNED_REQUIREMENT = re.compile(
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[A-Za-z0-9][A-Za-z0-9._+!-]*)"
)


class NarrowPinnedSpecifier:
    """The single `==version` specifier of a pinned requirement."""

    def __init__(self, text: str) -> None:
        self._text = text

    def __str__(self) -> str:
        return self._text

    def __len__(self) -> int:
        return 1


class NarrowPinnedRequirement:
    """Stand-in for pip's `Requirement`, limited to the committed lock grammar.

    The committed data-preparation locks contain only `name==version` pins with
    `--hash=` continuation lines. Anything richer -- extras, environment
    markers, ranges, several specifiers, a bare name -- is rejected instead of
    guessed, so a lock that outgrows this parser fails closed here rather than
    being silently accepted under a weaker grammar than the builder would use
    on a machine that has pip.
    """

    def __init__(self, requirement_text: str) -> None:
        match = PINNED_REQUIREMENT.fullmatch(requirement_text.strip())
        if not match:
            raise ValueError(
                "the narrow fallback parser accepts only an exact 'name==version' "
                f"pin, got {requirement_text!r}"
            )
        self.name = match.group("name")
        self.marker = None
        self.specifier = NarrowPinnedSpecifier(f"=={match.group('version')}")


def vendored_requirement_parser():
    """Return pip's vendored `Requirement`, or None when it is unavailable."""
    try:
        from pip._vendor.packaging.requirements import Requirement
    except Exception:
        return None
    return Requirement


def install_requirement_parser_fallback() -> str:
    """Make `from pip._vendor.packaging.requirements import Requirement` resolve.

    Returns a short provenance label naming the parser the builder will now use.
    On an interpreter that has pip, nothing is patched and the real parser runs.
    """
    if vendored_requirement_parser() is not None:
        return "pip vendored Requirement"
    requirements = types.ModuleType("pip._vendor.packaging.requirements")
    requirements.Requirement = NarrowPinnedRequirement  # type: ignore[attr-defined]
    for name in ("pip", "pip._vendor", "pip._vendor.packaging"):
        package = types.ModuleType(name)
        package.__path__ = []  # type: ignore[attr-defined]
        sys.modules[name] = package
    sys.modules["pip._vendor.packaging"].requirements = requirements  # type: ignore[attr-defined]
    sys.modules["pip._vendor.packaging.requirements"] = requirements
    return "narrow pinned-requirement fallback"


# Must happen before any test calls into the builder, which imports its parser
# lazily inside verify_data_prep_lock().
REQUIREMENT_PARSER = install_requirement_parser_fallback()


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("prepare_kaggle_benchmark", HERE / "prepare-kaggle-benchmark.py")
assert SPEC and SPEC.loader
PREP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREP)
VERIFY_SPEC = importlib.util.spec_from_file_location("verify_kaggle_benchmark_preparation", HERE / "verify-kaggle-benchmark-preparation.py")
assert VERIFY_SPEC and VERIFY_SPEC.loader
VERIFY = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(VERIFY)


def test_committed_lock_is_hash_pinned_and_contains_dataset_closure() -> None:
    for version in ((3, 10), (3, 11)):
        lock_file, digest_file = PREP.data_prep_lock_paths(
            system="Linux", machine="x86_64", python_version=version
        )
        digest, pins = PREP.verify_data_prep_lock(lock_file, digest_file)
        assert len(digest) == 64
        versions = dict(pins)
        assert versions["datasets"] == PREP.DATASETS_VERSION
        assert versions["huggingface-hub"]
        assert len(pins) >= 30

        lines = lock_file.read_text(encoding="utf-8").splitlines()
        assert sum(line.count("--hash=sha256:") for line in lines) >= len(pins)
        assert all(re.match(r"\s+--hash=sha256:[0-9a-f]{64}", line) for line in lines if "--hash=" in line)


def test_lock_change_fails_before_environment_creation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        lock = root / "requirements.txt"
        pin = root / "requirements.sha256"
        lock.write_text("datasets==5.0.1 \\\n    --hash=sha256:" + "0" * 64 + "\n", encoding="utf-8")
        pin.write_text(hashlib.sha256(lock.read_bytes()).hexdigest() + "\n", encoding="ascii")
        digest, packages = PREP.verify_data_prep_lock(lock, pin)
        assert digest == hashlib.sha256(lock.read_bytes()).hexdigest()
        assert packages == [("datasets", "5.0.1")]

        lock.write_text(lock.read_text(encoding="utf-8") + "# changed\n", encoding="utf-8")
        try:
            PREP.verify_data_prep_lock(lock, pin)
        except SystemExit as exc:
            assert "SHA-256 mismatch" in str(exc)
        else:
            raise AssertionError("modified lock was not rejected")


def test_prep_subprocess_environment_strips_host_python_and_pip_overrides() -> None:
    with patch.dict(os.environ, {
        "PYTHONPATH": "/tmp/host-shadow",
        "PYTHONHOME": "/tmp/host-python",
        "PIP_INDEX_URL": "https://example.invalid/simple",
        "PIP_ONLY_BINARY": "none",
    }):
        env = PREP.data_environment()
        assert "PYTHONPATH" not in env
        assert "PYTHONHOME" not in env
        assert not any(key.startswith("PIP_") for key in env if key != "PIP_DISABLE_PIP_VERSION_CHECK")
        assert env["PYTHONNOUSERSITE"] == "1"
        assert env["PIP_DISABLE_PIP_VERSION_CHECK"] == "1"


def test_preparation_receipt_requires_the_exact_verified_lock_and_python_abi() -> None:
    lock_file, digest_file = PREP.data_prep_lock_paths(
        system="Linux", machine="x86_64", python_version=(3, 11)
    )
    digest, pins = PREP.verify_data_prep_lock(lock_file, digest_file)
    receipt = {
        "sourceCompilationAllowed": False,
        "dependencyLock": {
            "state": "verified",
            "file": str(lock_file.relative_to(HERE)),
            "sha256": digest,
            "packageCount": len(pins),
            "installFlags": ["--require-hashes", "--only-binary=:all:", "--no-deps"],
        },
        "pythonImplementation": "CPython",
        "pythonVersion": "3.11.0",
        "pythonCacheTag": "cpython-311",
        "system": "Linux",
        "machine": "x86_64",
    }
    assert VERIFY.validate_data_environment_receipt(receipt) == []
    receipt["dependencyLock"]["sha256"] = "0" * 64
    assert any("SHA-256" in failure for failure in VERIFY.validate_data_environment_receipt(receipt))


def test_unqualified_runtime_profiles_fail_closed() -> None:
    for kwargs, expected in (
        ({"system": "Linux", "machine": "x86_64", "python_version": (3, 12)}, "CPython 3.12"),
        ({"system": "Linux", "machine": "aarch64", "python_version": (3, 11)}, "Linux x86_64"),
        ({"system": "Linux", "machine": "x86_64", "python_version": (3, 11), "implementation": "PyPy"}, "PyPy"),
    ):
        try:
            PREP.data_prep_lock_paths(**kwargs)
        except SystemExit as exc:
            assert expected in str(exc)
        else:
            raise AssertionError(f"unsupported profile unexpectedly resolved: {kwargs}")


def test_reused_prep_venv_must_match_locked_packages_without_extra_shadow_packages() -> None:
    _, pins = PREP.verify_data_prep_lock(*PREP.data_prep_lock_paths(
        system="Linux", machine="x86_64", python_version=(3, 11)
    ))
    installed = dict(pins)
    installed["pip"] = "22.3"
    assert PREP.package_lock_drift(installed, pins) == []
    installed["pandas"] = "0.0"
    assert any(row[0] == "pandas" for row in PREP.package_lock_drift(installed, pins))
    installed["pandas"] = dict(pins)["pandas"]
    installed["shadow-plugin"] = "1.0"
    assert any(row[0] == "shadow-plugin" for row in PREP.package_lock_drift(installed, pins))


def test_lock_parser_is_reported_and_rejects_grammar_the_committed_locks_do_not_use() -> None:
    assert REQUIREMENT_PARSER in {"pip vendored Requirement", "narrow pinned-requirement fallback"}
    parsed = NarrowPinnedRequirement("datasets==5.0.1")
    assert parsed.name == "datasets"
    assert parsed.marker is None
    assert str(parsed.specifier) == "==5.0.1"
    assert len(parsed.specifier) == 1

    # Anything outside the committed grammar must raise rather than be guessed,
    # so the fallback cannot be more permissive than the real parser.
    for unsupported in (
        "datasets",
        "datasets>=5.0.1",
        "datasets~=5.0.1",
        "datasets==5.0.1,<6",
        "datasets[json]==5.0.1",
        "datasets==5.0.1 ; python_version < '3.11'",
        "datasets==",
    ):
        try:
            NarrowPinnedRequirement(unsupported)
        except ValueError:
            continue
        raise AssertionError(f"fallback parser accepted unsupported grammar: {unsupported!r}")


def test_both_committed_locks_stay_inside_the_fallback_parser_grammar() -> None:
    """A richer lock must fail closed under the fallback, not parse by accident."""
    for version in ((3, 10), (3, 11)):
        lock_file, _ = PREP.data_prep_lock_paths(
            system="Linux", machine="x86_64", python_version=version
        )
        for line in lock_file.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if line[:1].isspace():
                assert re.fullmatch(r"\s+--hash=sha256:[0-9a-f]{64}(\s*\\)?", line), (
                    f"{lock_file.name}: continuation line is not a bare hash: {line!r}"
                )
                continue
            requirement_text = line.strip().removesuffix("\\").strip()
            NarrowPinnedRequirement(requirement_text)


if __name__ == "__main__":
    test_committed_lock_is_hash_pinned_and_contains_dataset_closure()
    test_lock_change_fails_before_environment_creation()
    test_prep_subprocess_environment_strips_host_python_and_pip_overrides()
    test_preparation_receipt_requires_the_exact_verified_lock_and_python_abi()
    test_unqualified_runtime_profiles_fail_closed()
    test_reused_prep_venv_must_match_locked_packages_without_extra_shadow_packages()
    test_lock_parser_is_reported_and_rejects_grammar_the_committed_locks_do_not_use()
    test_both_committed_locks_stay_inside_the_fallback_parser_grammar()
    print(
        "Kaggle CPU preparation dependency-lock tests passed (8 cases); "
        f"requirement parser: {REQUIREMENT_PARSER}."
    )
