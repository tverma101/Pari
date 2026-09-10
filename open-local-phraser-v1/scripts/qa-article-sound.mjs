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

const article = loadTsModule(path.join(ROOT_DIR, "src/lib/nlp/articleSound.ts"));
const grammar = loadTsModule(path.join(ROOT_DIR, "src/lib/nlp/grammar.ts"));
const englishRepair = loadTsModule(path.join(ROOT_DIR, "src/lib/generation/englishGrammarRepair.ts"));

assert.equal(article.preferredIndefiniteArticle("hour"), "an");
assert.equal(article.preferredIndefiniteArticle("honest answer"), "an");
assert.equal(article.preferredIndefiniteArticle("university"), "a");
assert.equal(article.preferredIndefiniteArticle("useful tool"), "a");
assert.equal(article.preferredIndefiniteArticle("herb"), null);
assert.equal(article.preferredIndefiniteArticle("herbal remedy"), null);
assert.equal(article.preferredIndefiniteArticle("MRI"), null);
assert.equal(article.preferredIndefiniteArticle("URL"), null);

function hasArticleMismatch(text) {
  return grammar.grammarSafetyIssues(text).some((issue) => issue.id === "article-mismatch");
}

assert.equal(hasArticleMismatch("It took a hour."), true, "high-confidence a/an error was missed");
assert.equal(hasArticleMismatch("It took an hour."), false, "correct silent-h article was rejected");
assert.equal(hasArticleMismatch("It is an university program."), true, "high-confidence /juː/ article error was missed");
assert.equal(hasArticleMismatch("It is a university program."), false, "correct /juː/ article was rejected");
assert.equal(hasArticleMismatch("It is a herb."), false, "UK-style herb article was falsely rejected");
assert.equal(hasArticleMismatch("It is an herb."), false, "US-style herb article was falsely rejected");

assert.equal(
  englishRepair.repairEnglishGrammar("It took a hour."),
  "It took an hour.",
  "grammar repair did not correct a high-confidence article error",
);
assert.equal(
  englishRepair.repairEnglishGrammar("It is a herb."),
  "It is a herb.",
  "grammar repair forced one dialect for herb",
);
assert.equal(
  englishRepair.repairEnglishGrammar("It is an herb."),
  "It is an herb.",
  "grammar repair forced one dialect for herb",
);

console.log("qa:article:sound passed");
