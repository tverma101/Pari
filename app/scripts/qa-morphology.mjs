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
    compilerOptions: { esModuleInterop: true, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
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
  vm.runInThisContext(wrapper, { filename: absolutePath })(module.exports, localRequire, module, absolutePath, path.dirname(absolutePath));
  return module.exports;
}

const morphology = loadTsModule(path.join(ROOT_DIR, "src/lib/nlp/morphology.ts"));
const { rankCandidatesByRule } = loadTsModule(path.join(ROOT_DIR, "src/lib/ranking/ruleBasedRanker.ts"));

assert.equal(morphology.detectNounNumber("status"), "singular");
assert.equal(morphology.detectNounNumber("process"), "singular");
assert.equal(morphology.detectNounNumber("processes"), "plural");
assert.equal(morphology.detectNounNumber("people"), "plural");
assert.equal(morphology.detectNounNumber("series"), "unknown");

assert.equal(morphology.detectVerbForm("review"), "base");
assert.equal(morphology.detectVerbForm("reviews"), "third-person");
assert.equal(morphology.detectVerbForm("reviewed"), "past");
assert.equal(morphology.detectVerbForm("reviewing"), "gerund");
assert.equal(morphology.detectVerbForm("made use of"), "past");
assert(morphology.morphologyCompatibility("reviewed", "examined", "verb") > 0.95);
assert(morphology.morphologyCompatibility("reviewed", "examine", "verb") < 0.5);

assert.equal(morphology.detectAdjectiveDegree("faster"), "comparative");
assert.equal(morphology.detectAdjectiveDegree("more reliable"), "comparative");
assert.equal(morphology.detectAdjectiveDegree("best"), "superlative");
assert.equal(morphology.detectAdjectiveDegree("reliable"), "positive");

function option(id, original, replacement, pos) {
  return { id, original, replacement, partOfSpeech: pos, source: "static-bank", risk: "low", label: "natural" };
}

function context(sentence, selectedText, pos) {
  const selectionStart = sentence.indexOf(selectedText);
  return {
    fullText: sentence,
    sentence,
    selectedText,
    mode: "personal",
    strength: 3,
    freezeWords: [],
    partOfSpeech: pos,
    selectionStart,
    selectionEnd: selectionStart + selectedText.length,
    sentenceStart: 0,
  };
}

let ranked = rankCandidatesByRule(
  [option("singular", "writers", "author", "noun"), option("plural", "writers", "authors", "noun")],
  context("Several writers reviewed the draft.", "writers", "noun"),
);
assert.equal(ranked[0].option.replacement, "authors", "plural noun morphology did not win in a plural slot");

ranked = rankCandidatesByRule(
  [option("past", "review", "examined", "verb"), option("base", "review", "examine", "verb")],
  context("They can review drafts.", "review", "verb"),
);
assert.equal(ranked[0].option.replacement, "examine", "modal verb slot did not prefer a base-form replacement");

ranked = rankCandidatesByRule(
  [option("positive", "faster", "rapid", "adjective"), option("comparative", "faster", "quicker", "adjective")],
  context("This route is faster than the other route.", "faster", "adjective"),
);
assert.equal(ranked[0].option.replacement, "quicker", "comparative slot did not preserve degree");

ranked = rankCandidatesByRule(
  [option("singular", "methods", "approach", "noun"), option("plural", "methods", "approaches", "noun")],
  context("These methods work across domains.", "methods", "noun"),
);
assert.equal(ranked[0].option.replacement, "approaches", "plural determiner slot did not prefer a plural noun");

console.log("qa:morphology passed");
