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

console.log("qa:rule:nli passed");
