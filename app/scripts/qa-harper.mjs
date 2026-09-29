import assert from "node:assert/strict";
import { LocalLinter } from "harper.js";
import { binaryInlined } from "harper.js/binaryInlined";

const linter = new LocalLinter({ binary: binaryInlined });
await linter.setup();

async function lint(text) {
  const lints = await linter.lint(text, {
    language: "plaintext",
    dedup: true,
    isolateEnglish: true,
  });

  return lints.map((lint) => {
    const span = lint.span();
    try {
      return {
        kind: lint.lint_kind_pretty() || lint.lint_kind(),
        problem: lint.get_problem_text(),
        start: span.start,
        end: span.end,
        message: lint.message(),
      };
    } finally {
      span.free();
      lint.free();
    }
  });
}

const malformed = "They is ready to revise the draft. An useful tool help writers.";
const malformedLints = await lint(malformed);
assert.ok(malformedLints.length >= 2, `expected agreement and article lints, got ${malformedLints.length}`);
assert.ok(malformedLints.some((entry) => entry.problem === "is" && entry.start === 5), "agreement range was not reported");
assert.ok(malformedLints.some((entry) => entry.problem === "An"), "article lint was not reported");
assert.ok(malformedLints.every((entry) => entry.end > entry.start), "every lint should have a usable range");

const clean = "They are ready to revise the draft. A useful tool helps writers.";
const cleanLints = await lint(clean);
assert.equal(cleanLints.length, 0, `clean sentence produced ${cleanLints.length} unexpected lint(s)`);

console.log(`[qa:grammar:harper] malformed=${malformedLints.length} clean=${cleanLints.length} PASS`);
