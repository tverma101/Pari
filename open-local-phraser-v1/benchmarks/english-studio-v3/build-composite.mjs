#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const benchmarks = path.resolve(here, "..");

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

const suites = [
  {
    id: "eval-v1",
    file: path.join(benchmarks, "eval", "corpus.json"),
    data: readJson(path.join(benchmarks, "eval", "corpus.json")),
  },
  {
    id: "quillbot-frozen-v2",
    file: path.join(benchmarks, "quillbot", "corpus.frozen.json"),
    data: readJson(path.join(benchmarks, "quillbot", "corpus.frozen.json")),
  },
  {
    id: "paraphrase-v2",
    file: path.join(benchmarks, "paraphrase-v2", "corpus.json"),
    data: readJson(path.join(benchmarks, "paraphrase-v2", "corpus.json")),
  },
];

const interactive = readJson(path.join(here, "interactive.seed.json"));
const instances = [];

function pushInstance(source, operation, extra = {}) {
  instances.push({
    instanceId: `${source.suite}:${source.id}:${operation}${extra.strength ? `:${extra.strength}` : ""}`,
    sourceSuite: source.suite,
    sourceId: source.id,
    category: source.category,
    input: source.input,
    operation,
    ...extra,
  });
}

function paragraphOperations(source) {
  pushInstance(source, "paragraph_rewrite");
  pushInstance(source, "register_preserve");
  for (const strength of [15, 40, 60, 90]) {
    pushInstance(source, "rewrite_strength", { strength });
  }

  const grammarCategories = new Set([
    "broken_words",
    "fragment",
    "run_on",
    "tense_agreement",
    "register_shift",
    "broken_grammar",
    "grammar_minimal_edit",
    "sentence_structure",
  ]);
  if (grammarCategories.has(source.category)) pushInstance(source, "grammar_repair");

  const nonInventionCategories = new Set([
    "vague",
    "word_salad",
    "ambiguity_invention_trap",
    "ambiguity_non_invention",
  ]);
  if (nonInventionCategories.has(source.category)) pushInstance(source, "clarify_without_invention");

  const conciseCategories = new Set([
    "paragraph_unity_redundancy",
    "sentence_structure",
    "run_on",
  ]);
  if (conciseCategories.has(source.category)) pushInstance(source, "condense");

  const registerCategories = new Set(["register_shift", "register_tone"]);
  if (registerCategories.has(source.category)) {
    pushInstance(source, "more_conversational");
    pushInstance(source, "more_formal_bounded");
  }
}

for (const suite of suites) {
  for (const row of suite.data.cases ?? []) {
    const source = {
      suite: suite.id,
      id: row.id,
      category: row.category ?? "uncategorized",
      input: row.input,
    };
    paragraphOperations(source);
  }
}

const interactiveOperation = {
  word_to_phrase: "word_alternatives",
  phrase_to_word: "span_alternatives",
  phrase_to_phrase: "span_alternatives",
  clause_rewrite: "clause_alternatives",
  sentence_rewrite: "sentence_alternatives",
  split_join: "sentence_structure_alternatives",
  register_preserve: "span_alternatives",
  vocabulary_ceiling: "span_alternatives",
  collocation: "span_alternatives",
  protected_context: "span_alternatives",
};

for (const row of interactive.cases ?? []) {
  const source = {
    suite: "interactive-seed-v1",
    id: row.id,
    category: row.category,
    input: row.input,
  };
  pushInstance(source, interactiveOperation[row.category] ?? "span_alternatives", {
    selection: row.selection,
    requirements: row.requirements ?? [],
    candidateTargets: [10, 40],
  });

  // Every interactive target is also tested for edit containment and deep candidate diversity.
  pushInstance(source, "local_edit_containment", {
    selection: row.selection,
    requirements: row.requirements ?? [],
  });
  pushInstance(source, "alternative_diversity", {
    selection: row.selection,
    requirements: row.requirements ?? [],
    candidateTargets: [10, 40],
  });
}

const suiteCounts = {};
const operationCounts = {};
for (const item of instances) {
  suiteCounts[item.sourceSuite] = (suiteCounts[item.sourceSuite] ?? 0) + 1;
  operationCounts[item.operation] = (operationCounts[item.operation] ?? 0) + 1;
}

const output = path.join(here, "corpus.composite.jsonl");
fs.writeFileSync(output, instances.map((row) => JSON.stringify(row)).join("\n") + "\n");

const summary = {
  generatedAt: new Date().toISOString(),
  sourceCases: suites.reduce((sum, suite) => sum + (suite.data.cases?.length ?? 0), 0) + (interactive.cases?.length ?? 0),
  taskInstances: instances.length,
  suiteCounts,
  operationCounts,
  output,
};

console.log(JSON.stringify(summary, null, 2));
