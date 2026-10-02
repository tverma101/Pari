#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILDER = HERE / "build-word-studio-transform-suite.py"
SEED = HERE / "interactive.seed.json"


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        tasks = root / "tasks.jsonl"
        manifest = root / "manifest.json"
        review = root / "review.json"
        subprocess.run([
            sys.executable, str(BUILDER),
            "--seed", str(SEED),
            "--output", str(tasks),
            "--manifest", str(manifest),
            "--private-review-key", str(review),
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        rows = [json.loads(line) for line in tasks.read_text(encoding="utf-8").splitlines() if line.strip()]
        meta = json.loads(manifest.read_text(encoding="utf-8"))
        private = json.loads(review.read_text(encoding="utf-8"))
        assert len(rows) == 100
        assert meta["cases"] == 100
        assert len(private["items"]) == 100
        assert len({row["id"] for row in rows}) == 100
        assert sum(row["semanticMode"] == "intentional_compression" for row in rows) == 6
        assert all(row["requestedCount"] == 10 for row in rows)
        forbidden = {"requirements", "expectations", "input", "selection", "gold", "answer"}
        for row in rows:
            assert not forbidden.intersection(row), (row["id"], forbidden.intersection(row))
            assert isinstance(row.get("prompt"), str) and row["prompt"].strip()
            assert "requirements" not in row["prompt"].casefold()

    print("word studio transform builder fixtures passed")


if __name__ == "__main__":
    main()
