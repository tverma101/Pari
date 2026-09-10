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

function expectSafe(original, candidate, label) {
  const found = issues(original, candidate);
  assert.deepEqual(found, [], `${label}: equivalent certainty wording produced ${JSON.stringify(found)}`);
}

function expectCertaintyDrift(original, candidate, label) {
  const found = issues(original, candidate);
  assert(
    found.some((issue) => issue.id === "certainty-drift"),
    `${label}: certainty change was accepted (${JSON.stringify(found)})`,
  );
}

expectSafe(
  "Maybe the update works.",
  "Perhaps the update works.",
  "maybe-perhaps possibility equivalence",
);
expectSafe(
  "It is possible that the update works.",
  "It is possibly the case that the update works.",
  "possible-possibly equivalence",
);
expectSafe(
  "The update will probably work.",
  "The update will likely work.",
  "probably-likely equivalence",
);
expectSafe(
  "The update will definitely work.",
  "The update will certainly work.",
  "definitely-certainly equivalence",
);

expectCertaintyDrift(
  "Maybe the update works.",
  "The update probably works.",
  "possibility strengthened to probability",
);
expectCertaintyDrift(
  "The update will probably work.",
  "The update will definitely work.",
  "probability strengthened to certainty",
);
expectCertaintyDrift(
  "The update will definitely work.",
  "The update might work.",
  "certainty weakened to possibility",
);
expectCertaintyDrift(
  "The update is unlikely to fail.",
  "The update is likely to fail.",
  "unlikely reversed to likely",
);
expectCertaintyDrift(
  "The update will probably work.",
  "The update will work.",
  "probability marker deleted",
);
expectCertaintyDrift(
  "The update will work.",
  "The update will probably work.",
  "unsupported probability inserted",
);

console.log("qa:meaning:certainty passed");
