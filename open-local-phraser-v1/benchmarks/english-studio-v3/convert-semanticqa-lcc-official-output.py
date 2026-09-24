"""Convert a Pari English Core model run into SemanticQA's LCC result JSONL.

Protocol fidelity matters here. SemanticQA's normal benchmark path is:

    query_llm(...) -> postprocess(..., task="collocation-categorization")
    -> result JSONL -> eval.py

The pinned SemanticQA postprocessor first normalizes whitespace, then for LCC:
  * if ``is: `` occurs, keep the suffix after the last occurrence;
  * else if ``Output:`` occurs, keep the suffix after the last occurrence;
  * otherwise keep the whitespace-normalized response.

The official standalone evaluator then compares ``prediction`` with ``label`` by
exact string equality. This converter mirrors that benchmark postprocessing and
nothing broader. Pari's separate tolerant diagnostic scorer may recover a clear
label from additional harmless wrappers, but that diagnostic must never be
relabeled as the official SemanticQA protocol result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def semanticqa_lcc_postprocess(text: str) -> str:
    """Mirror pinned SemanticQA data_utils.postprocess for LCC exactly."""
    s = " ".join(str(text or "").split())
    if "is: " in s:
        s = s.split("is: ")[-1].strip()
    elif "Output:" in s:
        s = s.split("Output:")[-1].strip()
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("result", type=Path)
    ap.add_argument("--tasks", required=True, type=Path)
    ap.add_argument("--answers", required=True, type=Path)
    ap.add_argument("--build-manifest", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    args = ap.parse_args()

    result = load_json(args.result)
    answers_obj = load_json(args.answers)
    build_manifest = load_json(args.build_manifest)
    task_bytes = args.tasks.read_bytes()
    answer_bytes = args.answers.read_bytes()
    build_manifest_bytes = args.build_manifest.read_bytes()

    tasks = [json.loads(line) for line in task_bytes.decode("utf-8").splitlines() if line.strip()]
    task_ids = [row.get("id") for row in tasks]
    if any(not x for x in task_ids) or len(task_ids) != len(set(task_ids)):
        raise SystemExit("Task file contains missing or duplicate IDs")
    if result.get("taskFileSha256") != sha256_bytes(task_bytes):
        raise SystemExit("Model result was not generated from the supplied SemanticQA LCC task file")
    if result.get("taskCount") != len(tasks):
        raise SystemExit("Model result taskCount does not match the supplied task file")
    if build_manifest.get("taskFileSha256") != sha256_bytes(task_bytes):
        raise SystemExit("SemanticQA build manifest/task hash mismatch")
    if build_manifest.get("answerFileSha256") != sha256_bytes(answer_bytes):
        raise SystemExit("SemanticQA build manifest/answer hash mismatch")

    answers = answers_obj.get("answers") or []
    answer_map = {row.get("id"): row for row in answers}
    if len(answer_map) != len(answers) or set(answer_map) != set(task_ids):
        raise SystemExit("SemanticQA answer/task ID mismatch")

    outputs = result.get("outputs") or []
    output_ids = [row.get("id") for row in outputs if isinstance(row, dict)]
    if len(output_ids) != len(outputs) or any(not x for x in output_ids):
        raise SystemExit("Malformed model output rows")
    if len(output_ids) != len(set(output_ids)):
        raise SystemExit("Duplicate model output IDs")
    if set(output_ids) != set(task_ids):
        raise SystemExit("Model output IDs must exactly match SemanticQA task IDs")
    output_map = {row["id"]: row for row in outputs}

    converted = []
    postprocess_changed = 0
    for task_id in task_ids:
        ans = answer_map[task_id]
        raw = str(output_map[task_id].get("output", ""))
        prediction = semanticqa_lcc_postprocess(raw)
        if prediction != raw:
            postprocess_changed += 1
        converted.append({
            "label": ans["label"],
            "prediction": prediction,
            "collocation": ans.get("collocation"),
            "pari_task_id": task_id,
        })

    output_text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in converted)
    args.output.write_text(output_text, encoding="utf-8")
    manifest = {
        "version": 2,
        "benchmark": "SemanticQA LCC official-protocol conversion",
        "sourceCommit": build_manifest.get("sourceCommit"),
        "taskFileSha256": sha256_bytes(task_bytes),
        "answerFileSha256": sha256_bytes(answer_bytes),
        "buildManifestSha256": sha256_bytes(build_manifest_bytes),
        "modelResultSha256": sha256_bytes(args.result.read_bytes()),
        "convertedFileSha256": sha256_bytes(output_text.encode("utf-8")),
        "cases": len(converted),
        "postprocessChangedOutputs": postprocess_changed,
        "predictionPolicy": "Mirror pinned SemanticQA data_utils.postprocess for collocation-categorization: whitespace normalization, then suffix after 'is: ' if present, else suffix after 'Output:' if present; no broader Pari label recovery.",
        "officialPipelineReference": "semantic_qa/main.py calls postprocess(query_llm(...), task, args) before writing prediction; semantic_qa/eval.py then compares prediction and label by exact equality.",
        "generatedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Converted {len(converted)} LCC outputs -> {args.output}")
    print(f"Official postprocess changed {postprocess_changed} outputs")


if __name__ == "__main__":
    main()
