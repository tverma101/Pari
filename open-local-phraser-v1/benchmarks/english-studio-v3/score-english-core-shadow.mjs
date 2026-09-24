#!/usr/bin/env node

// DEPRECATED COMPATIBILITY ENTRY POINT.
//
// This file previously implemented an older shadow-scoring protocol that:
// - expected a different JSONL result format;
// - did not reconstruct the canonical deterministic option permutation; and
// - accepted one free-form score_0_100 for generative cases without the current
//   metric directionality/provenance contract.
//
// Keeping that scorer active would allow two incompatible definitions of an
// "English Core" score. It is intentionally disabled. Use score-english-core.mjs.

console.error([
  "score-english-core-shadow.mjs is retired and intentionally does not score results.",
  "Use the canonical command:",
  "  node score-english-core.mjs <result.json>",
  "The canonical scorer enforces option-order reconstruction, complete-dimension scoring,",
  "the versioned generative metric-direction contract, and structured metric provenance."
].join("\n"));
process.exit(2);
