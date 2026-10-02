#!/usr/bin/env python3
"""Install only pinned prebuilt benchmark runtimes.

No source compilation is permitted. Missing/incompatible binaries fail fast so
Kaggle time is not consumed compiling C++/CUDA extensions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "kaggle-prebuilt-runtimes.json"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_extract(tf: tarfile.TarFile, dest: Path) -> None:
    root = dest.resolve()
    for member in tf.getmembers():
        target = (dest / member.name).resolve()
        if root != target and root not in target.parents:
            raise RuntimeError(f"unsafe tar member: {member.name}")
    tf.extractall(dest)


def run(cmd: list[str], env: dict[str, str] | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, env=env)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("artifact_id")
    ap.add_argument("--dest", type=Path, default=Path("/kaggle/working/pari-runtimes"))
    ap.add_argument("--cache", type=Path, default=Path("/kaggle/working/pari-downloads"))
    args = ap.parse_args()

    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    artifacts = {row["id"]: row for row in registry["artifacts"]}
    if args.artifact_id not in artifacts:
        raise SystemExit(f"unknown prebuilt artifact {args.artifact_id}; allowed: {', '.join(sorted(artifacts))}")
    artifact = artifacts[args.artifact_id]

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
        env = os.environ.copy()
        env.update({
            "PIP_ONLY_BINARY": ":all:",
            "PIP_NO_BUILD_ISOLATION": "0",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        })
        # --only-binary=:all: applies to dependencies too. If a dependency lacks a
        # wheel, installation FAILS instead of compiling it from source.
        run([
            sys.executable, "-m", "pip", "install",
            "--only-binary=:all:",
            str(archive),
        ], env=env)
        run([sys.executable, "-c", "import vllm; print('vllm', vllm.__version__)"])
        receipt = {
            "artifact": artifact,
            "localPath": str(archive),
            "sha256Verified": actual,
            "installMethod": "pip_binary_only",
            "sourceCompilationAllowed": False,
        }
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
