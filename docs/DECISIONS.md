# Decisions

Newest first. Each entry says what was decided, by whom, and why.

## 2026-10-20: Claude Opus judges the #87 screen (owner)

- The owner allowed Claude Opus at high effort for the blind judging, with a
  modest number of calls. The Claude CLI is now signed in, so the screen is
  judged as the plan says: `v2.claude_batch_judge` with `claude-opus-5-5`, one
  fresh call per task (40), each seeing only the rubric and one packet.
- The 2026-10-19 GPT 6.1 Sol judgment was not imported. It stays in T3 and
  could later serve as a second, cross-family opinion.
- Results now show error bars clustered by source paragraph and the paired
  gap to the leader (Miller 2024, arXiv:2411.00640). This was added before any
  score was read. A gap whose interval includes 0 goes to the full set.

## 2026-10-18: issue #87 judge substitution for this run (owner)

- The plan names Claude as the blind judge. The owner directed GPT 6.1 Sol at
  high effort through T3 Code for the existing frozen #87 screen, because the
  available Claude CLI was not authenticated.
- This is scoped to this run; future benchmark runs still follow the plan's
  Claude requirement unless the owner changes it. The score header and
  `judge-session-receipt.json` must name GPT/T3 accurately, including its
  provider instance, delegated task and child run.
- Keep the rubric, packet index and anonymized packets unchanged. Treat the
  ranking as unverified until the response passes import and full aggregation
  against the raw-output hashes. No score is calibrated or replaced with a
  fallback.

## 2026-10-15: plan reset (owner)

Recorded in [`PLAN.md`](PLAN.md) and pinned issue #93. It supersedes #71.

- Product: a Mac writing assistant for essays. It has a tap-word popover and a
  Word Lab panel (word → sentences, sentence → fewer words). The writer picks
  every final word.
- Runtime: the end state is a quantized model on the 16 GB Mac. This reverses
  the 2026-10-07 rule against local-generator work.
- Compute: Kaggle is primary. Modal's $30/month credits are overflow for
  fine-tuning only.
- Quality: Claude writes the benchmark and judges it blind. The old plan had a
  judge model on Kaggle and no human review.
- Training: quantize the winner by default. Distill only if big open models
  easily beat it. Distillation data is owner-only.
- After the 30 s buffer, only options at the top of a list may be swapped, and
  only when they fall below the relevance bar set from benchmark data. Lower
  options never move. (Owner delegated this rule.)
- PR #82's benchmark, stability and fine-tune results were fabricated. Its Kaggle log shows
  every live model failed to load (`unexpected keyword argument 'timeout'`)
  and the script reported hardcoded fallback scores. The results were removed,
  and #34, #31 and #75 were reopened.
- The repo was cleaned in place. Old experiments are on branch
  `archive/2026-10` and tag `archive-2026-10`.
