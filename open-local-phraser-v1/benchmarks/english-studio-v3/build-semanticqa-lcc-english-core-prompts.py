"""Build Pari English Core tasks from SemanticQA's official zero-shot LCC files.

This adapter does not vendor SemanticQA data. Point it at a local checkout of the
official repository and at the extracted LCC test TSV from `resources/dataset.zip`.
It reproduces SemanticQA's zero-shot prompt construction while keeping gold labels
out of the model-visible JSONL.

Promotion-quality example:

    python build-semanticqa-lcc-english-core-prompts.py \
      /path/to/SemanticQA \
      /path/to/extracted/collocation_categorization_prepared.tsv \
      semanticqa-lcc-prompts.jsonl \
      --require-promotion-provenance

The currently audited SemanticQA revision is pinned below. A different revision
requires a fresh protocol/data audit before it should support promotion claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path

AUDITED_REVISION = "56c82a587f4a6cef609255cd10af372d8c76600a"
EXPECTED_MAIN_CASES = 305
EXPECTED_LABELS = [
    "Magn",
    "AntiMagn",
    "Ver",
    "AntiVer",
    "Bon",
    "AntiBon",
    "Son",
    "Oper1",
]
PROMPT_RELATIVE = Path("semantic_qa/prompts/collocation_categorization_zeroshot.txt")
TAXONOMY_RELATIVE = Path("semantic_qa/taxonomy/SEM_REL_CATEGORY_8_0-shots.txt")
ARCHIVE_RELATIVE = Path("resources/dataset.zip")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def git_head(repo: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip() or None
    except Exception:
        return None


def git_dirty(repo: Path) -> bool | None:
    try:
        return bool(subprocess.check_output(
            ["git", "-C", str(repo), "status", "--porcelain"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip())
    except Exception:
        return None


def load_zero_shot_taxonomy(path: Path) -> tuple[str, list[str]]:
    """Replicate SemanticQA utils.load_taxonomy(..., shot_num=0)."""
    taxonomy = ""
    labels: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines(keepends=True):
        items = raw.split("\t")
        rendered = None
        label = None
        if len(items) == 2:
            rendered = items[0] + "\t" + items[1]
            label = items[0].strip()
        elif len(items) == 3:
            rendered = items[0] + "\t" + items[2]
            label = items[0].strip()
        elif len(items) == 4:
            rendered = items[1] + "\t" + items[3]
            label = items[1].strip()
        if rendered is not None:
            taxonomy += rendered
        if label and label.lower() not in {"label", "id"}:
            labels.append(label)
    taxonomy = taxonomy.replace("Semantic Gloss", "Meaning")
    labels = list(dict.fromkeys(labels))
    return taxonomy, labels


def load_lcc_test(path: Path) -> list[dict]:
    rows = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        fields = raw.split("\t")
        if len(fields) != 7:
            raise SystemExit(f"LCC test line {line_no} has {len(fields)} TSV fields; SemanticQA loader expects 7")
        id_, base, collocate, collocation, label, label_id, context = fields
        rows.append({
            "source_id": id_.strip(),
            "base": base.strip(),
            "collocate": collocate.strip(),
            "collocation": collocation.strip(),
            "label": label.strip(),
            "label_id": label_id.strip(),
            "context": context.strip(),
        })
    return rows


def find_archive_member_with_bytes(archive: Path, expected_bytes: bytes) -> tuple[str | None, list[str]]:
    expected_hash = sha256_bytes(expected_bytes)
    hash_matches: list[str] = []
    with zipfile.ZipFile(archive, "r") as zf:
        for info in zf.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".tsv"):
                continue
            data = zf.read(info)
            if sha256_bytes(data) == expected_hash:
                hash_matches.append(info.filename)
    return (hash_matches[0] if len(hash_matches) == 1 else None), hash_matches


def render_prompt(template: str, taxonomy: str, context: str, collocation: str) -> str:
    prompt = template.replace("{{taxonomy}}", taxonomy)
    prompt = prompt.replace("{{context}}", context)
    prompt = prompt.replace("{{collocation}}", collocation)
    if re.search(r"{{[^}]+}}", prompt):
        raise SystemExit("Official SemanticQA LCC prompt contains unresolved template variables")
    return prompt


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("semanticqa_repo", help="Local checkout of jacklanda/SemanticQA")
    ap.add_argument("test_tsv", help="Extracted main LCC test TSV from official resources/dataset.zip")
    ap.add_argument("out_jsonl")
    ap.add_argument("--prompt", default=None, help="Override official zero-shot prompt path for exploration only")
    ap.add_argument("--taxonomy", default=None, help="Override official 8-category zero-shot taxonomy path for exploration only")
    ap.add_argument("--answers", default=None, help="Output gold-answer JSON; defaults next to out_jsonl")
    ap.add_argument("--require-promotion-provenance", action="store_true")
    args = ap.parse_args()

    repo = Path(args.semanticqa_repo).expanduser().resolve()
    test = Path(args.test_tsv).expanduser().resolve()
    out = Path(args.out_jsonl).expanduser().resolve()
    prompt = Path(args.prompt).expanduser().resolve() if args.prompt else (repo / PROMPT_RELATIVE)
    taxonomy_path = Path(args.taxonomy).expanduser().resolve() if args.taxonomy else (repo / TAXONOMY_RELATIVE)
    archive = repo / ARCHIVE_RELATIVE
    answers = Path(args.answers).expanduser().resolve() if args.answers else out.with_suffix(out.suffix + ".answers.json")

    for label, path in [("SemanticQA repo", repo), ("LCC test", test), ("prompt", prompt), ("taxonomy", taxonomy_path), ("dataset archive", archive)]:
        exists = path.is_dir() if label == "SemanticQA repo" else path.is_file()
        if not exists:
            raise SystemExit(f"Missing {label}: {path}")

    revision = git_head(repo)
    dirty = git_dirty(repo)
    promotion_errors: list[str] = []
    if revision != AUDITED_REVISION:
        promotion_errors.append(f"semanticqa_revision_not_audited_commit:{revision}")
    if dirty is None:
        promotion_errors.append("semanticqa_worktree_cleanliness_unknown")
    elif dirty:
        promotion_errors.append("semanticqa_checkout_dirty")
    if prompt != (repo / PROMPT_RELATIVE).resolve():
        promotion_errors.append("noncanonical_prompt_path")
    if taxonomy_path != (repo / TAXONOMY_RELATIVE).resolve():
        promotion_errors.append("noncanonical_taxonomy_path")

    template = prompt.read_text(encoding="utf-8")
    taxonomy, taxonomy_labels = load_zero_shot_taxonomy(taxonomy_path)
    if taxonomy_labels != EXPECTED_LABELS:
        promotion_errors.append(f"unexpected_taxonomy_labels:{taxonomy_labels}")

    rows = load_lcc_test(test)
    if len(rows) != EXPECTED_MAIN_CASES:
        promotion_errors.append(f"unexpected_main_lcc_case_count:{len(rows)}")
    unknown_gold = sorted({row["label"] for row in rows} - set(EXPECTED_LABELS))
    if unknown_gold:
        promotion_errors.append(f"unknown_gold_labels:{unknown_gold}")

    test_bytes = test.read_bytes()
    archive_member, archive_matches = find_archive_member_with_bytes(archive, test_bytes)
    if archive_member is None:
        promotion_errors.append(f"test_bytes_not_uniquely_found_in_official_dataset_zip:matches={len(archive_matches)}")

    if args.require_promotion_provenance and promotion_errors:
        raise SystemExit("SemanticQA LCC promotion provenance failed:\n- " + "\n- ".join(promotion_errors))

    tasks = []
    answer_map = {}
    for i, row in enumerate(rows):
        task_id = f"semanticqa-lcc-{i:04d}"
        tasks.append({
            "id": task_id,
            "dimension": "collocation_naturalness",
            "source": "SemanticQA-LCC-ACL2026",
            "task": "semanticqa_lcc_zero_shot",
            "generative": False,
            "phenomenon": row["label"],
            "prompt": render_prompt(template, taxonomy, row["context"], row["collocation"]),
            "metadata": {
                "sourceId": row["source_id"],
                "base": row["base"],
                "collocate": row["collocate"],
                "collocation": row["collocation"],
                "labelId": row["label_id"],
            },
        })
        answer_map[task_id] = row["label"]

    ids = [row["id"] for row in tasks]
    if len(ids) != len(set(ids)):
        raise SystemExit("Generated SemanticQA LCC task IDs are not unique")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in tasks) + "\n", encoding="utf-8")
    answers.write_text(json.dumps({
        "version": 1,
        "source": "SemanticQA ACL 2026 LCC main 8-category test",
        "labels": EXPECTED_LABELS,
        "answers": answer_map,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = out.with_suffix(out.suffix + ".manifest.json")
    manifest.write_text(json.dumps({
        "version": 1,
        "protocol": "SemanticQA ACL 2026 Lexical Collocation Categorization, main 8-category zero-shot lane",
        "researchReference": "https://aclanthology.org/2026.acl-long.210/",
        "sourceConstructReference": "https://aclanthology.org/2021.eacl-main.120/",
        "officialRepository": "https://github.com/jacklanda/SemanticQA",
        "auditedRepositoryRevision": AUDITED_REVISION,
        "actualRepositoryRevision": revision,
        "worktreeDirty": dirty,
        "datasetArchive": str(archive),
        "datasetArchiveSha256": sha256(archive),
        "testFile": str(test),
        "testFileSha256": sha256(test),
        "testArchiveMember": archive_member,
        "testArchiveMatchingMembers": archive_matches,
        "promptFile": str(prompt),
        "promptFileSha256": sha256(prompt),
        "taxonomyFile": str(taxonomy_path),
        "taxonomyFileSha256": sha256(taxonomy_path),
        "taxonomyLabels": taxonomy_labels,
        "cases": len(tasks),
        "expectedCases": EXPECTED_MAIN_CASES,
        "taskFile": str(out),
        "taskFileSha256": sha256(out),
        "answerFile": str(answers),
        "answerFileSha256": sha256(answers),
        "promotionProvenanceErrors": promotion_errors,
        "promotionProvenanceReady": not promotion_errors,
        "notes": [
            "The zero-shot taxonomy is rendered with the same demo-removal logic as SemanticQA utils.load_taxonomy(..., shot_num=0).",
            "Gold labels are written only to the separate answer file, never to the model-visible task JSONL.",
            "Promotion provenance verifies that the supplied test TSV is byte-identical to exactly one TSV member of the pinned repository's resources/dataset.zip.",
            "This is the modern prompt-based SemanticQA LCC protocol. It must not be relabeled as the supervised EACL 2021 native categorization score.",
            "The 16-category SemanticQA scaling lane is a separate robustness diagnostic and is not substituted for this main 8-category/305-case result."
        ],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "cases": len(tasks),
        "labels": taxonomy_labels,
        "out": str(out),
        "answers": str(answers),
        "manifest": str(manifest),
        "testArchiveMember": archive_member,
        "promotionProvenanceReady": not promotion_errors,
        "promotionProvenanceErrors": promotion_errors,
    }, indent=2))


if __name__ == "__main__":
    main()
