#!/usr/bin/env python3
"""Build and verify the frozen Word Studio v2 task sets (#85).

    python3 -m v2.build_tasks          # rebuild tasks/ and the manifest
    python3 -m v2.build_tasks --check  # fail if the committed files differ

Run from ``bench/word-studio``. The source paragraphs live in
``v2/source/paragraphs.json``; prompts come from ``v2/prompts.py``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from v2 import prompts

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "source" / "paragraphs.json"
TASKS_DIR = HERE / "tasks"
MANIFEST = TASKS_DIR / "manifest.json"
SET_FILES = {"screen": TASKS_DIR / "screen.jsonl", "full": TASKS_DIR / "full.jsonl"}

#: The designed size of each set. The builder refuses to write anything else.
SET_TARGETS = {
    "screen": {"tap_word": 12, "word_sentences": 6, "condense": 6, "phrase_to_word": 6, "paraphrase": 5, "academic": 5},
    "full": {"tap_word": 60, "word_sentences": 28, "condense": 28, "phrase_to_word": 28, "paraphrase": 28, "academic": 28},
}

FROZEN_ON = "2026-10-16"

REUSE = {
    "reused": [
        "word_studio_output_parser.py: parse_document, partial_option_values and near_duplicate_keys parse the JSON options, flag wrapper prose and fences, recover options from a partial stream, and find near duplicates.",
        "The JSON {\"options\": [...]} output contract from the v1 suites.",
        "The global rules of v1-prompt-contracts.json: keep facts, negation and certainty; invent nothing; return options only.",
    ],
    "not_reused": [
        "word-studio-transform-suite.jsonl: its sources are short everyday sentences, not essay paragraphs, and its operations (split/join, collocation, a vocabulary ceiling that penalises academic wording) do not match the v1 features, where 'more academic' is now a feature.",
        "word-studio-strength-suite.jsonl: the 15/40/60/90 strength slider is not a v1 feature.",
        "word_studio_human_eval.py: human review packets are replaced by Claude blind judging (#87).",
        "run-kaggle-roster.py and the vLLM/Prism runners: they depend on the archived English Core lane, on a module that no longer exists (kaggle_stage_identity) and on prebuilt runtime locks. v2 uses one Transformers runner (#86).",
    ],
}


class SourceError(ValueError):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def whole_word_matches(text: str, needle: str, *, ignore_case: bool = False) -> list[int]:
    flags = re.IGNORECASE if ignore_case else 0
    pattern = re.compile(r"(?<![\w'-])" + re.escape(needle) + r"(?![\w'-])", flags)
    return [m.start() for m in pattern.finditer(text)]


def _sentence_offsets(sentences: list[str]) -> list[int]:
    offsets, position = [], 0
    for sentence in sentences:
        offsets.append(position)
        position += len(sentence) + 1
    return offsets


def build_records(source: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Turn the source paragraphs into task records, validating as it goes."""
    about = source["about"]
    records: dict[str, list[dict[str, Any]]] = {name: [] for name in SET_FILES}
    seen_ids: set[str] = set()
    sentences_by_set: dict[str, set[str]] = {name: set() for name in SET_FILES}
    for para in source["paragraphs"]:
        pid, set_name = para["id"], para["set"]
        if pid in seen_ids:
            raise SourceError(f"duplicate paragraph id {pid}")
        seen_ids.add(pid)
        if set_name not in SET_FILES:
            raise SourceError(f"{pid}: unknown set {set_name!r}")
        sentences = para["sentences"]
        if len(sentences) < 5:
            raise SourceError(f"{pid}: needs at least five sentences")
        paragraph = " ".join(sentences)
        offsets = _sentence_offsets(sentences)
        sentences_by_set[set_name].update(sentences)
        counters: Counter[str] = Counter()
        for task in para["tasks"]:
            kind = task["kind"]
            if kind not in prompts.TASK_KINDS:
                raise SourceError(f"{pid}: unknown kind {kind!r}")
            counters[kind] += 1
            task_id = f"ws2-{set_name}-{pid}-{kind}-{counters[kind]}"
            record: dict[str, Any] = {
                "id": task_id,
                "set": set_name,
                "paragraph_id": pid,
                "genre": para["genre"],
                "topic": para["topic"],
                "kind": kind,
                "paragraph": paragraph,
                "sentence_index": None,
                "sentence": None,
                "selection": None,
                "word": None,
                "word_origin": None,
                "requested_options": prompts.TASK_KINDS[kind]["options"],
                "max_new_tokens": prompts.TASK_KINDS[kind]["max_new_tokens"],
                "prompt_version": prompts.PROMPT_VERSION,
                "source_license": about["license"],
                "quotes": para.get("quotes", []),
            }
            if kind == "word_sentences":
                word, origin = task.get("word"), task.get("origin")
                if not word or origin not in {"writer", "suggested"}:
                    raise SourceError(f"{task_id}: needs a word and origin writer|suggested")
                in_paragraph = bool(whole_word_matches(paragraph, word, ignore_case=True))
                if (origin == "writer") != in_paragraph:
                    raise SourceError(f"{task_id}: origin {origin} but word in paragraph is {in_paragraph}")
                record.update(word=word, word_origin=origin)
                record["messages"] = prompts.render_messages(kind, paragraph=paragraph, word=word)
            else:
                index = task.get("s")
                if not isinstance(index, int) or not 1 <= index <= len(sentences):
                    raise SourceError(f"{task_id}: sentence index {index!r} out of range")
                sentence = sentences[index - 1]
                record.update(sentence_index=index, sentence=sentence)
                if kind in prompts.SELECTION_KINDS:
                    selected = task.get("select")
                    if not selected:
                        raise SourceError(f"{task_id}: needs 'select'")
                    hits = whole_word_matches(sentence, selected)
                    occurrence = task.get("occurrence")
                    if occurrence is None:
                        if len(hits) != 1:
                            raise SourceError(f"{task_id}: {selected!r} occurs {len(hits)} times; set 'occurrence'")
                        local = hits[0]
                    else:
                        if not 1 <= occurrence <= len(hits):
                            raise SourceError(f"{task_id}: occurrence {occurrence} of {selected!r} not found")
                        local = hits[occurrence - 1]
                    if kind == "phrase_to_word" and len(selected.split()) < 2:
                        raise SourceError(f"{task_id}: a phrase needs at least two words")
                    if kind == "tap_word" and len(selected.split()) != 1:
                        raise SourceError(f"{task_id}: a tapped word must be one word")
                    span = (local, local + len(selected))
                    start = offsets[index - 1] + local
                    record["selection"] = {"text": selected, "start": start, "end": start + len(selected)}
                    record["messages"] = prompts.render_messages(
                        kind, paragraph=paragraph, sentence=sentence, sentence_span=span, selected=selected
                    )
                else:
                    if "select" in task:
                        raise SourceError(f"{task_id}: sentence tasks select the whole sentence")
                    start = offsets[index - 1]
                    record["selection"] = {"text": sentence, "start": start, "end": start + len(sentence)}
                    record["messages"] = prompts.render_messages(kind, paragraph=paragraph, selected=sentence)
                sel = record["selection"]
                if paragraph[sel["start"]:sel["end"]] != sel["text"]:
                    raise SourceError(f"{task_id}: selection offsets do not match the paragraph")
            records[set_name].append(record)
    overlap = sentences_by_set["screen"] & sentences_by_set["full"]
    if overlap:
        raise SourceError(f"screen and full share sentences: {sorted(overlap)[:3]}")
    for set_name, target in SET_TARGETS.items():
        got = Counter(r["kind"] for r in records[set_name])
        if dict(got) != target:
            raise SourceError(f"{set_name}: kind counts {dict(got)} differ from the design {target}")
    for items in records.values():
        items.sort(key=lambda r: r["id"])
    return records


def jsonl_bytes(records: list[dict[str, Any]]) -> bytes:
    lines = [json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for r in records]
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_manifest(source_bytes: bytes, source: dict[str, Any], files: dict[str, bytes],
                   records: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    sets = {}
    for name, data in files.items():
        items = records[name]
        sets[name] = {
            "path": f"tasks/{SET_FILES[name].name}",
            "sha256": sha256_bytes(data),
            "tasks": len(items),
            "paragraphs": len({r["paragraph_id"] for r in items}),
            "kinds": dict(sorted(Counter(r["kind"] for r in items).items())),
            "genres": dict(sorted(Counter(r["genre"] for r in items).items())),
            "requested_options": sum(r["requested_options"] for r in items),
        }
    return {
        "schema_version": 1,
        "benchmark": "word-studio-v2",
        "frozen_on": FROZEN_ON,
        "frozen_before_results": "No candidate output existed when these files were built. Any change to a task, prompt or decoding setting is a new benchmark version.",
        "prompt_version": prompts.PROMPT_VERSION,
        "generation": prompts.GENERATION,
        "task_kinds": prompts.TASK_KINDS,
        "source": {
            "path": "source/paragraphs.json",
            "sha256": sha256_bytes(source_bytes),
            "license": source["about"]["license"],
            "author": source["about"]["author"],
            "quotes": source["about"]["quotes"],
        },
        "sets": sets,
        "screen_and_full_disjoint": "No paragraph or sentence appears in both sets.",
        "reuse": REUSE,
    }


def manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def build() -> tuple[dict[str, bytes], bytes]:
    source_bytes = SOURCE.read_bytes()
    source = json.loads(source_bytes)
    records = build_records(source)
    files = {name: jsonl_bytes(records[name]) for name in SET_FILES}
    manifest = build_manifest(source_bytes, source, files, records)
    return files, manifest_bytes(manifest)


def load_tasks(set_name: str) -> list[dict[str, Any]]:
    """Read a committed task set after checking it against the manifest."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entry = manifest["sets"][set_name]
    data = (HERE / entry["path"]).read_bytes()
    if sha256_bytes(data) != entry["sha256"]:
        raise SourceError(f"{entry['path']} does not match its manifest hash")
    return [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify the committed files instead of writing")
    args = parser.parse_args(argv)
    files, manifest = build()
    targets = {SET_FILES[name]: data for name, data in files.items()}
    targets[MANIFEST] = manifest
    if args.check:
        stale = [str(p.relative_to(HERE)) for p, data in targets.items() if not p.exists() or p.read_bytes() != data]
        if stale:
            print("stale or missing: " + ", ".join(stale), file=sys.stderr)
            return 1
        print("tasks match source, prompts and manifest")
        return 0
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    for path, data in targets.items():
        path.write_bytes(data)
        print(f"wrote {path.relative_to(HERE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
