#!/usr/bin/env node
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import ts from "typescript";

const ROOT_DIR = path.resolve(new URL("..", import.meta.url).pathname);
const nodeRequire = createRequire(import.meta.url);
const moduleCache = new Map();

function resolveFile(basePath) {
  for (const candidate of [basePath, `${basePath}.ts`, `${basePath}.tsx`, `${basePath}.js`, `${basePath}.json`]) {
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  throw new Error(`Cannot resolve ${basePath}`);
}

function loadTsModule(filePath) {
  const absolutePath = resolveFile(filePath);
  if (moduleCache.has(absolutePath)) return moduleCache.get(absolutePath).exports;
  if (absolutePath.endsWith(".json")) {
    const module = { exports: JSON.parse(fs.readFileSync(absolutePath, "utf8")) };
    moduleCache.set(absolutePath, module);
    return module.exports;
  }

  const source = fs.readFileSync(absolutePath, "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      esModuleInterop: true,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: absolutePath,
  }).outputText;
  const module = { exports: {} };
  moduleCache.set(absolutePath, module);
  const localRequire = (specifier) => {
    if (specifier.startsWith("@/")) return loadTsModule(path.join(ROOT_DIR, "src", specifier.slice(2)));
    if (specifier.startsWith(".")) return loadTsModule(path.resolve(path.dirname(absolutePath), specifier));
    return nodeRequire(specifier);
  };
  const wrapper = `(function(exports, require, module, __filename, __dirname) {\n${output}\n})`;
  const compiled = vm.runInThisContext(wrapper, { filename: absolutePath });
  compiled(module.exports, localRequire, module, absolutePath, path.dirname(absolutePath));
  return module.exports;
}

const { createRuleNliJudge } = loadTsModule(path.join(ROOT_DIR, "src/lib/scoring/nliJudge.ts"));
const { meaningContractIssues } = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/meaningContract.ts"));
const { repairSentenceFlow } = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/sentenceFlow.ts"));
const { extractProtectedSpans, validateProtectedContent } = loadTsModule(path.join(ROOT_DIR, "src/lib/safety/protectedContent.ts"));
const judge = createRuleNliJudge();

async function expectContradiction(premise, hypothesis, label) {
  const result = await judge.judge(premise, hypothesis);
  assert.equal(result.label, "contradict", `${label}: expected contradiction, got ${JSON.stringify(result)}`);
}

async function expectAllowed(premise, hypothesis, label) {
  const result = await judge.judge(premise, hypothesis);
  assert.notEqual(result.label, "contradict", `${label}: false contradiction ${JSON.stringify(result)}`);
}

function meaningIds(original, candidate) {
  return new Set(meaningContractIssues(original, candidate).map((issue) => issue.id));
}

function expectNoRelationDrift(original, candidate, label) {
  assert(
    !meaningIds(original, candidate).has("discourse-relation-drift"),
    `${label}: equivalent relation was rejected`,
  );
}

function expectRelationDrift(original, candidate, label) {
  assert(
    meaningIds(original, candidate).has("discourse-relation-drift"),
    `${label}: relation drift was accepted`,
  );
}

function expectProtectedSafe(original, candidate, label) {
  const result = validateProtectedContent(original, candidate, extractProtectedSpans(original));
  assert.equal(result.safe, true, `${label}: false protected-content rejection ${JSON.stringify(result)}`);
}

function expectProtectedUnsafe(original, candidate, label) {
  const result = validateProtectedContent(original, candidate, extractProtectedSpans(original));
  assert.equal(result.safe, false, `${label}: protected-content drift was accepted`);
}

await expectContradiction(
  "The nurse helped the patient.",
  "The patient helped the nurse.",
  "simple active role swap",
);
await expectContradiction(
  "The curator mailed the rare manuscript to the archive.",
  "The archive mailed the rare manuscript to the curator.",
  "agent/recipient role swap with unchanged direct object",
);
await expectAllowed(
  "The editor reviewed the draft.",
  "The draft was reviewed by the editor.",
  "active/passive equivalence",
);
await expectAllowed(
  "After lunch, the editor reviewed the draft.",
  "The editor reviewed the draft after lunch.",
  "safe adjunct movement",
);
await expectAllowed(
  "The editor couldn't approve the draft.",
  "The editor could not approve the draft.",
  "straight-apostrophe contraction expansion",
);
await expectAllowed(
  "The editor couldn’t approve the draft.",
  "The editor could not approve the draft.",
  "curly-apostrophe contraction expansion",
);
await expectContradiction(
  "The editor can approve the draft.",
  "The editor can't approve the draft.",
  "positive-to-negative modal contraction",
);
await expectContradiction(
  "The editor can approve the draft.",
  "The editor can’t approve the draft.",
  "positive-to-negative curly modal contraction",
);
await expectContradiction(
  "The report contains 12 examples.",
  "The report contains 13 examples.",
  "invented numeric detail",
);

const unlessEquivalent = meaningIds(
  "Unless it rains, we can leave.",
  "If it does not rain, we can leave.",
);
assert(!unlessEquivalent.has("negation-drift"), "unless↔if-not equivalence falsely changed negation");
assert(!unlessEquivalent.has("discourse-relation-drift"), "unless↔if-not equivalence falsely changed condition relation");

const unlessDropped = meaningIds(
  "Unless it rains, we can leave.",
  "If it rains, we can leave.",
);
assert(unlessDropped.has("negation-drift"), "unless→if lost implicit negative force without a veto");

const nestedUnlessEquivalent = meaningIds(
  "Unless the editor approves the draft, we cannot ship it.",
  "If the editor does not approve the draft, we cannot ship it.",
);
assert(!nestedUnlessEquivalent.has("negation-drift"), "unless↔if-not failed with an additional unchanged negation");
assert(!nestedUnlessEquivalent.has("discourse-relation-drift"), "unless↔if-not failed relation normalization with another negation");

const doubleNegativeUnless = meaningIds(
  "Unless the editor does not approve the draft, we can ship it.",
  "If the editor approves the draft, we can ship it.",
);
assert(doubleNegativeUnless.has("negation-drift"), "unless-not collapsed two negative forces into a positive condition");

expectNoRelationDrift(
  "The flight was delayed because of fog.",
  "The flight was delayed due to fog.",
  "because-of↔due-to cause equivalence",
);
expectNoRelationDrift(
  "The team shipped despite the delay.",
  "Although there was a delay, the team shipped.",
  "despite↔although contrast equivalence",
);
expectNoRelationDrift(
  "The first version is shorter, whereas the second is clearer.",
  "The first version is shorter, but the second is clearer.",
  "whereas↔but contrast equivalence",
);
expectNoRelationDrift(
  "The service stays open until Friday.",
  "The service stays open till Friday.",
  "until↔till time-boundary equivalence",
);
expectRelationDrift(
  "The flight was delayed because of fog.",
  "The flight was delayed after fog.",
  "cause changed to chronology",
);
expectRelationDrift(
  "The service stays open until Friday.",
  "The service stays open before Friday.",
  "until changed to before",
);
expectRelationDrift(
  "Call me as soon as the result arrives.",
  "Call me once the result arrives.",
  "immediate time relation weakened to once",
);
expectRelationDrift(
  "The team shipped despite the delay.",
  "The team shipped after the delay.",
  "contrast changed to chronology",
);

assert.equal(
  repairSentenceFlow(
    "I focus better when the room is quiet.",
    "I focus better, and the room is quiet.",
  ),
  "I focus better when the room is quiet.",
  "dropped embedded time relation produced a coordinator fragment",
);
assert.equal(
  repairSentenceFlow(
    "The team revised the plan because the deadline changed.",
    "The team revised the plan, and the deadline changed.",
  ),
  "The team revised the plan because the deadline changed.",
  "dropped embedded causal relation produced a coordinator fragment",
);
assert.equal(
  repairSentenceFlow(
    "The draft was ready, although the review was late.",
    "The draft was ready, and the review was late.",
  ),
  "The draft was ready, although the review was late.",
  "source comma before embedded relation was not preserved",
);
assert(
  !repairSentenceFlow(
    "I focus better when the room is quiet.",
    "I focus better, and the room is quiet.",
  ).includes("especially"),
  "relation repair invented emphasis",
);

expectProtectedSafe(
  "We can't ship today.",
  "We cannot ship today.",
  "can't→cannot semantic anchor equivalence",
);
expectProtectedSafe(
  "We could not ship tomorrow.",
  "We couldn't ship tomorrow.",
  "could-not→couldn't semantic anchor equivalence",
);
expectProtectedSafe(
  "They aren’t ready.",
  "They are not ready.",
  "curly negative contraction expansion",
);
const negativeModalSpans = extractProtectedSpans("We can't ship.");
assert(
  !negativeModalSpans.some((span) => span.kind === "modality" && span.text.toLowerCase() === "can"),
  "negative contraction retained a redundant nested modal anchor",
);
expectProtectedUnsafe(
  "The dose is 50 mg.",
  "The dose is 50 g.",
  "measurement unit mutation",
);
expectProtectedUnsafe(
  "Meet at 6pm PST.",
  "Meet at 6pm EST.",
  "timezone mutation",
);
expectProtectedUnsafe(
  "The review is on 10 September 2026.",
  "The review is on 10 October 2026.",
  "day-month date mutation",
);
expectProtectedUnsafe(
  "The draft is ready.",
  "The draft is ready Monday.",
  "invented weekday",
);
expectProtectedUnsafe(
  "The report has 12 examples.",
  "The report has 12 examples and 13 notes.",
  "invented additional number",
);
const technicalSpans = extractProtectedSpans("GPT-6 can rewrite the draft.");
assert(
  technicalSpans.some((span) => span.kind === "name" && span.text === "GPT-6"),
  "technical model name at sentence start was not protected",
);

console.log("qa:rule:nli passed");
