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

const { extractProtectedSpans, validateProtectedContent } = loadTsModule(
  path.join(ROOT_DIR, "src/lib/safety/protectedContent.ts"),
);

function assertSafe(original, candidate, message) {
  const spans = extractProtectedSpans(original);
  const validation = validateProtectedContent(original, candidate, spans);
  assert.equal(
    validation.safe,
    true,
    `${message}: ${validation.reason ?? "unknown reason"}\nsource=${JSON.stringify(spans)}\ncandidate=${JSON.stringify(extractProtectedSpans(candidate))}`,
  );
}

function assertUnsafe(original, candidate, message) {
  const validation = validateProtectedContent(original, candidate);
  assert.equal(validation.safe, false, message);
}

assertSafe("The peak occurred at 3am.", "The peak occurred at 3 a.m.", "meridiem punctuation/spacing equivalence failed");
assertSafe("The meeting is at 3pm Thursday.", "The meeting is at 3:00 pm Thursday.", "implicit :00 equivalence failed");
assertSafe("The call starts at 3 PM EST.", "The call starts at 3:00 p.m. EST.", "timezone-preserving clock normalization failed");
assertSafe("The job runs at 15:30 UTC.", "The job runs at 15:30UTC.", "24-hour timezone spacing equivalence failed");
assertUnsafe("The call starts at 3 PM EST.", "The call starts at 4 PM EST.", "clock-value mutation was accepted");
assertUnsafe("The call starts at 3 PM EST.", "The call starts at 3 PM PST.", "timezone mutation was accepted");
assertUnsafe("The call starts at 3 PM.", "The call starts at 3 AM.", "meridiem mutation was accepted");

console.log("qa:protected:times passed");
