# Pari benchmark catalogue

Use this page to choose the benchmark that matches the question. These suites
serve different purposes; results from one should not be substituted for
another or treated as proof of production behavior.

- [`eval/`](eval/) — fast regression fixtures and mechanical safety metrics.
- [`llm-shootout/`](llm-shootout/README.md) — local model-generation and
  editing-model experiments.
- [`paraphrase-v2/`](paraphrase-v2/README.md) — product-quality comparison of
  paragraph rewrites, with separate meaning, fluency, and human-review
  evidence.
- [`quillbot/`](quillbot/README.md) — frozen external-reference corpus and
  comparison workflow.
- [`strength-sweep/`](strength-sweep/README.md) — adversarial synthetic
  paragraphs evaluated across rewrite-slider regimes, including Qwen3.5 MTP
  output and speed experiments.

The strength-sweep folder contains scripts, synthetic input, raw output,
summaries, and run manifests. It intentionally excludes local model weights,
Python bytecode caches, and the private answer key for blinded human review.
