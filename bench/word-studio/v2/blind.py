#!/usr/bin/env python3
"""Turn a fetched run into blind judging packets and a sealed key (#87).

    cd bench/word-studio
    python3 -m v2.blind --run v2/runs/<run-id>

Writes ``v2/judging/<run-id>/``:

- ``packets/<task-id>.md``: what the judge reads. Each candidate's options
  appear under a letter that is shuffled for every task, with an opaque output
  ref and the sha256 of the raw output file. No model names or paths.
- ``packets/index.json``: the task list, the rubric hash, and the key's sha256,
  so the key cannot be swapped after judging.
- ``scores.template.jsonl``: one row per task and letter for the judge to fill
  in and save as ``scores.jsonl`` (format in ``v2/RUBRIC.md``).
- ``sealed/key.json``: letter -> candidate and raw file. The judge does not open
  it; ``v2.aggregate`` does.

Only candidates whose run completed are judged. Failed runs are listed in the
key as not judged, with their error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import secrets
import string
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
WORD_STUDIO = HERE.parent
REPO_ROOT = WORD_STUDIO.parents[1]
RUBRIC = HERE / "RUBRIC.md"
CRITERIA = ("fit", "meaning", "register", "variety", "usefulness")

if str(WORD_STUDIO) not in sys.path:
    sys.path.insert(0, str(WORD_STUDIO))

from v2 import build_tasks, hard_checks  # noqa: E402


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()


def rel(path: Path) -> str:
    """Repository-relative path, so the key still resolves on another machine."""
    path = path.resolve()
    return path.relative_to(REPO_ROOT).as_posix() if path.is_relative_to(REPO_ROOT) else str(path)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_runs(run_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Completed candidate runs, and the ones that will not be judged."""
    judged, skipped = [], []
    for run_json in sorted(run_dir.glob("*/run.json")):
        run = json.loads(run_json.read_text(encoding="utf-8"))
        cid = (run.get("candidate") or {}).get("candidate_id") or run_json.parent.name
        entry = {"candidate_id": cid, "dir": run_json.parent, "run": run, "run_sha256": sha256_file(run_json)}
        if run.get("status") == "completed":
            judged.append(entry)
        else:
            skipped.append({"candidate_id": cid, "status": run.get("status"), "stage": run.get("stage"),
                            "error": run.get("error"), "run_json": rel(run_json),
                            "run_sha256": entry["run_sha256"]})
    return judged, skipped


def instruction_of(task: dict[str, Any]) -> str:
    return task["messages"][1]["content"].rsplit("\n\n", 1)[-1]


def render_packet(task: dict[str, Any], entries: list[dict[str, Any]]) -> str:
    lines = [f"# {task['id']}", "", f"Kind: `{task['kind']}`, asks for {task['requested_options']} options.", ""]
    lines += ["Paragraph:", "", "> " + task["paragraph"], ""]
    if task.get("sentence"):
        selection = task["selection"]
        sentence = task["sentence"]
        if task["kind"] in {"tap_word", "phrase_to_word"}:
            start = selection["start"] - task["paragraph"].index(sentence)
            sentence = sentence[:start] + "[[" + selection["text"] + "]]" + sentence[start + len(selection["text"]):]
        lines += [f"Selected: {sentence}", ""]
    if task.get("word"):
        lines += [f"Word: **{task['word']}** ({task['word_origin']})", ""]
    lines += ["Instruction given to every model:", "", "> " + instruction_of(task), ""]
    for entry in entries:
        checked = entry["checked"]
        lines += [f"## Output {entry['label']}", "",
                  f"ref `{entry['output_ref']}`, raw sha256 `{entry['output_sha256']}`", "",
                  f"Format: {checked['format']} ({checked['parse_mode']}), {checked['returned']} options"
                  + (", hit the token limit" if checked["truncated"] else ""), ""]
        if not checked["options"]:
            lines += ["No options to judge.", ""]
        for option in checked["options"]:
            text = option["text"].replace("\n", " ")
            note = ""
            if option["fail"]:
                note = f"  — not judged, counts as 0 (fail: {', '.join(option['fail'])})"
            elif option["warn"]:
                note = f"  — check: {', '.join(option['warn'])}"
            lines.append(f"{option['index'] + 1}. {text}{note}")
        lines.append("")
    return "\n".join(lines)


def template_row(task_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    judged = [o["index"] + 1 for o in entry["checked"]["options"] if o["judge"]]
    return {
        "task_id": task_id,
        "label": entry["label"],
        "output_ref": entry["output_ref"],
        "output_sha256": entry["output_sha256"],
        "criteria": {c: None for c in CRITERIA} if judged else None,
        "relevance": {str(i): None for i in judged},
        "note": "",
    }


def build(run_dir: Path, out_dir: Path, *, task_ids: list[str] | None = None) -> dict[str, Any]:
    if (out_dir / "sealed" / "key.json").exists():
        raise SystemExit(f"{out_dir} already has a key; never overwrite judging evidence")
    judged, skipped = load_runs(run_dir)
    if not judged:
        raise SystemExit(f"no completed candidate runs in {run_dir}")
    sets = {(e["run"]["task_set"], e["run"]["task_file_sha256"], e["run"]["prompt_version"]) for e in judged}
    if len(sets) != 1:
        raise SystemExit(f"candidates ran different task sets or prompts: {sorted(sets)}")
    set_name, task_sha, _prompt = sets.pop()
    manifest = json.loads(build_tasks.MANIFEST.read_text(encoding="utf-8"))
    if manifest["sets"][set_name]["sha256"] != task_sha:
        raise SystemExit(f"the runs used a different {set_name} task file than v2/tasks has now; "
                         "judge them from the commit they ran at")
    tasks = {t["id"]: t for t in build_tasks.load_tasks(set_name)}
    have = [{p.stem for p in (e["dir"] / "outputs").glob("*.json")} for e in judged]
    common = set.intersection(*have)
    chosen = [t for t in tasks if t in common] if task_ids is None else task_ids
    missing = [t for t in chosen if t not in common]
    if missing:
        raise SystemExit(f"tasks without an output from every judged candidate: {missing}")
    secret = secrets.token_hex(16)
    key: dict[str, Any] = {
        "run_dir": rel(run_dir),
        "task_set": set_name,
        "secret": secret,
        "candidates": {e["candidate_id"]: {"run_json": rel(e["dir"] / "run.json"), "run_sha256": e["run_sha256"],
                                           "complete_set": e["run"].get("complete_set")} for e in judged},
        "not_judged": skipped,
        "tasks": {},
    }
    template: list[dict[str, Any]] = []
    for task_id in chosen:
        task = tasks[task_id]
        order = list(judged)
        random.Random(int(digest(secret, task_id)[:16], 16)).shuffle(order)
        entries = []
        for label, e in zip(string.ascii_uppercase, order):
            path = e["dir"] / "outputs" / f"{task_id}.json"
            output = json.loads(path.read_text(encoding="utf-8"))
            entries.append({
                "label": label,
                "candidate_id": e["candidate_id"],
                "output_ref": "o-" + digest(secret, e["candidate_id"], task_id)[:12],
                "output_sha256": sha256_file(path),
                "raw_output": rel(path),
                "checked": hard_checks.check(task, output),
            })
        (out_dir / "packets").mkdir(parents=True, exist_ok=True)
        (out_dir / "packets" / f"{task_id}.md").write_text(render_packet(task, entries), encoding="utf-8")
        key["tasks"][task_id] = {e["label"]: {k: e[k] for k in ("candidate_id", "output_ref", "output_sha256",
                                                                  "raw_output")} for e in entries}
        template += [template_row(task_id, e) for e in entries]
    write_json(out_dir / "sealed" / "key.json", key)
    index = {
        "run_id": run_dir.name,
        "task_set": set_name,
        "tasks": chosen,
        "outputs_per_task": len(judged),
        "checks_version": hard_checks.CHECKS_VERSION,
        "rubric_sha256": sha256_file(RUBRIC),
        "key_sha256": sha256_file(out_dir / "sealed" / "key.json"),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "judge_reads": "packets/*.md only; sealed/key.json stays closed until scores.jsonl is final",
    }
    write_json(out_dir / "packets" / "index.json", index)
    header = {"header": True, "judge": None, "session": None, "blind": True,
              "rubric_sha256": index["rubric_sha256"], "key_sha256": index["key_sha256"]}
    with (out_dir / "scores.template.jsonl").open("w", encoding="utf-8") as fh:
        for row in [header, *template]:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return index


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", type=Path, required=True, help="v2/runs/<run-id>")
    parser.add_argument("--out", type=Path, help="default: v2/judging/<run-id>")
    parser.add_argument("--tasks", help="comma-separated task ids (default: every task all candidates ran)")
    args = parser.parse_args(argv)
    run_dir = args.run.resolve()
    out_dir = (args.out or HERE / "judging" / run_dir.name).resolve()
    task_ids = [t.strip() for t in args.tasks.split(",") if t.strip()] if args.tasks else None
    index = build(run_dir, out_dir, task_ids=task_ids)
    print(json.dumps({"out": rel(out_dir), "tasks": len(index["tasks"]),
                      "outputs_per_task": index["outputs_per_task"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
