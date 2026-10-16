#!/usr/bin/env python3
"""Install only pinned prebuilt benchmark runtimes.

No source compilation is permitted. Missing/incompatible binaries fail fast so
Kaggle time is not consumed compiling C++/CUDA extensions.

Issue #41: a pinned Python wheel is not a runtime. For a ``python_wheel``
artifact this installer additionally requires a reviewed, hash-bound dependency
lock and installs into a dedicated virtual environment, so the canonical path
cannot inherit mutable Kaggle global packages. When the lock is absent or
unreviewed the installer records ``runtime_unqualified`` and stops instead of
letting pip resolve the closure against whatever the base image happens to
ship.
"""
from __future__ import annotations

import argparse
import email.parser
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "kaggle-prebuilt-runtimes.json"

EXIT_OK = 0
EXIT_UNQUALIFIED = 3

SOURCE_BUILD_FLAGS = (
    "--no-binary",
    "--no-binary=:all:",
    "--no-build-isolation",
    "--config-settings",
    "--install-option",
    "--global-option",
    "-e",
    "--editable",
)

NAME_CANON = re.compile(r"[-_.]+")


def canonical_name(name: str) -> str:
    """PEP 503 normalized distribution name."""
    return NAME_CANON.sub("-", name).lower()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def emit_unqualified(
    classification: str,
    failures: list[str],
    receipt: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit the machine-readable fail-closed receipt and exit non-zero."""
    payload: dict[str, Any] = {
        "status": "runtime_unqualified",
        "classification": classification,
        "failures": failures,
        "sourceCompilationAttempted": False,
    }
    if receipt is not None:
        payload["receipt"] = str(receipt)
    if extra:
        payload.update(extra)
    print(json.dumps(payload, indent=2))
    raise SystemExit(EXIT_UNQUALIFIED)


def load_registry() -> dict[str, Any]:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if int(registry.get("version", 1)) < 2:
        raise SystemExit(
            "pinned runtime registry predates the Issue #41 dependency-closure "
            "contract; refusing to install without environments[]"
        )
    return registry


def environment_for(registry: dict[str, Any], artifact_id: str) -> dict[str, Any] | None:
    for env in registry.get("environments", []):
        if env.get("artifactId") == artifact_id:
            return env
    return None


def read_wheel_metadata(wheel: Path) -> dict[str, Any]:
    """Read METADATA out of a wheel without installing anything."""
    with zipfile.ZipFile(wheel) as zf:
        names = [
            n
            for n in zf.namelist()
            if n.endswith(".dist-info/METADATA") and n.count("/") == 1
        ]
        if len(names) != 1:
            raise ValueError(f"wheel {wheel.name} does not contain exactly one top-level dist-info/METADATA")
        raw = zf.read(names[0])
    msg = email.parser.BytesParser().parsebytes(raw)
    return {
        "name": msg.get("Name"),
        "version": msg.get("Version"),
        "requiresPython": msg.get("Requires-Python"),
        "requiresDist": msg.get_all("Requires-Dist") or [],
        "metadataPath": names[0],
        "metadataSha256": sha256_bytes(raw),
    }


def requirement_name(requirement: str) -> str | None:
    """Parse the distribution name out of a PEP 508 requirement string."""
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    return canonical_name(match.group(1)) if match else None


def requirement_is_optional(requirement: str) -> bool:
    """True when the requirement only applies under an extra/marker."""
    lowered = requirement.lower()
    if ";" in lowered:
        marker = lowered.split(";", 1)[1]
        if "extra" in marker:
            return True
    return False


def locked_versions(lock: dict[str, Any], *, include_optional: bool = False) -> dict[str, str]:
    out: dict[str, str] = {}
    for package in lock.get("packages", []):
        if package.get("optional") and not include_optional:
            continue
        out[canonical_name(package["name"])] = str(package["version"])
    return out


def evaluate_lock(
    env: dict[str, Any],
    lock: dict[str, Any] | None,
    lock_sha256: str | None,
    lock_bytes: bytes | None,
    wheel_metadata: dict[str, Any] | None,
) -> list[str]:
    """Fail-closed evaluation of a candidate dependency lock.

    Returns a list of human-readable failures; empty means the lock is usable.
    """
    dep = env.get("dependencyLock") or {}
    failures: list[str] = []
    if dep.get("state") != "locked":
        return [
            f"dependency lock state is {dep.get('state')!r}, expected 'locked'; "
            "the runtime-critical closure has not been resolved and reviewed on the target image"
        ]
    if lock is None:
        return [f"dependency lock file {dep.get('file')!r} is missing"]
    if lock_bytes is not None and lock_sha256 is not None:
        actual = sha256_bytes(lock_bytes)
        if actual != dep.get("sha256"):
            failures.append(
                f"dependency lock sha256 mismatch: registry={dep.get('sha256')} actual={actual}"
            )
    if lock.get("schema") != "kaggle-runtime-dependency-lock-1":
        failures.append(f"unsupported dependency lock schema {lock.get('schema')!r}")
    if lock.get("artifactId") != env.get("artifactId"):
        failures.append(
            f"dependency lock artifactId={lock.get('artifactId')!r} expected {env.get('artifactId')!r}"
        )
    if lock.get("evidenceGaps"):
        failures.append(
            "dependency lock still records evidence gaps: "
            + "; ".join(str(g) for g in lock["evidenceGaps"])
        )

    packages = lock.get("packages") or []
    if not packages:
        failures.append("dependency lock contains no packages")
    seen: dict[str, int] = {}
    for index, package in enumerate(packages):
        name = canonical_name(str(package.get("name", "")))
        seen[name] = seen.get(name, 0) + 1
        if not name:
            failures.append(f"packages[{index}] has no name")
        if not package.get("version"):
            failures.append(f"packages[{index}] ({name}) has no version pin")
        hashes = package.get("sha256") or []
        if not hashes or not all(re.fullmatch(r"[0-9a-f]{64}", str(h).lower()) for h in hashes):
            failures.append(
                f"packages[{index}] ({name}) has no usable sha256 wheel hashes; "
                "an unhashed pin cannot fail closed"
            )
    for name, count in seen.items():
        if count > 1:
            failures.append(f"dependency lock pins {name} {count} times")

    pinned = locked_versions(lock)
    required = {canonical_name(p) for p in (dep.get("requiredPackages") or [])}
    for name in sorted(required):
        if name not in pinned:
            failures.append(f"dependency lock does not pin required runtime package {name!r}")

    if wheel_metadata is not None:
        declared = wheel_metadata.get("requiresDist") or []
        for requirement in declared:
            if requirement_is_optional(requirement):
                continue
            name = requirement_name(requirement)
            if name is None:
                continue
            if name not in pinned and name not in required:
                failures.append(
                    f"wheel Requires-Dist {requirement!r} is outside the frozen closure; "
                    "pip would have to resolve it against the mutable base image"
                )
    return failures


def materialize_requirements_txt(lock: dict[str, Any], *, include_optional: bool = False) -> str:
    """Render the lock as a pip --require-hashes requirements file."""
    lines = [
        "# generated from "
        f"{lock.get('artifactId')} ({lock.get('schema')}); do not edit by hand",
        "--only-binary=:all:",
    ]
    for package in sorted(lock.get("packages", []), key=lambda p: canonical_name(p["name"])):
        if package.get("optional") and not include_optional:
            continue
        hashes = "".join(f" --hash=sha256:{str(h).lower()}" for h in package["sha256"])
        lines.append(f"{package['name']}=={package['version']}{hashes}")
    return "\n".join(lines) + "\n"


def assert_binary_only(cmd: list[str]) -> None:
    """Reject any command that could trigger a source build."""
    for token in cmd:
        if token in SOURCE_BUILD_FLAGS or token.startswith("--no-binary=") :
            raise ValueError(f"source-build flag {token!r} is forbidden by the pinned runtime policy")
        if token.startswith("--config-settings") or token == "--config-settings":
            raise ValueError("--config-settings can select a source build; forbidden")


def build_dependency_install_command(
    python: Path, requirements_txt: Path, report: Path | None
) -> list[str]:
    cmd = [
        str(python),
        "-m",
        "pip",
        "install",
        "--only-binary=:all:",
        "--require-hashes",
        "--no-deps",
        "-r",
        str(requirements_txt),
    ]
    assert_binary_only(cmd)
    if report is not None:
        cmd += ["--report", str(report)]
    return cmd


def pip_supports_report(python: Path) -> bool:
    rc = subprocess.run(
        [str(python), "-m", "pip", "install", "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return rc.returncode == 0 and "--report" in rc.stdout


def build_lock_from_pip_report(
    report: dict[str, Any],
    *,
    artifact_id: str,
    python_version: str,
    optional_packages: set[str] | None = None,
    evidence_gaps: list[str] | None = None,
) -> dict[str, Any]:
    """Convert a real ``pip install --report`` capture into a reviewable lock.

    This is the operator-side step that must run on the real Kaggle image; it is
    deliberately pure so the conversion can be tested without a GPU.
    """
    optional = {canonical_name(n) for n in (optional_packages or set())}
    packages: list[dict[str, Any]] = []
    for entry in report.get("install", []):
        meta = entry.get("metadata") or {}
        name = canonical_name(str(meta.get("name", "")))
        if not name:
            continue
        download = entry.get("download_info") or {}
        hashes = ((download.get("archive_info") or {}).get("hashes") or {})
        sha = hashes.get("sha256")
        packages.append(
            {
                "name": meta.get("name"),
                "version": meta.get("version"),
                "sha256": [sha] if sha else [],
                "wheel": download.get("url"),
                "requiredBy": ["pip-report"],
                "optional": name in optional,
            }
        )
    packages.sort(key=lambda p: canonical_name(p["name"]))
    return {
        "schema": "kaggle-runtime-dependency-lock-1",
        "artifactId": artifact_id,
        "python": {"version": python_version},
        "packages": packages,
        "resolutionReport": {
            "source": "pip install --report",
            "environment": report.get("environment"),
        },
        "evidenceGaps": list(evidence_gaps or []),
    }


def resolve_venv_python(env: dict[str, Any], dest: Path, override: Path | None) -> Path:
    if override is not None:
        if not Path(override).exists():
            raise FileNotFoundError(f"--python {override} does not exist")
        return Path(override)
    template = env.get("venvPathTemplate")
    if not template:
        raise RuntimeError("environment does not declare venvPathTemplate")
    root = dest / env["artifactId"] / "venv"
    candidate = root / "bin" / "python"
    if not candidate.exists():
        raise FileNotFoundError(
            f"isolated runtime interpreter {candidate} does not exist; create the venv before installing"
        )
    if not str(root) == str(template.format(dest=dest, artifactId=env["artifactId"])):
        # Defensive: the template is the documented contract; keep them in sync.
        raise RuntimeError("venvPathTemplate does not match the resolved interpreter path")
    return candidate


def create_venv(env: dict[str, Any], dest: Path, *, recreate: bool) -> Path:
    root = dest / env["artifactId"] / "venv"
    if recreate and root.exists():
        shutil.rmtree(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    if not (root / "bin" / "python").exists():
        rc = subprocess.run(
            [sys.executable, "-m", "venv", "--without-pip", str(root)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        # --without-pip keeps the environment hermetic; pip is invoked explicitly below.
        if rc.returncode != 0:
            raise RuntimeError(f"venv creation failed:\n{rc.stdout}")
    return root / "bin" / "python"


def safe_extract(tf: tarfile.TarFile, dest: Path) -> None:
    root = dest.resolve()
    for member in tf.getmembers():
        target = (dest / member.name).resolve()
        if root != target and root not in target.parents:
            raise RuntimeError(f"unsafe tar member: {member.name}")
    tf.extractall(dest)


def run(cmd: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, env=env, text=True)


def isolated_env(venv_root: Path) -> dict[str, str]:
    """Environment for installs/probes: never inherit an ambient PYTHONPATH."""
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_NO_INPUT"] = "1"
    env["VIRTUAL_ENV"] = str(venv_root)
    env["PATH"] = f"{venv_root / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    return env


def install_wheel_runtime(
    artifact: dict[str, Any],
    archive: Path,
    args: argparse.Namespace,
    registry: dict[str, Any],
) -> dict[str, Any]:
    env_spec = environment_for(registry, artifact["id"])
    if env_spec is None:
        emit_unqualified(
            "environment_contract_missing",
            [
                f"artifact {artifact['id']!r} has no environments[] entry; Issue #41 "
                "requires an explicit isolation + dependency-closure contract for Python wheels"
            ],
            extra={"artifactId": artifact["id"]},
        )

    wheel_metadata = read_wheel_metadata(archive)
    print(
        f"wheel metadata: {wheel_metadata['name']} {wheel_metadata['version']} "
        f"(Requires-Python {wheel_metadata['requiresPython']})",
        flush=True,
    )

    dep = env_spec.get("dependencyLock") or {}
    lock_path = (HERE / dep["file"]) if dep.get("file") else None
    lock_bytes: bytes | None = None
    lock: dict[str, Any] | None = None
    if lock_path is not None and lock_path.is_file():
        lock_bytes = lock_path.read_bytes()
        lock = json.loads(lock_bytes)
    failures = evaluate_lock(env_spec, lock, dep.get("sha256"), lock_bytes, wheel_metadata)
    if failures:
        emit_unqualified(
            "dependency_lock_pending"
            if dep.get("state") != "locked"
            else "dependency_lock_rejected",
            failures,
            extra={
                "artifactId": artifact["id"],
                "wheelMetadata": wheel_metadata,
                "expectedLockFile": str(lock_path) if lock_path else None,
                "nextAction": (
                    "run `install-kaggle-prebuilt-runtime.py --emit-resolution-plan "
                    f"{artifact['id']}` on the Kaggle image, capture a real `pip install "
                    "--report`, convert it with build_lock_from_pip_report, review it, then "
                    "commit the lock together with its sha256 in environments[].dependencyLock"
                ),
            },
        )

    assert lock is not None and lock_bytes is not None  # narrowed by evaluate_lock
    try:
        venv_python = create_venv(env_spec, args.dest, recreate=args.recreate_venv)
    except Exception as exc:  # noqa: BLE001 - surfaced as a structured failure
        emit_unqualified(
            "environment_venv_unavailable",
            [f"could not create the isolated runtime environment: {exc}"],
            extra={"artifactId": artifact["id"]},
        )
    venv_root = venv_python.parent.parent

    work = args.dest / artifact["id"]
    work.mkdir(parents=True, exist_ok=True)
    lock_copy = work / "dependency.lock.json"
    lock_copy.write_bytes(lock_bytes)
    requirements_txt = work / "dependency.lock.requirements.txt"
    requirements_txt.write_text(
        materialize_requirements_txt(lock, include_optional=args.include_optional),
        encoding="utf-8",
    )

    report_path = work / "dependency-resolution-report.json"
    proc_env = isolated_env(venv_root)
    proc_env["PIP_ONLY_BINARY"] = ":all:"
    proc_env["PIP_CONSTRAINT"] = str(requirements_txt)

    # Step 1: install the already-hash-verified wheel with dependency resolution
    # disabled, so the wheel itself can never pull a mutable package.
    wheel_cmd = [
        str(venv_python),
        "-m",
        "pip",
        "install",
        "--only-binary=:all:",
        "--no-deps",
        str(archive),
    ]
    assert_binary_only(wheel_cmd)
    run(wheel_cmd, env=proc_env)

    # Step 2: install the frozen closure from the hash-bound requirements file.
    support_report = pip_supports_report(venv_python)
    dep_cmd = build_dependency_install_command(
        venv_python, requirements_txt, report_path if support_report else None
    )
    dep_proc = run(dep_cmd, env=proc_env)

    if support_report and report_path.is_file():
        resolution_report = {
            "schema": "kaggle-runtime-resolution-report-1",
            "artifactId": artifact["id"],
            "pipReport": json.loads(report_path.read_text(encoding="utf-8")),
            "pipStdout": "",
            "pipStderr": "",
            "pipExitCode": dep_proc.returncode,
            "environment": {
                "venv": str(venv_root),
                "python": str(venv_python),
                "pythonExecutableSha256": (
                    sha256_file(venv_python) if venv_python.is_file() else None
                ),
            },
        }
        (work / "dependency-resolution-report.json").write_text(
            json.dumps(resolution_report, indent=2) + "\n", encoding="utf-8"
        )
    else:
        print(
            "note: this pip build has no --report support; the frozen requirements file "
            "is retained as the machine-readable resolution record",
            flush=True,
        )

    return {
        "artifact": artifact,
        "localPath": str(archive),
        "sha256Verified": sha256_file(archive),
        "installMethod": "pip_binary_only_frozen_closure_isolated_venv",
        "sourceCompilationAllowed": False,
        "environment": {
            "kind": env_spec.get("isolation"),
            "venvPath": str(venv_root),
            "pythonExecutable": str(venv_python),
            "pythonExecutableSha256": (
                sha256_file(venv_python) if venv_python.is_file() else None
            ),
        },
        "dependencyLock": {
            "path": str(lock_path),
            "copiedTo": str(lock_copy),
            "sha256": sha256_bytes(lock_bytes),
            "packageCount": len(lock.get("packages", [])),
            "requirementsTxtSha256": sha256_file(requirements_txt),
        },
        "wheelMetadata": wheel_metadata,
        "resolutionReport": str(report_path) if support_report and report_path.is_file() else None,
        "logDir": str(work),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("artifact_id")
    ap.add_argument("--dest", type=Path, default=Path("/kaggle/working/pari-runtimes"))
    ap.add_argument("--cache", type=Path, default=Path("/kaggle/working/pari-downloads"))
    ap.add_argument("--recreate-venv", action="store_true")
    ap.add_argument("--include-optional", action="store_true")
    ap.add_argument("--emit-resolution-plan", action="store_true")
    args = ap.parse_args()

    registry = load_registry()
    artifacts = {row["id"]: row for row in registry["artifacts"]}
    if args.artifact_id not in artifacts:
        raise SystemExit(f"unknown prebuilt artifact {args.artifact_id}; allowed: {', '.join(sorted(artifacts))}")
    artifact = artifacts[args.artifact_id]

    if args.emit_resolution_plan:
        env_spec = environment_for(registry, args.artifact_id)
        if env_spec is None:
            raise SystemExit(f"artifact {args.artifact_id} has no environments[] contract")
        dep = env_spec["dependencyLock"]
        venv = f"/kaggle/working/pari-runtimes/{args.artifact_id}/venv"
        print(
            json.dumps(
                {
                    "artifactId": args.artifact_id,
                    "lockState": dep.get("state"),
                    "requiredPackages": dep.get("requiredPackages"),
                    "optionalPackages": dep.get("optionalPackages"),
                    "evidenceGaps": dep.get("evidenceGaps"),
                    "commands": [
                        "# Run on the real Kaggle image; resolution alone does not need a GPU.",
                        f"python3 -m venv {venv}",
                        f"{venv}/bin/pip install --only-binary=:all: "
                        f"--report /kaggle/working/{args.artifact_id}.report.json "
                        f"'{artifact['url']}'",
                        (
                            "# Convert with build_lock_from_pip_report, review every pin, then "
                            "commit the lock and its sha256 in environments[].dependencyLock."
                        ),
                    ],
                },
                indent=2,
            )
        )
        raise SystemExit(EXIT_OK)

    args.cache.mkdir(parents=True, exist_ok=True)
    args.dest.mkdir(parents=True, exist_ok=True)
    filename = artifact["url"].rsplit("/", 1)[-1]
    # URL-escaped '+' is intentionally retained in the URL but decoded for a local file name.
    filename = filename.replace("%2B", "+")
    archive = args.cache / filename
    if not archive.exists():
        print(f"downloading pinned prebuilt: {artifact['url']}", flush=True)
        with urllib.request.urlopen(artifact["url"], timeout=120) as response, archive.open("wb") as out:
            shutil.copyfileobj(response, out)
    actual = sha256_file(archive)
    if actual.lower() != artifact["sha256"].lower():
        archive.unlink(missing_ok=True)
        raise SystemExit(f"SHA256 mismatch for {artifact['id']}: expected {artifact['sha256']} got {actual}")
    print(f"sha256 ok: {actual}", flush=True)

    if artifact["kind"] == "python_wheel":
        receipt = install_wheel_runtime(artifact, archive, args, registry)
        receipt["sha256Verified"] = actual
    elif artifact["kind"] == "tarball":
        out_dir = args.dest / artifact["id"]
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True)
        with tarfile.open(archive, "r:*") as tf:
            safe_extract(tf, out_dir)
        servers = [p for p in out_dir.rglob("llama-server") if p.is_file()]
        if not servers:
            raise SystemExit("prebuilt archive extracted but llama-server was not found; do not compile a replacement")
        server = servers[0]
        server.chmod(server.stat().st_mode | 0o111)
        rc = subprocess.run([str(server), "--version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if rc.returncode != 0:
            raise SystemExit(f"prebuilt llama-server failed version smoke; do not compile fallback:\n{rc.stdout}")
        print(rc.stdout.strip())
        receipt = {
            "artifact": artifact,
            "localPath": str(archive),
            "sha256Verified": actual,
            "installMethod": "verified_vendor_tarball",
            "sourceCompilationAllowed": False,
            "runtimeExecutable": str(server),
            "versionOutput": rc.stdout.strip(),
        }
    else:
        raise SystemExit(f"unsupported artifact kind {artifact['kind']}")

    receipt_path = args.dest / f"{artifact['id']}.receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "installed_prebuilt", "receipt": str(receipt_path)}, indent=2))


if __name__ == "__main__":
    main()
