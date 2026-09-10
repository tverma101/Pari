#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { meaningContractIssuesForBenchmark } from "../benchmarks/paraphrase-v2/meaning-contract-bridge.mjs";

const ROOT_DIR = path.resolve(new URL("..", import.meta.url).pathname);

function ids(original, candidate) {
  return new Set(meaningContractIssuesForBenchmark(original, candidate).map((issue) => issue.id));
}

assert.deepEqual(
  meaningContractIssuesForBenchmark(
    "The update will probably work.",
    "The update will likely work.",
  ),
  [],
  "benchmark bridge disagreed with production certainty equivalence",
);
assert(
  ids("The update will probably work.", "The update will definitely work.").has("certainty-drift"),
  "benchmark bridge missed certainty strengthening",
);
assert(
  ids("At least 10 records remain.", "At most 10 records remain.").has("quantity-drift"),
  "benchmark bridge missed numeric bound reversal",
);
assert(
  ids("The office stays open until Friday.", "The office stays open before Friday.").has("discourse-relation-drift"),
  "benchmark bridge missed temporal boundary drift",
);
assert.deepEqual(
  meaningContractIssuesForBenchmark(
    "Certain users reported delays.",
    "Some users reported delays.",
  ),
  [],
  "benchmark bridge misclassified subset 'certain'",
);

const scoreSource = fs.readFileSync(
  path.join(ROOT_DIR, "benchmarks/paraphrase-v2/score.mjs"),
  "utf8",
);
assert.match(
  scoreSource,
  /meaningContractIssuesForBenchmark\(item\.input, output\)/,
  "v2 score path does not invoke the production meaning contract bridge",
);
assert.match(
  scoreSource,
  /passed:\s*scored\.passed\s*&&\s*meaningContractSafe/,
  "v2 pass gate does not include meaningContractSafe",
);
assert.match(
  scoreSource,
  /meaningSafe:\s*scored\.meaningSafe\s*&&\s*meaningContractSafe/,
  "v2 meaning-safe gate does not include meaningContractSafe",
);
assert.match(
  scoreSource,
  /"meaningContractSafe"/,
  "v2 failedChecks does not expose meaning-contract failures",
);

console.log("qa:benchmark:meaning-contract passed");
