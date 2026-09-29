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

console.log(JSON.stringify({ accepted: accepted.size, rejected: rejected.length, status: "pass" }));
