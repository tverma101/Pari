#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { meaningContractIssuesForBenchmark } from "../benchmarks/paraphrase-v2/meaning-contract-bridge.mjs";
import { protectedContentValidationForBenchmark } from "../benchmarks/paraphrase-v2/protected-content-bridge.mjs";

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
  ids("The interface barely changed.", "The interface slightly changed.").has("degree-drift"),
  "benchmark bridge missed degree/extent strengthening",
);
assert(
  ids("I sometimes review the draft.", "I always review the draft.").has("frequency-drift"),
  "benchmark bridge missed frequency strengthening",
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

assert.equal(
  protectedContentValidationForBenchmark(
    "Read the documentation before editing.",
    "Read https://example.org before editing.",
  ).safe,
  false,
  "benchmark protected-content bridge accepted an invented URL",
);
assert.equal(
  protectedContentValidationForBenchmark(
    "Read https://example.org before editing.",
    "Before editing, read https://example.org.",
  ).safe,
  true,
  "benchmark protected-content bridge rejected an unchanged moved URL",
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
  /protectedContentValidationForBenchmark\(item\.input, output\)/,
  "v2 score path does not invoke the production protected-content bridge",
);
assert.match(
  scoreSource,
  /productionMeaningSafe\s*=\s*meaningContractSafe\s*&&\s*protectedContentSafe/,
  "v2 score path does not combine both production semantic gates",
);
assert.match(
  scoreSource,
  /passed:\s*scored\.passed\s*&&\s*productionMeaningSafe/,
  "v2 pass gate does not include production semantic safety",
);
assert.match(
  scoreSource,
  /meaningSafe:\s*scored\.meaningSafe\s*&&\s*productionMeaningSafe/,
  "v2 meaning-safe gate does not include production semantic safety",
);
assert.match(
  scoreSource,
  /"meaningContractSafe"/,
  "v2 failedChecks does not expose meaning-contract failures",
);
assert.match(
  scoreSource,
  /"protectedContentSafe"/,
  "v2 failedChecks does not expose protected-content failures",
);

console.log("qa:benchmark:meaning-contract passed");
