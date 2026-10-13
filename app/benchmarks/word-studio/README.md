# Word Studio benchmark

This directory is the portable Word Studio evaluation and runtime lane from PR #26, relocated under `app/benchmarks/word-studio` so it follows the production app layout.

## Suites

- `interactive.seed.json` and `word-studio-synthetic.seed.json` are the tracked seeds.
- `build-word-studio-transform-suite.py` builds the 100-case transform suite.
- `build-word-studio-strength-suite.py` builds the private strength suite at 15/40/60/90.
- `v1-suite-config.json` and `v1-prompt-contracts.json` define the product contract.
- `word_studio_output_parser.py` is the shared typed-output, duplicate, protected-content, and streaming-depth contract.
- `word_studio_human_eval.py` and `build-word-studio-human-eval.py` provide blinded human-review packets.

## Runtime

The Kaggle runners are pinned and separate from scoring. `run-kaggle-roster.py` is the normal roster entry point; the vLLM and Prism runners are explicit alternatives. `run-kaggle-vllm-streaming-latency.py` measures first 1/3/10 usable candidates. `studio_backend/` contains the model-agnostic local service contract.

## CPU self-check

From this directory:

```bash
python3 -m unittest discover -p 'test_*.py'
python3 build-word-studio-transform-suite.py --output /tmp/word-studio-transform.jsonl --manifest /tmp/word-studio-transform.manifest.json --private-review-key /tmp/word-studio-transform.review.json
```

Tests are CPU-only and do not require model weights, Kaggle credentials, or network access. Keep generated outputs and private review keys out of version control.

## Scope

This port intentionally excludes the English Core lane, provenance/audit lane, old runbooks, and other parked work from PR #26. The server ownership check is retained only as a dependency of the explicit vLLM latency runner; it must still fail closed on model identity mismatch.
