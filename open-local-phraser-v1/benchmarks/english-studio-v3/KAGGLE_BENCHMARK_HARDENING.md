# Kaggle benchmark hardening — mandatory qualification before LLM scoring

This document is a **blocking execution contract** for GitHub Issue #25 and PR #26.

The Pari English Core / Word Studio benchmark must distinguish three very different questions:

1. **Can this exact model + artifact + runtime actually run on Kaggle 2×T4?**
2. **Can it follow the benchmark response protocol reliably?**
3. **How strong is its English / Word Studio behavior when it does run and answer?**

Never collapse those into one score. A CUDA/runtime incompatibility is not bad English. A recoverable formatting error is not the same as choosing the wrong answer. A model that only works after changing quantization/runtime is a different evaluated configuration.

---

## 1. Real Kaggle T4 execution is mandatory

Promotion-quality runtime evidence must come from an actual private Kaggle job exposing **2× NVIDIA T4, 16 GB each**.

Local CUDA, Colab, A10/A100/L4, Apple Silicon, CPU, or model-card throughput may be useful development evidence but cannot substitute for the Kaggle T4 qualification run.

Every candidate result must record:

- Kaggle kernel/run identity;
- exact benchmark Git commit;
- exact model repository + immutable revision;
- exact runtime and version/build commit;
- exact quantization/dtype;
- GPU names, count, memory, compute capability, driver and CUDA versions;
- `CUDA_VISIBLE_DEVICES`;
- TP size and device placement/offload evidence;
- cold-load result and time;
- peak VRAM if available;
- full command/config used;
- whether ordinary decode, MTP/speculative decode, TP2, or two independent GPU replicas were used.

A result without real T4 evidence is `environment_unqualified` and cannot enter the quality comparison.

---

## 2. Qualification ladder

Every exact candidate configuration must pass the following ladder **in order**.

### Q0 — environment preflight

Require and record:

- exactly two visible NVIDIA T4 devices for the canonical Kaggle run;
- CUDA available;
- compute capability 7.5;
- expected per-GPU memory;
- runtime imports/version checks;
- model/tokenizer revision resolvable;
- required native libraries and shared objects resolvable;
- no accidental CPU-only fallback.

Failure here is infrastructure/runtime evidence only. Do not score English.

### Q1 — load and placement smoke

Load the exact artifact with the exact intended runtime configuration.

Require evidence that:

- model load completes;
- expected CUDA device(s) are used;
- GPU offload/device placement matches the declared configuration;
- no silent CPU fallback occurred;
- tokenizer and chat template initialize;
- one trivial generation completes;
- runtime remains alive after the generation.

Record the failure class if it does not pass.

### Q2 — protocol smoke

Before the 1,943-case screen, run a small fixed smoke set covering **protocol behavior**, not benchmark quality:

- forced-choice answer requesting one letter;
- answer with punctuation tolerance;
- short natural-language generation;
- Word Studio list generation;
- Unicode punctuation/input;
- longer context;
- protected names/numbers/date text;
- repeated request after warmup.

The smoke must verify that the harness can observe and classify the output. It must not be used to tune prompts to a specific model after seeing benchmark results.

### Q3 — bounded benchmark smoke

Run a deterministic fixed prefix/stratified subset from the frozen benchmark (for example 16–32 cases), checkpoint it, validate IDs/hashes/output count, and run the scorer/parser diagnostics.

Do not start the full screen until this succeeds.

### Q4 — complete fixed screen

Only a Q0–Q3-qualified configuration may run and be reported in the 1,943-case common comparison.

### Q5 — Word Studio and runtime qualification

Finalists must then run the product suite and interactive latency tests on the same Kaggle hardware family.

---

## 3. Required failure taxonomy

Do not leave a failed candidate as merely `error` or `invalid`.

At minimum classify failures into the following machine-readable categories where applicable:

### Environment/runtime

- `environment_unqualified`
- `dependency_install_failure`
- `runtime_import_failure`
- `unsupported_architecture`
- `unsupported_compute_capability`
- `unsupported_quantization`
- `tokenizer_load_failure`
- `chat_template_failure`
- `model_download_failure`
- `artifact_hash_mismatch`
- `model_load_failure`
- `cuda_oom_load`
- `cuda_oom_generate`
- `gpu_offload_unverified`
- `silent_cpu_fallback_detected`
- `tensor_parallel_failure`
- `mtp_unsupported`
- `mtp_runtime_failure`
- `native_library_or_abi_failure`
- `generation_timeout`
- `runtime_crash`
- `kaggle_session_or_control_plane_failure`

### Response/protocol

- `ok`
- `empty_output`
- `whitespace_only`
- `malformed_choice`
- `ambiguous_multiple_choices`
- `reasoning_only_no_answer`
- `reasoning_leak_with_answer`
- `refusal_or_nonanswer`
- `max_tokens_truncation`
- `wrong_number_of_outputs`
- `duplicate_response`
- `invalid_unicode_or_decode_error`
- `word_studio_unparseable_list`
- `word_studio_too_few_candidates`
- `word_studio_excessive_duplicates`

Preserve the raw output bytes/text needed to audit the classification.

---

## 4. Strict protocol score and recoverable semantic score must be separate

Forced-choice models sometimes output:

- `A`
- `A.`
- `A. same`
- `Answer: A`
- `The answer is A because ...`

The benchmark asks for a letter-only answer, so **format compliance remains a real metric**. But formatting mistakes must not be silently converted into linguistic ignorance.

For every forced-choice lane report both:

1. **strict protocol compliance / strict accuracy** — only the frozen strict contract;
2. **recoverable semantic parse accuracy** — only a predeclared conservative anchored parser that extracts an explicit selected option without inferring from free prose.

Rules:

- never scan arbitrary prose for an answer letter;
- never use the gold answer to decide how to parse;
- never change parser behavior after inspecting which model benefits;
- parser versions/hashes are part of result provenance;
- report strict-vs-recoverable disagreement counts;
- malformed/ambiguous outputs remain visible even when a semantic choice can be recovered.

The Bonsai parser replay already demonstrated why this distinction matters. Preserve the frozen strict score and label a replay as parser/format coverage, never as improved generation.

---

## 5. Model-family response edge cases

The harness must test and safely handle common model behaviors:

- `<think>...</think>` followed by an answer;
- unclosed thinking blocks;
- Markdown/code fences;
- leading/trailing labels;
- repeated answer lines;
- `A or B` / `A/B` ambiguity;
- answer then self-correction;
- answer embedded in an explanation;
- model echoes the prompt/options;
- empty completion with non-empty reasoning channel;
- EOS before answer;
- max-token cutoff;
- refusal/safety boilerplate;
- tool-call-like or JSON-shaped output;
- invalid UTF-8/decoding anomalies from native runtimes;
- runtime returning outputs out of order;
- fewer/more outputs than requests.

Any parser normalization used for official scoring must be deterministic, versioned, tested with positive **and adversarial negative** fixtures, and applied identically to every model.

---

## 6. Word Studio output parser must be first-class

A Word Studio candidate is not valid merely because it emitted fluent text.

For a request for 10 alternatives, capture and report:

- raw completion;
- parsed candidate list;
- parser status;
- requested count;
- parsed count;
- unique normalized count;
- exact-duplicate count;
- near-duplicate rate;
- empty candidates;
- candidates that reproduce the source unchanged;
- candidate length distribution;
- whether protected content was corrupted;
- whether output accidentally contains commentary instead of alternatives.

The parser should support a **predeclared** set of harmless wrappers (numbered list, bullets, newline list, valid JSON array if requested by the frozen prompt) while rejecting ambiguous prose dumps.

Do not silently ask the model again because the first answer was ugly. Retry behavior is controlled below.

---

## 7. Retry policy: transient runtime recovery, never result cherry-picking

Predeclare retries.

Allowed automatic retry examples:

- transient model-server connection reset;
- temporary CUDA allocation failure after cleanup where the same config is retried once;
- Kaggle filesystem/network interruption during public artifact fetch;
- server startup race.

Do **not** automatically retry merely because:

- the answer is wrong;
- the answer is malformed;
- the model refuses;
- Word Studio alternatives are poor;
- the model returns too few useful candidates.

Every attempt is retained. A retry uses the same frozen task, seed, prompt, decoding configuration, artifact and runtime. Never keep only the better attempt.

---

## 8. Predeclared OOM / compatibility fallback matrix

The harness may reduce **batch size** to make the same model configuration executable, because batch size is a serving parameter rather than a different language model.

Recommended deterministic sequence:

`64 -> 32 -> 16 -> 8 -> 4 -> 1`

Record every failed step and the first stable step.

Do not silently change any of the following to make a model fit:

- checkpoint;
- quantization;
- dtype semantics;
- model architecture;
- tokenizer;
- chat template;
- context policy beyond a predeclared benchmark-safe bound;
- runtime implementation.

Those changes create a **new candidate configuration** and require a separate result identity.

If TP1 fails but TP2 is an intended configuration, report TP1 failure and TP2 separately. Do not overwrite the TP1 evidence.

---

## 9. T4 speed testing must match the product

For every finalist that fits on one T4, measure at least:

- ordinary decode on one T4;
- warm repeated requests;
- candidate generation on GPU0 while GPU1 is independently available;
- two independent model replicas if the artifact fits and this is operationally practical;
- TP2 only if required or if measured to improve end-to-end latency;
- MTP/speculative variants only when genuinely supported.

Report:

- cold load;
- TTFT p50/p95;
- complete-output latency p50/p95;
- time to first parsed Word Studio candidate;
- time to first 3 parsed candidates;
- time to 10 parsed candidates;
- prefill tok/s;
- decode tok/s;
- successful request throughput;
- peak VRAM/headroom;
- speculative acceptance metrics when exposed;
- failure/retry rate.

Do not mix cold and warm samples into one latency number.

---

## 10. Determinism and stability checks

A candidate that passes once but is operationally unstable is not ready for Pari.

For finalists:

- rerun a fixed subset after warmup;
- verify task/output ordering and IDs;
- compare deterministic outputs where temperature is zero;
- record unexpected nondeterminism rather than hiding it;
- run enough repeated requests to expose delayed OOM/memory leaks/server degradation;
- verify checkpoint/resume after an intentional interruption;
- ensure a resumed run cannot duplicate or silently skip task IDs.

---

## 11. Scoring rules for failures

### Never do this

`model failed to load on T4 -> English score = 0`

### Instead

Report the candidate as:

`runtime_status = unqualified` with a structured failure reason.

Similarly:

- a recoverable formatting miss is reported in protocol-compliance metrics and separately in semantic accuracy;
- an ambiguous response is invalid, not guessed;
- a truncated response is a generation/protocol failure, not automatically a linguistic error;
- a wrong but well-formed choice is a real task error;
- a Word Studio list with only three candidates is a product-output-depth failure even if those three are good.

Only comparable, qualified runs enter head-to-head English Core statistics.

---

## 12. Required candidate matrix

Issue #25 is not complete until every serious roster candidate has one explicit status row:

| candidate | exact config | Kaggle T4 qualification | full screen | Word Studio | MTP/spec | disposition |
| --- | --- | --- | --- | --- | --- | --- |
| candidate | pinned model/runtime/quant | passed / structured failure | complete / n/a | complete / n/a | measured / unsupported / n/a | finalist / eliminated / runtime-unqualified |

No blank cells and no implied success.

---

## 13. Blocking acceptance criteria

Before model selection:

- [ ] every serious candidate was attempted on real Kaggle T4×2;
- [ ] every attempt has structured runtime evidence or a structured failure artifact;
- [ ] no runtime failure was converted to an English-quality zero;
- [ ] strict and recoverable forced-choice parsing are both reported;
- [ ] parser adversarial fixtures pass;
- [ ] Word Studio has a deterministic candidate-list parser and output-depth metrics;
- [ ] empty/refusal/truncated/ambiguous/reasoning-leak cases are counted explicitly;
- [ ] batch-size/OOM fallback is predeclared and auditable;
- [ ] retries are retained and cannot cherry-pick better content;
- [ ] finalists have warm latency distributions on Kaggle, not one-off stopwatch numbers;
- [ ] MTP/speculative comparisons use the same frozen prompts/configuration apart from the decoding method;
- [ ] the final comparison includes runtime-unqualified candidates as such rather than deleting them from history;
- [ ] only qualified and comparable runs enter paired linguistic statistics.

This hardening work is part of the benchmark. It is not optional cleanup after model selection.
