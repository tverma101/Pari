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

Issue #66 requires executable fidelity, not prose. This converter therefore prefers
the pinned official postprocessor imported from a verified SemanticQA checkout
(``--semanticqa-checkout``); the local mirror is used only when no checkout is
supplied, and that fallback is recorded in the manifest as non-official. Either way
the manifest binds the frozen conversion protocol
(`pari-semanticqa-lcc-postprocess` v1), this script's SHA-256, the postprocessor
source actually used, the full conversion config, and the Pari benchmark
commit/tree. ``predictionPolicy`` prose is documentation only; it is never
accepted as proof that the implementation is faithful.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from english_core_converter_provenance import (  # noqa: E402
    SEMANTICQA_PROTOCOL_ID,
    build_converter_provenance,
    registered_protocol,
)

PINNED_COMMIT = "56c82a587f4a6cef609255cd10af372d8c76600a"
PROTOCOL_VERSION = 1
OFFICIAL_DATA_UTILS_REL = Path("semantic_qa") / "data_utils.py"
TASK_ARG = "collocation-categorization"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def semanticqa_lcc_postprocess(text: str) -> str:
    """Local mirror of pinned ``data_utils.postprocess`` for the LCC task.

    Equivalent to official lines 1163-1173: unconditional whitespace normalization,
    then an ``if "is: "`` / ``elif "Output:"`` marker split taking the *last*
    occurrence and stripping only the suffix. This function is the fallback used
    when no verified official checkout is supplied; see
    ``load_official_postprocess``.
    """
    s = " ".join(str(text or "").split())
    if "is: " in s:
        s = s.split("is: ")[-1].strip()
    elif "Output:" in s:
        s = s.split("Output:")[-1].strip()
    return s


def load_official_postprocess(checkout: Path, task: str = TASK_ARG):
    """Import the pinned official postprocessor from a verified checkout.

    Returns ``(callable, provenance_dict)``. Raises ``SystemExit`` when the checkout
    cannot be verified, so a promotion run can never silently fall back to the
    local mirror.
    """
    checkout = Path(checkout).expanduser().resolve()
    if not checkout.is_dir():
        raise SystemExit(f"Missing SemanticQA checkout: {checkout}")

    def git(*args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(checkout), *args], text=True, stderr=subprocess.STDOUT
        ).strip()

    commit = git("rev-parse", "HEAD").lower()
    dirty = bool(git("status", "--porcelain"))
    if commit != PINNED_COMMIT:
        raise SystemExit(
            f"Official SemanticQA postprocessor requires commit {PINNED_COMMIT}; got {commit}"
        )
    if dirty:
        raise SystemExit(
            "Official SemanticQA postprocessor requires a clean checkout"
        )

    data_utils = checkout / OFFICIAL_DATA_UTILS_REL
    if not data_utils.is_file():
        raise SystemExit(f"Missing official postprocessor module: {data_utils}")

    spec = importlib.util.spec_from_file_location(
        "pari_semanticqa_official_data_utils", data_utils
    )
    if spec is None or spec.loader is None:
        raise SystemExit(f"Cannot load official postprocessor module: {data_utils}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    postprocess = getattr(module, "postprocess", None)
    if postprocess is None:
        raise SystemExit(
            f"Official module {data_utils} does not define postprocess()"
        )

    def call(text: str) -> str:
        return postprocess(str(text or ""), task)

    return call, {
        "kind": "official-pinned-import",
        "checkout": str(checkout),
        "commit": commit,
        "clean": not dirty,
        "modulePath": str(OFFICIAL_DATA_UTILS_REL),
        "moduleSha256": sha256_bytes(data_utils.read_bytes()),
        "taskArgument": task,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("result", type=Path)
    ap.add_argument("--tasks", required=True, type=Path)
    ap.add_argument("--answers", required=True, type=Path)
    ap.add_argument("--build-manifest", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument(
        "--semanticqa-checkout",
        type=Path,
        default=None,
        help="Verified SemanticQA checkout used to import the official postprocessor (required for promotion conversion)",
    )
    ap.add_argument(
        "--require-promotion-provenance",
        action="store_true",
        help="Fail unless the official postprocessor is imported from a verified checkout and converter provenance is complete",
    )
    args = ap.parse_args()

    if args.semanticqa_checkout is not None:
        postprocess, postprocessor_provenance = load_official_postprocess(args.semanticqa_checkout)
    else:
        postprocess = semanticqa_lcc_postprocess
        postprocessor_provenance = {
            "kind": "local-mirror",
            "checkout": None,
            "commit": None,
            "clean": None,
            "modulePath": str(OFFICIAL_DATA_UTILS_REL),
            "moduleSha256": None,
            "taskArgument": TASK_ARG,
            "fidelity": (
                "Local mirror only. Not executable proof of official fidelity; promotion "
                "conversion requires --semanticqa-checkout or a hash-bound conformance fixture."
            ),
        }

    provenance_errors: list[str] = []
    # This is recorded unconditionally, not only under --require-promotion-provenance:
    # a manifest that claims promotion readiness while built from the local mirror
    # is exactly the self-authenticating prose #66 forbids.
    if postprocessor_provenance["kind"] != "official-pinned-import":
        provenance_errors.append("official_semanticqa_postprocessor_not_imported_from_pinned_checkout")

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
    is_marker_rows = 0
    output_marker_rows = 0
    for task_id in task_ids:
        ans = answer_map[task_id]
        raw = str(output_map[task_id].get("output", ""))
        normalized = " ".join(raw.split())
        if "is: " in normalized:
            is_marker_rows += 1
        elif "Output:" in normalized:
            output_marker_rows += 1
        prediction = postprocess(raw)
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

    coverage = {
        "cases": len(converted),
        "convertedRows": len(converted),
        "missingOutputs": 0,
        "extraOutputs": 0,
        "emptyOutputs": sum(1 for row in converted if row["prediction"] == ""),
        "postprocessChangedOutputs": postprocess_changed,
        "isMarkerRows": is_marker_rows,
        "outputMarkerRows": output_marker_rows,
    }
    conversion_config = {
        "postprocessorSource": postprocessor_provenance["kind"],
        "postprocessorCommit": postprocessor_provenance.get("commit"),
        "postprocessorModuleSha256": postprocessor_provenance.get("moduleSha256"),
    }
    converter_provenance = build_converter_provenance(
        benchmark="semanticqa_lcc",
        protocol_id=SEMANTICQA_PROTOCOL_ID,
        protocol_version=PROTOCOL_VERSION,
        converter_path=Path(__file__),
        conversion_config=conversion_config,
    )
    if not converter_provenance["benchmarkGit"]["available"]:
        provenance_errors.append("benchmark_git_identity_unavailable")

    if args.require_promotion_provenance and provenance_errors:
        raise SystemExit(
            "SemanticQA promotion provenance failed:\n- " + "\n- ".join(provenance_errors)
        )

    manifest = {
        "version": 3,
        "benchmark": "SemanticQA LCC official-protocol conversion",
        "sourceCommit": build_manifest.get("sourceCommit"),
        "taskFileSha256": sha256_bytes(task_bytes),
        "answerFileSha256": sha256_bytes(answer_bytes),
        "buildManifestSha256": sha256_bytes(build_manifest_bytes),
        "modelResultSha256": sha256_bytes(args.result.read_bytes()),
        "convertedFileSha256": sha256_bytes(output_text.encode("utf-8")),
        "cases": len(converted),
        "postprocessChangedOutputs": postprocess_changed,
        "coverage": coverage,
        "isMarkerRows": is_marker_rows,
        "outputMarkerRows": output_marker_rows,
        "conversionStatus": "completed" if not provenance_errors else "completed_with_provenance_errors",
        "terminalStatus": "completed",
        "postprocessor": postprocessor_provenance,
        "converterProvenance": converter_provenance,
        "conversionContract": registered_protocol("semanticqa_lcc", SEMANTICQA_PROTOCOL_ID, PROTOCOL_VERSION)["contract"],
        "promotionProvenanceErrors": provenance_errors,
        "promotionProvenanceReady": not provenance_errors,
        "predictionPolicy": "Documentation only, never proof of fidelity: pinned SemanticQA data_utils.postprocess for collocation-categorization applies whitespace normalization, then takes the suffix after the last 'is: ' if present, else the suffix after the last 'Output:' if present, and performs no other edits. The executable proof is postprocessor + converterProvenance above.",
        "officialPipelineReference": "semantic_qa/main.py calls postprocess(query_llm(...), task, args) before writing prediction; semantic_qa/eval.py then compares prediction and label by exact equality.",
        "generatedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Converted {len(converted)} LCC outputs -> {args.output}")
    print(f"Official postprocess changed {postprocess_changed} outputs")
    print(f"Postprocessor source: {postprocessor_provenance['kind']}")
    print(f"Converter identity: {converter_provenance['identity']}")


if __name__ == "__main__":
    main()
