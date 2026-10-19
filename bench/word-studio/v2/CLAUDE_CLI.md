# Blind Claude CLI judge (resumable)

This is an automation for the already-frozen Word Studio v2 blind packets, not a new model benchmark or a claimed quality result.

Use Claude Code CLI on a machine with an authenticated Claude session. It requires the newer CLI options `--safe-mode`, `--json-schema` and `--disallowedTools`. The model should be a fully versioned Claude model ID, held constant across the run.

From `bench/word-studio`, with the existing score template and packets:

```sh
python3 -m v2.claude_batch_judge \
  --judging v2/judging/2026-10-16T1933Z-screen-0dd011b \
  --model YOUR_VERSIONED_CLAUDE_MODEL_ID --dry-run

python3 -m v2.claude_batch_judge \
  --judging v2/judging/2026-10-16T1933Z-screen-0dd011b \
  --model YOUR_VERSIONED_CLAUDE_MODEL_ID --limit 2

python3 -m v2.claude_batch_judge \
  --judging v2/judging/2026-10-16T1933Z-screen-0dd011b \
  --model YOUR_VERSIONED_CLAUDE_MODEL_ID

python3 -m v2.aggregate \
  --judging v2/judging/2026-10-16T1933Z-screen-0dd011b
```

The judge reads only the rubric, anonymized Markdown packet, packet index and score template. It **never opens** the sealed model-identity key or raw model output files. Claude runs from a new temporary directory with `--safe-mode` to disable project customizations and memory, while retaining existing subscription OAuth authentication. Every built-in and MCP tool is explicitly denied via `--disallowedTools "*"`. `--bare` is deliberately not used because it disables OAuth/keychain login; an API key is not necessary just to run the judge. Noninteractive Claude requests may consume a separate subscription allowance or billed API usage depending on the local account's authentication. The collector rejects missing scores, duplicated output letters, invalid numeric labels, changed frozen packets, missing CLI provenance and changed model identities. It verifies the **actual** Claude model reported in `modelUsage` is exactly the requested pinned model, rejecting automatic fallback or unverified metadata.

Every invocation pins `CLAUDE_CODE_EFFORT_LEVEL=high`. That requested effort is recorded in each per-task checkpoint, the score header and session receipt; checkpoints with another effort are rejected. The aggregator verifies the receipt against the model, session digest, packet-index hash and completed score-file hash, then includes the effort level in result metadata.

Claude Code documents this variable as taking precedence over saved effort settings and `/effort`; an organization `maxEffortLevel` cap can still apply ([official environment-variable reference](https://code.claude.com/docs/en/env-vars)). The receipt records the requested setting.

Each task gets an atomic checkpoint under `claude-progress/`; rerunning resumes from saved successful tasks. A completed set writes `scores.jsonl` and a separate Claude session receipt. A malformed result stops the run without guessed scores or a partial official result. The independent `v2.aggregate` step is responsible for the unblinding and raw-output hashes.

**Execution status:** Code and mocked tests only. No authenticated Claude CLI session is available in this ChatGPT environment, so no claims of actual Claude judging, calibrated accuracy or model ranking are made.
