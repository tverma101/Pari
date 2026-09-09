# Local model receipts for Pari Paraphrase Quality Benchmark v2

This file records why each model belongs in the benchmark. It is a **receipt sheet, not a ranking**. Generic benchmark results are reasons to test; only the Pari v2 corpus can decide the local default.

Facts below are traced to first-party model cards or peer-reviewed/ACL papers where possible.

## Primary contenders

### CoEdIT-large

- Official checkpoint: https://huggingface.co/grammarly/coedit-large
- Paper: https://aclanthology.org/2023.findings-emnlp.350/
- Architecture/base: FLAN-T5-large text-to-text editor.
- Parameters: **770M** (official model card).
- Purpose: instruction-driven text revision/writing assistance; the paper covers editing tasks including grammar, simplification, paraphrasing and style changes.
- Training scale: paper reports **82K task-specific text-editing instructions**.
- License: **CC-BY-NC-4.0** on the official checkpoint.
- Benchmark role: compact editing specialist; research/personal evaluation only unless shipping-license questions are separately resolved.
- Important limitation: T5 config advertises `n_positions: 512`, so long paragraph behavior must be tested explicitly rather than assumed.

### CoEdIT-XL

- Official checkpoint: https://huggingface.co/grammarly/coedit-xl
- Paper: https://aclanthology.org/2023.findings-emnlp.350/
- Base: FLAN-T5-XL.
- Parameters: **3B** (official model card).
- License: **CC-BY-NC-4.0**.
- Benchmark role: likely quality/RAM sweet-spot editing specialist on a 16-GB Mac if a suitable local runtime/quantization is stable.
- Same licensing and context-length cautions as CoEdIT-large.

### DIPPER (Discourse Paraphraser) XXL

- Checkpoint/model card: https://huggingface.co/fahmid/dipper-paraphraser-xxl
- Original project/paper is linked from the model card.
- Architecture: T5-XXL fine-tune.
- Parameters: **11B**.
- License: **Apache-2.0** on the cited checkpoint.
- Purpose: explicitly trained for **paragraph-length / discourse-level paraphrasing**, not only isolated sentence paraphrase.
- Controls: documented inference controls for **lexical diversity** and **content/order diversity**.
- Training data: model card states DIPPER uses **PAR3**, paragraph-aligned alternative English translations, as paragraph-level paraphrases.
- Benchmark role: most task-specific paragraph paraphraser in the set; must justify its much larger RAM/runtime cost.
- Important limitation: original implementation assumes CUDA/T5 tooling; Apple-Silicon quantized runtime must be validated rather than presumed.

### MiniCPM5-2B

- Official checkpoint: https://huggingface.co/openbmb/MiniCPM5-2B
- Official Apple-Silicon checkpoint: https://huggingface.co/openbmb/MiniCPM5-2B-MLX
- Parameters: **2,516,756,480** total (official model card).
- Architecture: standard LlamaForCausalLM, dense.
- Context: **131,072** tokens advertised.
- License: **Apache-2.0**.
- Deployment: OpenBMB explicitly provides an **MLX / 4-bit Apple Silicon** release and documents MLX among supported backends.
- Benchmark role: modern compact general-model challenger with excellent deployment fit; not paraphrase-specific.

### Qwen3.5-4B

- Official checkpoint: https://huggingface.co/Qwen/Qwen3.5-4B
- License: **Apache-2.0**.
- Benchmark role: current general-model control in Pari's shootout; do not treat its existing old-suite score as a human paraphrase-quality score.
- Important protocol rule: use text-only rewrite prompting and record any thinking/reasoning configuration; visual capability is irrelevant to this benchmark.

### Ling-3.0-tiny

- Official checkpoint: https://huggingface.co/inclusionAI/Ling-3.0-tiny
- Architecture: sparse hybrid MoE.
- Parameters: **7.9B total / 1.3B activated per token** (official model card).
- License: **MIT**.
- Local deployment receipt: model card says the model was validated on Apple Silicon; it reports about **86–90 tok/s on an M4 Pro MacBook in FP8 at 8K context**, with approximately **8.34 GiB peak memory** in that setup.
- Thinking: configurable via `enable_thinking`.
- Benchmark role: modern sparse general-model challenger; measure quality against its larger total-memory footprint and runtime complexity.

## Secondary/diagnostic contender

### ADAL / RADAR paraphraser-large

- Checkpoint: https://huggingface.co/Shushant/adal-paraphraser-large
- Architecture: T5-large.
- Parameters: **0.3B** (model card).
- File size shown by repository: roughly **710 MB** FP32 checkpoint.
- License: **Apache-2.0**.
- Training purpose: adversarial paraphrasing in the RADAR detector framework, specifically to generate paraphrases that evade the companion detector.
- Benchmark role: tiny paraphrase-specific diagnostic baseline, **not** a presumed quality winner. Its training objective is not the same as Pari's meaning-preserving writing-assistance objective.

## Required comparison set

Run at minimum:

1. CoEdIT-large 770M;
2. CoEdIT-XL 3B;
3. DIPPER 11B;
4. MiniCPM5-2B;
5. Qwen3.5-4B;
6. Ling-3.0-tiny;
7. current shipped Qwen3-4B incumbent;
8. original text / deterministic fallback as safety references.

ADAL is optional but useful for the low-RAM end of the Pareto curve.

## Do not mix model selection with shipping eligibility

A non-commercial model can still be benchmarked as a research reference. If CoEdIT wins, that does **not** authorize shipping its official checkpoint. Record two independent decisions:

- **quality winner**;
- **shippable winner under acceptable license/runtime constraints**.

## Required receipts in every result run

Each output bundle must record:

- exact model repository and revision/commit;
- quantized conversion repository + revision if not using official weights;
- license stated by both base and conversion;
- runtime and version;
- quantization format/bit width;
- prompt/template and generation settings;
- hardware/macOS version;
- model bytes on disk;
- peak memory;
- latency/throughput;
- raw outputs for every corpus case.

## 2026-09-08 execution receipts

All completed v2 runs used the validated 72-case corpus and the product
instruction in `corpus.json`. Raw JSONL and score bundles are retained under
`results/`; production-finalized scores are separate from raw generator
scores.

| Candidate | Runtime receipt | v2 result | Decision state |
| --- | --- | --- | --- |
| Qwen3-4B incumbent | MLX 4-bit; 2.153 GB on disk; 2.258 GiB peak Metal; 1.450 s median case | 65/72 raw; 65/72 Pari-finalized | Keep incumbent; no promotion |
| Qwen3-4B best-of-four | MLX 4-bit; four temperatures; automatic selector | 69/72 raw research selection; 60/72 production-safe selection | Research evidence only |
| Qwen3.5-4B control | MLX 4-bit; 3.061 GB on disk; 2.520 GiB peak Metal; 1.685 s median case | 64/72 raw; 65/72 Pari-finalized | Not promoted |
| MiniCPM5-2B | MLX 4-bit; 1.426 GB on disk; 1.536 GiB peak Metal; 0.868 s median case | 21/72 raw; 24/72 Pari-finalized | Rejected for promotion |
| CoEdIT-large | Transformers 5.14.1 / PyTorch 2.12.1 / MPS; 3.135 GB on disk; 2.303 GiB MPS; 2.051 s median case | 51/72 raw and Pari-finalized; 14 hard-safety failures | Research-only negative result; CC-BY-NC-4.0 |
| CoEdIT-XL | Transformers 5.14.1 / PyTorch 2.12.1 / MPS; one 11.4 GB safetensor | 55/72 raw rows written; full run not scored | **User-stopped** after MPS smoke and partial run; CC-BY-NC-4.0 |

### Required candidates not completed

- **ADAL / RADAR paraphraser-large** — the pinned 709.6 MB download was
  inspected; the safetensor contains NaN values in encoder/decoder tensors, so
  the checkpoint is invalid for generation and was not scored.
- **DIPPER XXL** — the unauthenticated pinned Hub snapshot exposed only the
  handler/README and no model weights, so no local run was possible.
- **Ling-3.0-tiny** — the pinned Apple conversion requires `rapid-mlx`, which
  is not installed; the available upstream `mlx-lm` path does not support its
  `bailing_hybrid` architecture. It was not silently substituted with a
  different runtime.

The CoEdIT-XL partial JSONL is intentionally retained for recoverable resume,
but it is not a quality score and must not be used in the promotion report.
