# Decisions

Newest first. Each entry says what was decided, by whom, and why.

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
