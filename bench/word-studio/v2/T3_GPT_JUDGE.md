# T3 GPT 6.1 Sol blind judging

This runbook imports a completed, owner-authorized GPT 6.1 Sol judgment of the
already-frozen Word Studio v2 blind packets. It does not launch a judge. The
judge must have read only `RUBRIC.md`, `packets/index.json`,
`scores.template.jsonl`, and the anonymized `packets/*.md` files. Keep the
sealed key, candidate run metadata, raw outputs and existing score results out
of the judge's context.

The current issue #87 substitution uses GPT 6.1 Sol through T3 Code at high
reasoning effort and standard service tier. It is a run-specific owner
override; Claude remains the default in the project plan. Do not describe these
scores as Claude-judged. Do not change the frozen rubric or packet files after
judging begins.

Save the completed T3 response JSON and task metadata under a private scratch
directory. Then validate/import it from `bench/word-studio`:

```sh
python3 -m v2.import_t3_judgment \
  --judging v2/judging/<run-id> \
  --response ~/.codex/tmp/<task>/response.json \
  --provider-instance-id <provider-instance-id> \
  --delegated-task-id <delegated-task-id> \
  --child-run-id <child-run-id> --dry-run

python3 -m v2.import_t3_judgment \
  --judging v2/judging/<run-id> \
  --response ~/.codex/tmp/<task>/response.json \
  --provider-instance-id <provider-instance-id> \
  --delegated-task-id <delegated-task-id> \
  --child-run-id <child-run-id>

python3 -m v2.aggregate --judging v2/judging/<run-id>
```

The importer validates exact task/label coverage, score ranges, notes for zero
labels, rubric/index commitments and every packet hash. It copies the frozen
task IDs, anonymous labels, output references and raw-output hashes from the
template. The receipt binds the T3 provider instance, delegated task, child run,
high effort, standard service tier, input-response SHA-256, packet-index hash
and final score-file hash. The aggregator then verifies every raw-output hash,
recomputes hard checks, checks score coverage and writes rankings only if all
evidence matches.

The receipt records requested run settings and T3 task provenance. It does not
claim hidden server-side compute settings beyond what T3 task metadata reports.
