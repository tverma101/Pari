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

const { rankCandidatesByRule } = loadTsModule(path.join(ROOT_DIR, "src/lib/ranking/ruleBasedRanker.ts"));

function context(sentence, selectedText, partOfSpeech = "unknown") {
  const selectionStart = sentence.indexOf(selectedText);
  assert(selectionStart >= 0, `Missing selection ${JSON.stringify(selectedText)} in ${JSON.stringify(sentence)}`);
  return {
    fullText: sentence,
    sentence,
    selectedText,
    mode: "personal",
    strength: 2,
    freezeWords: [],
    partOfSpeech,
    selectionStart,
    selectionEnd: selectionStart + selectedText.length,
    sentenceStart: 0,
  };
}

function option(original, replacement, id = replacement) {
  return {
    id,
    original,
    replacement,
    label: "natural",
    source: "static-bank",
    risk: "low",
  };
}

function score(sentence, selectedText, replacement, partOfSpeech = "unknown") {
  return rankCandidatesByRule(
    [option(selectedText, replacement)],
    context(sentence, selectedText, partOfSpeech),
  )[0].score;
}

function expectPreferred(sentence, selectedText, preferred, rejected, label) {
  const ranked = rankCandidatesByRule(
    [option(selectedText, rejected, `bad-${label}`), option(selectedText, preferred, `good-${label}`)],
    context(sentence, selectedText),
  );
  assert.equal(ranked[0].option.replacement, preferred, `${label}: ranked ${ranked[0].option.replacement} above ${preferred}`);
}

// English indefinite articles are selected by the following sound, not the
// first written letter. These pairs exercise both silent-h and /juː/ cases.
assert(
  score("It was an old choice.", "old", "honest") > score("It was a old choice.", "old", "honest"),
  "silent-h vowel sound did not prefer 'an honest'",
);
assert(
  score("It was a old choice.", "old", "useful") > score("It was an old choice.", "old", "useful"),
  "useful /juː/ sound did not prefer 'a useful'",
);
assert(
  score("It was a old campus.", "old", "university") > score("It was an old campus.", "old", "university"),
  "university /juː/ sound did not prefer 'a university'",
);
assert(
  score("It took an old interval.", "old", "hour") > score("It took a old interval.", "old", "hour"),
  "hour vowel sound did not prefer 'an hour'",
);

expectPreferred(
  "The result is the same as before.",
  "as",
  "as",
  "than",
  "same-as frame",
);
expectPreferred(
  "The result is similar to the draft.",
  "to",
  "to",
  "from",
  "similar-to frame",
);
expectPreferred(
  "The result is distinct from the draft.",
  "from",
  "from",
  "to",
  "distinct-from frame",
);
expectPreferred(
  "The result is different from the draft.",
  "from",
  "from",
  "since",
  "different-from rejects temporal since",
);

const differentFrom = score("The result is different from the draft.", "from", "from");
const differentThan = score("The result is different from the draft.", "from", "than");
const differentTo = score("The result is different from the draft.", "from", "to");
assert(Math.abs(differentFrom - differentThan) < 1e-9, "standard 'different than' was penalized");
assert(Math.abs(differentFrom - differentTo) < 1e-9, "standard 'different to' was penalized");

// The comparison-frame rule must only inspect the link word itself. It should
// not punish ordinary content-word substitutions after “same”.
const sameMethod = score("They use the same process.", "process", "method", "noun");
const clearMethod = score("They use the clear process.", "process", "method", "noun");
assert(
  Math.abs(sameMethod - clearMethod) < 1e-9,
  `content-word rewrite after 'same' received a stray comparison penalty (${sameMethod} vs ${clearMethod})`,
);

console.log("qa:rule:ranker passed");
