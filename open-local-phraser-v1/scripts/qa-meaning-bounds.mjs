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

function ids(original, candidate) {
  return new Set(meaningContractIssues(original, candidate).map((issue) => issue.id));
}

function expectQuantitySafe(original, candidate, label) {
  assert(
    !ids(original, candidate).has("quantity-drift"),
    `${label}: equivalent numeric quantity relation was rejected`,
  );
}

function expectQuantityDrift(original, candidate, label) {
  assert(
    ids(original, candidate).has("quantity-drift"),
    `${label}: numeric quantity drift was accepted`,
  );
}

expectQuantitySafe(
  "At least 10 students attended.",
  "No less than 10 students attended.",
  "lower-inclusive synonyms",
);
expectQuantitySafe(
  "The room holds at most 30 people.",
  "The room holds up to 30 people.",
  "upper-inclusive synonyms",
);
expectQuantitySafe(
  "Approximately 200 records remain.",
  "Roughly 200 records remain.",
  "approximation synonyms",
);
expectQuantitySafe(
  "About 50% of the files changed.",
  "Around 50% of the files changed.",
  "about-around approximation synonyms",
);
expectQuantitySafe(
  "Exactly 12 examples are required.",
  "Precisely 12 examples are required.",
  "exactness synonyms",
);
expectQuantitySafe(
  "Nearly 100 users responded.",
  "Almost 100 users responded.",
  "near-below synonyms",
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

// Numeric-bound words should remain inert when they are not actually modifying
// a written number. These prose-only changes are outside this deterministic
// quantity contract and must not create a false hard failure.
expectQuantitySafe(
  "We talked about the schedule.",
  "We talked around the schedule.",
  "non-numeric about-around prose",
);

console.log("qa:meaning:bounds passed");
