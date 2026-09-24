"""Build Pari English Core tasks for SemanticQA lexical-collocation categorization (LCC).

Research protocol
-----------------
SemanticQA (ACL 2026) evaluates lexical-collocation categorization (LCC) with
accuracy/F1 and reports a 305-item LCC test. The benchmark provides a zero-shot
prompt plus 8-category taxonomy and distributes prepared benchmark data in
resources/dataset.zip.

This adapter deliberately does not copy SemanticQA data into Pari. It consumes a
local checkout of a pinned SemanticQA revision and extracts the exact LCC test
member from the official dataset.zip. Promotion mode requires:
  * a clean SemanticQA checkout at the pinned commit;
  * the official dataset.zip from that checkout;
  * exactly one 305-row, 8-label LCC TSV candidate in the archive;
  * the official zero-shot prompt and 8-category zero-shot taxonomy from the
    same checkout.

The rendered prompt follows SemanticQA's load_taxonomy(..., shot_num=0) behavior
and official prompt template. The answer key is kept separate from model-visible
JSONL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
import zipfile
from collections import Counter
from pathlib import Path

PINNED_SEMANTICQA_COMMIT = "56c82a587f4a6cef609255cd10af372d8c76600a"
PROMPT_REL = Path("semantic_qa/prompts/collocation_categorization_zeroshot.txt")
TAXONOMY_REL = Path("semantic_qa/taxonomy/SEM_REL_CATEGORY_8_0-shots.txt")
ARCHIVE_REL = Path("resources/dataset.zip")
EXPECTED_TEST_SIZE = 305
LABELS = ("Magn", "AntiMagn", "Ver", "AntiVer", "Bon", "AntiBon", "Son", "Oper1")
LABEL_SET = set(LABELS)
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def git(checkout: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=checkout, text=True, stderr=subprocess.STDOUT).strip()


def semanticqa_zero_shot_taxonomy(raw: str) -> str:
    """Mirror SemanticQA semantic_qa/utils.py load_taxonomy(..., shot_num=0)."""
    out: list[str] = []
    for line in raw.splitlines(keepends=True):
        items = line.split("\t")
        if len(items) == 2:
            out.append(items[0] + "\t" + items[1])
        elif len(items) == 3:
            out.append(items[0] + "\t" + items[2])
        elif len(items) == 4:
            out.append(items[1] + "\t" + items[3])
    return "".join(out).replace("Semantic Gloss", "Meaning")


def parse_lcc_tsv(data: bytes) -> list[dict]:
    text = data.decode("utf-8")
    rows: list[dict] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 7:
            continue
        id_, base, collocate, collocation, label, label_id, context = [p.strip() for p in parts]
        if label not in LABEL_SET:
            continue
        rows.append({
            "sourceId": id_,
            "base": base,
            "collocate": collocate,
            "collocation": collocation,
            "label": label,
            "labelId": label_id,
            "context": context,
        })
    return rows


def find_lcc_member(zf: zipfile.ZipFile, explicit: str | None) -> tuple[str, bytes, list[dict], list[dict]]:
    candidates: list[dict] = []
    names = [explicit] if explicit else zf.namelist()
    for name in names:
        if not name or name.endswith("/"):
            continue
        if explicit and name not in zf.namelist():
            raise SystemExit(f"Dataset member not found in archive: {name}")
        if not name.lower().endswith((".tsv", ".txt")):
            continue
        try:
            raw = zf.read(name)
            rows = parse_lcc_tsv(raw)
        except (UnicodeDecodeError, KeyError):
            continue
        if not rows:
            continue
        labels = sorted(set(r["label"] for r in rows))
        row = {"member": name, "rows": len(rows), "labels": labels, "sha256": sha256_bytes(raw)}
        candidates.append(row)
        if explicit:
            if len(rows) != EXPECTED_TEST_SIZE or set(labels) != LABEL_SET:
                raise SystemExit(f"Explicit dataset member is not the expected 305-item 8-label SemanticQA LCC test: {row}")
            return name, raw, rows, candidates

    exact = [c for c in candidates if c["rows"] == EXPECTED_TEST_SIZE and set(c["labels"]) == LABEL_SET]
    if len(exact) != 1:
        preview = json.dumps(exact[:20] if exact else candidates[:20], indent=2)
        raise SystemExit(
            "Could not uniquely identify the SemanticQA 305-item 8-category LCC test inside dataset.zip. "
            "Pass --dataset-member explicitly after inspecting the archive. Candidates:\n" + preview
        )
    selected = exact[0]
    raw = zf.read(selected["member"])
    rows = parse_lcc_tsv(raw)
    return selected["member"], raw, rows, candidates


def render_prompt(template: str, taxonomy: str, context: str, collocation: str) -> str:
    rendered = template.replace("{{taxonomy}}", taxonomy)
    rendered = rendered.replace("{{context}}", context)
    rendered = rendered.replace("{{collocation}}", collocation)
    if "{{" in rendered or "}}" in rendered:
        raise SystemExit("Unresolved SemanticQA prompt placeholders remain after rendering")
    return rendered


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--semanticqa-checkout", required=True, type=Path)
    ap.add_argument("--dataset-member", default=None, help="Optional explicit member path inside resources/dataset.zip")
    ap.add_argument("--tasks", default="semanticqa-lcc-english-core.jsonl", type=Path)
    ap.add_argument("--answers", default="semanticqa-lcc-english-core.answers.json", type=Path)
    ap.add_argument("--manifest", default="semanticqa-lcc-english-core.manifest.json", type=Path)
    ap.add_argument("--promotion", action="store_true", help="Require pinned clean SemanticQA checkout and frozen official assets")
    args = ap.parse_args()

    checkout = args.semanticqa_checkout.expanduser().resolve()
    if not checkout.is_dir():
        raise SystemExit(f"Missing SemanticQA checkout: {checkout}")

    commit = git(checkout, "rev-parse", "HEAD").lower()
    dirty = bool(git(checkout, "status", "--porcelain"))
    if args.promotion:
        if not SHA40_RE.fullmatch(commit):
            raise SystemExit("Could not resolve an immutable SemanticQA Git commit")
        if commit != PINNED_SEMANTICQA_COMMIT:
            raise SystemExit(f"Promotion LCC build requires SemanticQA {PINNED_SEMANTICQA_COMMIT}; got {commit}")
        if dirty:
            raise SystemExit("Promotion LCC build requires a clean SemanticQA checkout")

    prompt_path = checkout / PROMPT_REL
    taxonomy_path = checkout / TAXONOMY_REL
    archive_path = checkout / ARCHIVE_REL
    for p in (prompt_path, taxonomy_path, archive_path):
        if not p.is_file():
            raise SystemExit(f"Missing required SemanticQA asset: {p}")

    template_bytes = prompt_path.read_bytes()
    taxonomy_bytes = taxonomy_path.read_bytes()
    template = template_bytes.decode("utf-8")
    taxonomy = semanticqa_zero_shot_taxonomy(taxonomy_bytes.decode("utf-8"))

    taxonomy_labels = []
    for line in taxonomy.splitlines():
        if not line.strip():
            continue
        label = line.split("\t", 1)[0].strip()
        if label in LABEL_SET:
            taxonomy_labels.append(label)
    if set(taxonomy_labels) != LABEL_SET or len(set(taxonomy_labels)) != 8:
        raise SystemExit(f"Unexpected SemanticQA zero-shot 8-category taxonomy labels: {taxonomy_labels}")

    archive_bytes = archive_path.read_bytes()
    with zipfile.ZipFile(archive_path) as zf:
        member, member_bytes, rows, candidates = find_lcc_member(zf, args.dataset_member)

    if len(rows) != EXPECTED_TEST_SIZE:
        raise SystemExit(f"Expected {EXPECTED_TEST_SIZE} SemanticQA LCC rows; got {len(rows)}")
    counts = Counter(r["label"] for r in rows)
    if set(counts) != LABEL_SET:
        raise SystemExit(f"Unexpected SemanticQA LCC label set: {sorted(counts)}")

    tasks = []
    answers = []
    seen_ids: set[str] = set()
    for index, row in enumerate(rows):
        task_id = f"semanticqa_lcc_{index:03d}"
        if task_id in seen_ids:
            raise SystemExit(f"Duplicate generated task id: {task_id}")
        seen_ids.add(task_id)
        prompt = render_prompt(template, taxonomy, row["context"], row["collocation"])
        tasks.append({
            "id": task_id,
            "dimension": "collocation_naturalness",
            "benchmark": "SemanticQA-LCC-8cat",
            "generative": False,
            "prompt": prompt,
        })
        answers.append({
            "id": task_id,
            "label": row["label"],
            "sourceId": row["sourceId"],
            "collocation": row["collocation"],
        })

    task_text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in tasks)
    answer_obj = {
        "version": 1,
        "benchmark": "SemanticQA LCC 8-category zero-shot",
        "sourceCommit": commit,
        "datasetMember": member,
        "labels": list(LABELS),
        "answers": answers,
    }
    args.tasks.write_text(task_text, encoding="utf-8")
    args.answers.write_text(json.dumps(answer_obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    manifest = {
        "version": 1,
        "benchmark": "SemanticQA LCC 8-category zero-shot",
        "researchReference": "ACL 2026: Revisiting a Pain in the Neck: A Semantic Reasoning Benchmark for Language Models",
        "sourceRepository": "jacklanda/SemanticQA",
        "sourceCommit": commit,
        "pinnedPromotionCommit": PINNED_SEMANTICQA_COMMIT,
        "checkoutDirty": dirty,
        "promotionBuild": args.promotion,
        "protocol": {
            "task": "Lexical Collocation Categorization (LCC)",
            "taxonomyCategories": 8,
            "testSize": EXPECTED_TEST_SIZE,
            "shotCount": 0,
            "metrics": ["accuracy", "macro_f1", "micro_f1", "weighted_f1"],
            "note": "Prompt and taxonomy are rendered from the official SemanticQA zero-shot files. The 305-item test is extracted from the official resources/dataset.zip distribution.",
        },
        "assets": {
            "datasetZip": {"path": str(ARCHIVE_REL), "sha256": sha256_bytes(archive_bytes)},
            "datasetMember": {"path": member, "sha256": sha256_bytes(member_bytes)},
            "prompt": {"path": str(PROMPT_REL), "sha256": sha256_bytes(template_bytes)},
            "taxonomy": {"path": str(TAXONOMY_REL), "sha256": sha256_bytes(taxonomy_bytes)},
            "renderedTaxonomySha256": sha256_bytes(taxonomy.encode("utf-8")),
        },
        "labelCounts": dict(sorted(counts.items())),
        "taskFile": str(args.tasks.resolve()),
        "taskFileSha256": sha256_bytes(task_text.encode("utf-8")),
        "answerFile": str(args.answers.resolve()),
        "answerFileSha256": sha256_file(args.answers),
        "candidateScan": candidates,
        "generatedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "claimScope": "Modern prompted LLM collocation-semantic classification evidence. Report separately from the EACL 2021 native supervised/retrieval protocols and from Pari shadow collocation cases.",
    }
    args.manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Built {len(tasks)} SemanticQA LCC tasks -> {args.tasks}")
    print(f"Answers -> {args.answers}")
    print(f"Manifest -> {args.manifest}")


if __name__ == "__main__":
    main()
