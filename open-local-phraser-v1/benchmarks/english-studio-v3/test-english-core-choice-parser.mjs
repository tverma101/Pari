#!/usr/bin/env node

import assert from "node:assert/strict";
import {
  allowedChoicesFromTask,
  normalizeAllowedChoices,
  parseChoice,
  parseChoiceLetter,
} from "./english-core-choice-parser.mjs";

const accepted = new Map([
  ["A", "A"],
  ["A.", "A"],
  ["b)", "B"],
  ["Answer: C", "C"],
  ["Answer = D", "D"],
  ["Answer is E", "E"],
  ["The answer is F", "F"],
  ["The answer: G", "G"],
  ["Option H", "H"],
  ["  i  ", "I"],
  ["I choose J", "J"],
  ["I'd pick K.", "K"],
  ["I would select L", "L"],
  ["My choice is M", "M"],
  ["A. same", "A"],
  ["A. acceptable", "A"],
  ["B) This is the better-formed option.", "B"],
  ["C: Because it fits the context.", "C"],
  ["D) a short explanation\nwith detail", "D"],
  ["The answer is A because the verb agrees.", "A"],
  ["The answer is A because...", "A"],
  ["Answer: B — it preserves the meaning.", "B"],
  ["Option C: the second clause is grammatical.", "C"],
  ["I choose D because it directly answers the question.", "D"],
  ["My answer is E because it fits the context.", "E"],
  ["F is the correct answer.", "F"],
  ["G because it matches the example.", "G"],
  ["A because it sounds better", "A"],
]);

const rejected = [
  "",
  "A or B",
  "Probably A",
  "ANSWERA",
  "Option A or B",
  "A, B",
  "A. or B",
  "A. B. is also plausible",
  "A. and B both work",
  "A. B or C",
  "A. A or B",
  "I choose A or B",
  "The answer is A or B",
  "A is correct or B is correct",
];

for (const [text, expected] of accepted) {
  assert.equal(parseChoiceLetter(text), expected, `expected ${JSON.stringify(text)} -> ${expected}`);
}
for (const text of rejected) {
  assert.equal(parseChoiceLetter(text), null, `expected ${JSON.stringify(text)} to be rejected`);
}

// Task-aware allowed set (GitHub issue #44). The allowed set is frozen task
// metadata and never the gold answer.
const AB = ["A", "B"];
const ABCD = ["A", "B", "C", "D"];
const taskAware = [
  ["A", AB, "strict_allowed_choice", "A", null],
  ["D", ABCD, "strict_allowed_choice", "D", null],
  ["Answer: B", AB, "recoverable_allowed_choice", "B", null],
  ["Z", AB, "strict_invalid_option_label", null, "Z"],
  ["C", AB, "strict_invalid_option_label", null, "C"],
  ["E", ABCD, "strict_invalid_option_label", null, "E"],
  ["Answer: C because it fits", AB, "recoverable_invalid_option_label", null, "C"],
  ["b", AB, "strict_allowed_choice", "B", null],
  ["\uff21", AB, "no_anchored_answer", null, null], // full-width A
  ["\u212a", AB, "no_anchored_answer", null, null], // Kelvin sign
  ["\u0410", AB, "no_anchored_answer", null, null], // Cyrillic A
  ["", AB, "empty_output", null, null],
  ["   ", AB, "whitespace_only", null, null],
];

for (const [text, allowed, status, letter, invalid] of taskAware) {
  const got = parseChoice(text, allowed);
  assert.equal(got.status, status, `status ${JSON.stringify(text)} ${JSON.stringify(allowed)}`);
  assert.equal(got.letter, letter, `letter ${JSON.stringify(text)} ${JSON.stringify(allowed)}`);
  assert.equal(got.invalidOptionLabel, invalid, `invalid ${JSON.stringify(text)} ${JSON.stringify(allowed)}`);
  assert.equal(got.allowedSetFrozen, true);
  assert.equal(parseChoiceLetter(text, allowed), letter);
}

// Out-of-domain labels never become valid under either view.
for (const text of ["Z", "C", "Answer: C"]) {
  assert.equal(parseChoiceLetter(text, AB), null, text);
}

assert.deepEqual(allowedChoicesFromTask({ allowedChoices: ["B", "A"] }), ["A", "B"]);
assert.deepEqual(allowedChoicesFromTask({ allowed_choices: ["A", "B"] }), ["A", "B"]);
assert.equal(allowedChoicesFromTask({ id: "x" }), null);
assert.deepEqual(normalizeAllowedChoices("AB"), ["A", "B"]);
for (const bad of [[], ["AA"], [""], ["Ä"], { A: true }, ["a", "b"]]) {
  assert.throws(() => normalizeAllowedChoices(bad), `expected throw for ${JSON.stringify(bad)}`);
}

// Task files that predate the frozen set keep the historical permissive behavior.
const legacy = parseChoice("Z");
assert.equal(legacy.letter, "Z");
assert.equal(legacy.allowedSetFrozen, false);

console.log(
  JSON.stringify({ accepted: accepted.size, rejected: rejected.length, taskAware: taskAware.length, status: "pass" }),
);
