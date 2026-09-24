#!/usr/bin/env node

import assert from "node:assert/strict";
import { parseChoiceLetter } from "./english-core-choice-parser.mjs";

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
]);

const rejected = [
  "",
  "A because it sounds better",
  "The answer is A because...",
  "A or B",
  "Probably A",
  "I choose A",
  "ANSWERA",
  "Option A or B",
  "A, B",
];

for (const [text, expected] of accepted) {
  assert.equal(parseChoiceLetter(text), expected, `expected ${JSON.stringify(text)} -> ${expected}`);
}
for (const text of rejected) {
  assert.equal(parseChoiceLetter(text), null, `expected ${JSON.stringify(text)} to be rejected`);
}

console.log(JSON.stringify({ accepted: accepted.size, rejected: rejected.length, status: "pass" }));
