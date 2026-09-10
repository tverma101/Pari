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

const { meaningContractIssues } = loadTsModule(
  path.join(ROOT_DIR, "src/lib/generation/meaningContract.ts"),
);

function issues(original, candidate) {
  return meaningContractIssues(original, candidate);
}

function ids(original, candidate) {
  return new Set(issues(original, candidate).map((issue) => issue.id));
}

function expectContractSafe(original, candidate, label) {
  const found = issues(original, candidate);
  assert.deepEqual(found, [], `${label}: equivalent wording produced contract issues ${JSON.stringify(found)}`);
}

function expectNoQuantityDrift(original, candidate, label) {
  assert(
    !ids(original, candidate).has("quantity-drift"),
    `${label}: non-quantity prose created a quantity failure`,
  );
}

function expectQuantityDrift(original, candidate, label) {
  assert(
    ids(original, candidate).has("quantity-drift"),
    `${label}: quantity drift was accepted`,
  );
}

expectContractSafe(
  "At least 10 students attended.",
  "No less than 10 students attended.",
  "lower-inclusive synonyms",
);
expectContractSafe(
  "The room holds at most 30 people.",
  "The room holds up to 30 people.",
  "upper-inclusive synonyms",
);
expectContractSafe(
  "Approximately 200 records remain.",
  "Roughly 200 records remain.",
  "approximation synonyms",
);
expectContractSafe(
  "About 50% of the files changed.",
  "Around 50% of the files changed.",
  "about-around approximation synonyms",
);
expectContractSafe(
  "Exactly 12 examples are required.",
  "Precisely 12 examples are required.",
  "exactness synonyms",
);
expectContractSafe(
  "Nearly 100 users responded.",
  "Almost 100 users responded.",
  "near-below synonyms",
);
expectContractSafe(
  "A number of students asked questions.",
  "Several students asked questions.",
  "a-number-of several equivalence",
);

expectQuantityDrift(
  "At least 10 students attended.",
  "At most 10 students attended.",
  "minimum reversed to maximum",
);
expectQuantityDrift(
  "At least 10 students attended.",
  "More than 10 students attended.",
  "inclusive lower bound changed to exclusive",
);
expectQuantityDrift(
  "The room holds up to 30 people.",
  "The room holds fewer than 30 people.",
  "inclusive upper bound changed to exclusive",
);
expectQuantityDrift(
  "Exactly 12 examples are required.",
  "About 12 examples are required.",
  "exact quantity weakened to approximate",
);
expectQuantityDrift(
  "Approximately 200 records remain.",
  "Exactly 200 records remain.",
  "approximate quantity strengthened to exact",
);
expectQuantityDrift(
  "Nearly 100 users responded.",
  "About 100 users responded.",
  "below-target quantity changed to two-sided approximation",
);
expectQuantityDrift(
  "Several students asked questions.",
  "Many students asked questions.",
  "several strengthened to many",
);
expectQuantityDrift(
  "Many students asked questions.",
  "Several students asked questions.",
  "many weakened to several",
);

// Numeric-bound words should remain inert when they are not actually modifying
// a written number. These prose-only changes are outside this deterministic
// quantity contract and must not create a false hard quantity failure.
expectNoQuantityDrift(
  "We talked about the schedule.",
  "We talked around the schedule.",
  "non-numeric about-around prose",
);

console.log("qa:meaning:bounds passed");
