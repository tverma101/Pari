#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const benchmarks = path.resolve(here, "..");

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function stableKey(value) {
  return crypto.createHash("sha256").update(String(value)).digest("hex");
}

function stableTake(rows, count, salt) {
  return [...rows]
    .sort((a, b) => stableKey(`${salt}:${a.suite}:${a.id}`).localeCompare(stableKey(`${salt}:${b.suite}:${b.id}`)))
    .slice(0, Math.min(count, rows.length));
}

function normalize(suite, row) {
  return {
    suite,
    id: row.id,
    category: row.category ?? "uncategorized",
    input: row.input,
    selection: row.selection,
    requirements: row.requirements ?? [],
  };
}

const evalV1 = readJson(path.join(benchmarks, "eval", "corpus.json")).cases.map((x) => normalize("eval-v1", x));
const quillbot = readJson(path.join(benchmarks, "quillbot", "corpus.frozen.json")).cases.map((x) => normalize("quillbot-frozen-v2", x));
const paraphraseV2 = readJson(path.join(benchmarks, "paraphrase-v2", "corpus.json")).cases.map((x) => normalize("paraphrase-v2", x));
const interactive = readJson(path.join(here, "interactive.seed.json")).cases.map((x) => normalize("interactive-v2", x));

const routes = [];
const seenInstance = new Set();

function add(route, row, extra = {}) {
  const instanceId = `${route}:${row.suite}:${row.id}`;
  if (seenInstance.has(instanceId)) return;
  seenInstance.add(instanceId);
  routes.push({
    instanceId,
    route,
    sourceSuite: row.suite,
    sourceId: row.id,
    category: row.category,
    input: row.input,
    ...(row.selection ? { selection: row.selection } : {}),
    ...(row.requirements?.length ? { requirements: row.requirements } : {}),
    ...extra,
  });
}

// Interactive cases have explicit selected spans. Never fabricate a selected word
// from paragraph corpora simply to increase the lexical benchmark count.
const wordPhraseCategories = new Set([
  "word_to_phrase",
  "phrase_to_word",
  "phrase_to_phrase",
  "register_preserve",
  "vocabulary_ceiling",
  "collocation",
  "expansion_compression",
]);
for (const row of interactive.filter((x) => wordPhraseCategories.has(x.category))) {
  add("word_phrase_alternatives", row, { candidateTargets: [3, 5, 10, 20, 40] });
}

const sentenceCategories = new Set(["sentence_rewrite", "split_join", "clause_rewrite"]);
for (const row of interactive.filter((x) => sentenceCategories.has(x.category))) {
  add("sentence_alternatives", row, { candidateTargets: [3, 5, 10] });
}

for (const row of interactive.filter((x) => x.category === "protected_context")) {
  add("protected_containment", row);
}

// Paragraph first-draft set: standards-traced cases first, then a small hard-tail
// supplement if necessary. This is intentionally not the full release corpus.
const paragraphTarget = 35;
const paraPrimary = stableTake(paraphraseV2, paragraphTarget, "paragraph-v1");
for (const row of paraPrimary) add("paragraph_first_draft", row);
if (paraPrimary.length < paragraphTarget) {
  for (const row of stableTake(quillbot, paragraphTarget - paraPrimary.length, "paragraph-hard-tail")) {
    add("paragraph_first_draft", row);
  }
}

// Safety set prioritizes categories where exact relationships/anchors matter.
const safetyCategoryHints = new Set([
  "canary",
  "meaning_equivalence",
  "logical_relations",
  "reference_coreference",
  "modality_negation_precision",
  "factual_anchors",
  "ambiguity_non_invention",
  "ambiguity_invention_trap",
]);
const safetyPool = [...evalV1, ...paraphraseV2, ...quillbot].filter((x) => safetyCategoryHints.has(x.category));
for (const row of stableTake(safetyPool, 30, "safety-v1")) add("safety_meaning", row);

// Strength/register uses explicit interactive register/vocabulary cases plus
// standards-traced register cases. Each source is evaluated at all four strengths
// by the runner; do not multiply them into fake unique source counts here.
const strengthInteractive = interactive.filter((x) => ["register_preserve", "vocabulary_ceiling"].includes(x.category));
const strengthExternal = paraphraseV2.filter((x) => ["register_tone", "lexical_collocation", "meaning_equivalence"].includes(x.category));
const strengthPool = [...strengthInteractive, ...stableTake(strengthExternal, 13, "strength-v1")];
for (const row of stableTake(strengthPool, 25, "strength-final-v1")) {
  add("strength_register", row, { strengths: [15, 40, 60, 90] });
}

// Add a containment check for every interactive selected span, but keep it as a
// correlated task instance rather than pretending it is another unique source.
for (const row of interactive) {
  add("local_edit_containment", row);
}

const uniqueSources = new Set(routes.map((x) => `${x.sourceSuite}:${x.sourceId}`));
const countsByRoute = {};
for (const row of routes) countsByRoute[row.route] = (countsByRoute[row.route] ?? 0) + 1;

const externalModules = [
  {
    id: "smart-word-suggestions",
    route: "word_phrase_alternatives",
    purpose: "human-annotated contextual substitution coverage/ranking",
    dataPolicy: "external frozen evaluation module; do not copy into this generated core",
  },
  {
    id: "tsar-english",
    route: "word_phrase_alternatives",
    purpose: "human lexical alternatives and ranking metrics",
    dataPolicy: "external frozen evaluation module",
  },
  {
    id: "jfleg",
    route: "grammar_fluency_release",
    purpose: "human fluency corrections",
    dataPolicy: "release validation; not required for every fast iteration",
  },
  {
    id: "iterater-holdout",
    route: "sentence_paragraph_release",
    purpose: "real human revision behavior",
    dataPolicy: "official dev/test only for evaluation",
  },
];

const output = path.join(here, "v1-core.internal.jsonl");
fs.writeFileSync(output, routes.map((row) => JSON.stringify(row)).join("\n") + "\n");

const manifest = {
  version: 1,
  generatedAt: new Date().toISOString(),
  design: "internal V1 fast core; external gold suites stay separate",
  uniqueInternalSources: uniqueSources.size,
  internalTaskInstances: routes.length,
  countsByRoute,
  externalModules,
  honestyRule: "Do not claim a 200-source gold suite until required external modules are loaded and counted. Do not fabricate selected spans from paragraph corpora.",
  output,
};

fs.writeFileSync(path.join(here, "v1-core.manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
console.log(JSON.stringify(manifest, null, 2));
