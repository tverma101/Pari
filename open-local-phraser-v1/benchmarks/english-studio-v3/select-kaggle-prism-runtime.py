#!/usr/bin/env python3
"""Select a compatible pinned Prism llama.cpp prebuilt without compiling.

Both artifacts are the same pinned Prism source commit. The only allowed ladder
is CUDA 12.8 then CUDA 12.4. Every failed binary attempt is preserved.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
INSTALL = HERE / "install-kaggle-prebuilt-runtime.py"
VERIFY = HERE / "verify-kaggle-prebuilt-runtime.py"
LADDER = (
    "prism-llamacpp-b10735-cuda12.8-linux-x86_64",
    "prism-llamacpp-b10735-cuda12.4-linux-x86_64",
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runtime-dir", type=Path, default=Path("/kaggle/working/pari-runtimes"))
    ap.add_argument("--output", type=Path, default=Path("/kaggle/working/results/prism-runtime-selection.json"))
    args = ap.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "version": 1,
        "policy": "predeclared vendor-binary compatibility ladder; no source build",
        "ladder": list(LADDER),
        "attempts": [],
        "selectedArtifactId": None,
    }

    for artifact_id in LADDER:
        receipt = args.runtime_dir / f"{artifact_id}.receipt.json"
        install_output = ""
        install_rc = 0
        if not receipt.is_file():
            install = subprocess.run(
                [sys.executable, str(INSTALL), artifact_id, "--dest", str(args.runtime_dir)],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            install_rc = install.returncode
            install_output = install.stdout
        verify = None
        if install_rc == 0:
            verify = subprocess.run(
                [sys.executable, str(VERIFY), artifact_id, "--runtime-dir", str(args.runtime_dir)],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
        attempt = {
            "artifactId": artifact_id,
            "receiptExistedBeforeAttempt": receipt.is_file(),
            "installReturnCode": install_rc,
            "installOutput": install_output,
            "verifyReturnCode": verify.returncode if verify else None,
            "verifyOutput": verify.stdout if verify else None,
        }
        report["attempts"].append(attempt)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if install_rc == 0 and verify is not None and verify.returncode == 0:
            report["selectedArtifactId"] = artifact_id
            report["status"] = "selected_prebuilt"
            args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"status": report["status"], "selectedArtifactId": artifact_id, "artifact": str(args.output)}, indent=2))
            return

    report["status"] = "runtime_unqualified"
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "selectedArtifactId": None, "artifact": str(args.output)}, indent=2))
    raise SystemExit(2)


if __name__ == "__main__":
    main()
