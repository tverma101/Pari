"""Validate public English Core builder manifests for reproducibility.

Usage:
    python validate-english-core-public-manifest.py MANIFEST.json
    python validate-english-core-public-manifest.py MANIFEST.json --promotion

Promotion mode requires immutable requested source revisions and non-empty resolved
fingerprints for every source represented by the manifest. This checks provenance,
not benchmark correctness or licensing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

MUTABLE = {"", "mutable_default_not_pinned", "main", "master", "latest", "default", "unknown", None}


def pinned(value) -> bool:
    return value not in MUTABLE and str(value).strip().lower() not in {str(x).lower() for x in MUTABLE if x is not None}


def has_fingerprint(value) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return bool(value) and all(has_fingerprint(v) for v in value.values())
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--promotion", action="store_true")
    args = ap.parse_args()

    path = Path(args.manifest)
    data = json.loads(path.read_text())
    errors: list[str] = []
    warnings: list[str] = []

    def issue(message: str, required_for_promotion: bool = False) -> None:
        if args.promotion and required_for_promotion:
            errors.append(message)
        else:
            warnings.append(message)

    if not data.get("datasetsLibraryVersion"):
        issue("datasetsLibraryVersion missing", True)

    sources = data.get("sources") or {}
    if not sources:
        errors.append("manifest has no sources")

    for name, source in sorted(sources.items()):
        revision = source.get("requestedRevision")
        if not pinned(revision):
            issue(f"{name}: source revision is not immutably pinned ({revision!r})", True)

    fingerprints = data.get("resolvedDatasetFingerprints") or {}
    for name in sorted(sources):
        value = fingerprints.get(name)
        if not has_fingerprint(value):
            issue(f"{name}: resolved dataset fingerprint missing/incomplete", True)

    if data.get("purpose") is None:
        warnings.append("manifest missing purpose")
    if data.get("cases") is None:
        errors.append("manifest missing case count")
    if not data.get("revisionPolicy"):
        warnings.append("manifest missing revisionPolicy")

    report = {
        "version": 1,
        "manifest": str(path),
        "mode": "promotion" if args.promotion else "exploratory",
        "errors": errors,
        "warnings": warnings,
        "status": "fail" if errors else ("pass_with_warnings" if warnings else "pass"),
        "interpretation": [
            "This validator checks source-version/fingerprint provenance, not linguistic validity, licensing, or native-protocol fidelity.",
            "Promotion mode rejects mutable branch/default revisions even when a resolved cache fingerprint exists; both immutable source identity and resolved bytes provenance are required when supported.",
            "Public-fast remains an engineering screen even when perfectly reproducible. Reproducibility does not upgrade it into an official/native benchmark score."
        ]
    }
    print(json.dumps(report, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
