#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const config = JSON.parse(fs.readFileSync(path.join(here, "english-core-config.json"), "utf8"));
const seed = JSON.parse(fs.readFileSync(path.join(here, "english-core-shadow.seed.json"), "utf8"));

const weights = Object.values(config.composite.weights);
if (weights.reduce((a, b) => a + b, 0) !== 100) {
  throw new Error("English Core weights must sum to 100");
}

const ids = new Set();
for (const row of seed.cases) {
  if (!row.id || !row.dimension || !row.task) throw new Error(`Invalid row: ${JSON.stringify(row)}`);
  if (ids.has(row.id)) throw new Error(`Duplicate id: ${row.id}`);
  ids.add(row.id);
  if (!config.dimensions[row.dimension]) throw new Error(`Unknown dimension ${row.dimension} in ${row.id}`);
}

const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

// LLM multiple-choice scores can change substantially when answer choices move.
// Deterministically permute every forced-choice item's options so the handcrafted
// seed cannot leak a "correct answer is usually first" shortcut. The scorer uses
// the same ID-derived permutation to recover the gold position without exposing it
// in the model-visible task file.
function permutation(length, id) {
  const order = Array.from({ length }, (_, i) => i);
  for (let i = length - 1; i > 0; i -= 1) {
    const digest = crypto.createHash("sha256").update(`${id}:option:${i}`).digest();
    const value = digest.readUInt32BE(0);
    const j = value % (i + 1);
    [order[i], order[j]] = [order[j], order[i]];
  }
  return order;
}

function shuffledChoices(row, choices) {
  const order = permutation(choices.length, row.id);
  return order.map((i) => choices[i]);
}

function choicePrompt(prefix, choices) {
  return `${prefix}\n${choices.map((choice, i) => `${letters[i]}. ${choice}`).join("\n")}\nAnswer only with the letter.`;
}

function render(row) {
  switch (row.task) {
    case "same_sense":
      return choicePrompt(
        `Target word: ${row.target}\nSentence 1: ${row.sentenceA}\nSentence 2: ${row.sentenceB}\nDoes the target have the same meaning in both sentences?`,
        shuffledChoices(row, ["same", "different"]),
      );
    case "best_substitute":
      return choicePrompt(
        `Sentence: ${row.sentence}\nTarget text: ${row.target}\nWhich replacement best preserves the target meaning and sounds natural in this exact sentence?`,
        shuffledChoices(row, row.choices),
      );
    case "minimal_pair":
      return choicePrompt(
        `Choose the word that makes the most natural standard-English expression.\nSentence: ${row.sentence}`,
        shuffledChoices(row, row.choices),
      );
    case "acceptability_pair":
      return choicePrompt(
        "Which sentence is more acceptable in standard written English?",
        shuffledChoices(row, [row.sentenceA, row.sentenceB]),
      );
    case "same_meaning":
      return choicePrompt(
        `Sentence 1: ${row.sentenceA}\nSentence 2: ${row.sentenceB}\nDo these sentences preserve the same meaning?`,
        shuffledChoices(row, ["same", "different"]),
      );
    case "closer_register":
    case "closer_meaning_and_register":
      return choicePrompt(
        `Source: ${row.source}\nWhich option best preserves the source meaning, intensity, and register?`,
        shuffledChoices(row, row.choices),
      );
    case "more_natural":
      return choicePrompt("Which option is more natural standard English?", shuffledChoices(row, row.choices));
    case "relation_preservation":
      return choicePrompt(
        `Source: ${row.source}\nCandidate: ${row.candidate}\nDoes the candidate preserve the source relation/meaning?`,
        shuffledChoices(row, ["preserved", "changed"]),
      );
    case "relation_label":
      return choicePrompt(`Sentence: ${row.sentence}\nWhich discourse relation is expressed?`, shuffledChoices(row, row.choices));
    case "sentence_order":
      return choicePrompt(
        `Sentences:\n${row.sentences.map((s, i) => `${i + 1}. ${s}`).join("\n")}\nWhich ordering is most coherent?`,
        shuffledChoices(row, row.choices.map((x) => x.map((n) => n + 1).join("-"))),
      );
    case "generate_span_alternatives":
      return `Sentence: ${row.sentence}\nSelected text: ${row.selection}\nGive ${row.count} materially useful replacements for the selected text that fit this exact sentence. Candidate length may change. Requirements: ${row.requirements.join("; ")}. Return only the candidates, one per line.`;
    case "rewrite_sentence":
      return `Rewrite this sentence in ${row.count} materially different natural ways. Requirements: ${row.requirements.join("; ")}.\nSentence: ${row.sentence}`;
    case "rewrite_paragraph":
      return `Rewrite this paragraph as a useful editable alternative. Requirements: ${row.requirements.join("; ")}.\nParagraph: ${row.text}`;
    case "split_join":
      return `Rewrite the text using the requested split/join behavior. Requirements: ${row.requirements.join("; ")}.\nText: ${row.text}`;
    default:
      throw new Error(`Unsupported task ${row.task} (${row.id})`);
  }
}

const tasks = seed.cases.map((row) => ({
  id: row.id,
  dimension: row.dimension,
  task: row.task,
  phenomenon: row.phenomenon ?? null,
  prompt: render(row),
  generative: row.dimension === "generative_expression",
}));

const countsByDimension = {};
for (const row of tasks) countsByDimension[row.dimension] = (countsByDimension[row.dimension] ?? 0) + 1;

fs.writeFileSync(path.join(here, "english-core-shadow.jsonl"), tasks.map((x) => JSON.stringify(x)).join("\n") + "\n");
fs.writeFileSync(
  path.join(here, "english-core-shadow.manifest.json"),
  JSON.stringify({
    version: 2,
    source: "english-core-shadow.seed.json",
    cases: tasks.length,
    countsByDimension,
    optionOrder: "deterministic SHA-256 permutation per case ID for every forced-choice task",
    answerLeakageRule: "Generated task JSONL contains prompts but never gold answers. Scoring reads gold only from the seed file and reconstructs the same option permutation.",
    compositeRule: config.composite.rule,
  }, null, 2) + "\n",
);

console.log(JSON.stringify({ cases: tasks.length, countsByDimension }, null, 2));
