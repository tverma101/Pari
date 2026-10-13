# Pari

## Current plan

Start from pinned issue #71 (2026-10-07). It supersedes #13, #25 and #28.

- The generator, the benchmark, the judge model and fine-tuning all run on Kaggle (2×T4). The Mac app in `app/` is the front end. Don't add new local-generator work.
- Choose the model with the Word Studio benchmark (#37), scored by a judge model (#73). There is no human review gate.
- Fine-tuning on the user's saved studio edits (`track:fine-tune`: #75, #76) is low priority but planned. Don't close or drop it.
- Keep the studio's choice log (#74) working so the fine-tuning data builds up. Never commit that log: this repository is public.
- Issues labelled `parked` were closed on purpose. Don't reopen them to unblock the tracks.
- Take work from open `agent-ready` issues. Priority follows the labels: `track:benchmark` (P0), then `track:studio` (P1), then `track:fine-tune` (P2).

App-specific rules are in `app/AGENTS.md`.
