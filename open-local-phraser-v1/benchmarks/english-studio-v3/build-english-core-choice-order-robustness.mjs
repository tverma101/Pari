#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const seed = JSON.parse(fs.readFileSync(path.join(here, "english-core-shadow.seed.json"), "utf8"));
const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

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

function secondOrder(first) {
  if (first.length <= 1) return [...first];
  if (first.length === 2) return [first[1], first[0]];
  return [...first.slice(1), first[0]];
}

function baseChoices(row) {
  switch (row.task) {
    case "same_sense":
    case "same_meaning": return ["same", "different"];
    case "relation_preservation": return ["preserved", "changed"];
    case "acceptability_pair": return [row.sentenceA, row.sentenceB];
    case "best_substitute":
    case "minimal_pair":
    case "closer_register":
    case "closer_meaning_and_register":
    case "more_natural":
    case "relation_label": return row.choices;
    case "sentence_order": return row.choices.map((x) => x.map((n) => n + 1).join("-"));
    default: return null;
  }
}

function baseGoldIndex(row) {
  switch (row.task) {
    case "same_sense":
    case "same_meaning": return ["same", "different"].indexOf(row.answer);
    case "relation_preservation": return ["preserved", "changed"].indexOf(row.answer);
    case "acceptability_pair": return letters.indexOf(row.answer);
    case "best_substitute":
    case "minimal_pair":
    case "relation_label": return row.choices.indexOf(row.answer);
    case "closer_register":
    case "closer_meaning_and_register":
    case "more_natural": return row.answer;
    case "sentence_order": return row.choices.findIndex((x) => JSON.stringify(x) === JSON.stringify(row.answer));
    default: return -1;
  }
}

function prefix(row) {
  switch (row.task) {
    case "same_sense":
      return `Target word: ${row.target}\nSentence 1: ${row.sentenceA}\nSentence 2: ${row.sentenceB}\nDoes the target have the same meaning in both sentences?`;
    case "best_substitute":
      return `Sentence: ${row.sentence}\nTarget text: ${row.target}\nWhich replacement best preserves the target meaning and sounds natural in this exact sentence?`;
    case "minimal_pair":
      return `Choose the word that makes the most natural standard-English expression.\nSentence: ${row.sentence}`;
    case "acceptability_pair":
      return "Which sentence is more acceptable in standard written English?";
    case "same_meaning":
      return `Sentence 1: ${row.sentenceA}\nSentence 2: ${row.sentenceB}\nDo these sentences preserve the same meaning?`;
    case "closer_register":
    case "closer_meaning_and_register":
      return `Source: ${row.source}\nWhich option best preserves the source meaning, intensity, and register?`;
    case "more_natural":
      return "Which option is more natural standard English?";
    case "relation_preservation":
      return `Source: ${row.source}\nCandidate: ${row.candidate}\nDoes the candidate preserve the source relation/meaning?`;
    case "relation_label":
      return `Sentence: ${row.sentence}\nWhich discourse relation is expressed?`;
    case "sentence_order":
      return `Sentences:\n${row.sentences.map((s, i) => `${i + 1}. ${s}`).join("\n")}\nWhich ordering is most coherent?`;
    default:
      return null;
  }
}

function render(row, order) {
  const choices = baseChoices(row);
  const p = prefix(row);
  if (!choices || !p) return null;
  return `${p}\n${order.map((baseIndex, i) => `${letters[i]}. ${choices[baseIndex]}`).join("\n")}\nAnswer only with the letter.`;
}

const tasks = [];
const answers = {};
let baseCases = 0;
for (const row of seed.cases) {
  const choices = baseChoices(row);
  const goldIndex = baseGoldIndex(row);
  if (!choices || goldIndex < 0) continue;
  baseCases += 1;
  const first = permutation(choices.length, row.id);
  const orders = [first, secondOrder(first)];
  for (let variant = 0; variant < orders.length; variant += 1) {
    const order = orders[variant];
    const id = `${row.id}::o${variant}`;
    const goldDisplayedIndex = order.indexOf(goldIndex);
    const baseIndexByLetter = Object.fromEntries(order.map((baseIndex, i) => [letters[i], baseIndex]));
    tasks.push({
      id,
      baseId: row.id,
      orderVariant: variant,
      dimension: row.dimension,
      task: row.task,
      phenomenon: row.phenomenon ?? null,
      generative: false,
      prompt: render(row, order),
      // Frozen from the structured choice array length, never the gold index.
      allowedChoices: letters.slice(0, order.length).split(""),
    });
    answers[id] = {
      expectedLetter: letters[goldDisplayedIndex],
      goldBaseChoiceIndex: goldIndex,
      baseIndexByLetter,
    };
  }
}

fs.writeFileSync(
  path.join(here, "english-core-choice-order-robustness.jsonl"),
  tasks.map((x) => JSON.stringify(x)).join("\n") + "\n",
);
fs.writeFileSync(
  path.join(here, "english-core-choice-order-robustness.answers.json"),
  JSON.stringify({ version: 1, answers }, null, 2) + "\n",
);
fs.writeFileSync(
  path.join(here, "english-core-choice-order-robustness.manifest.json"),
  JSON.stringify({
    version: 1,
    source: "english-core-shadow.seed.json",
    baseCases,
    taskInstances: tasks.length,
    presentationsPerCase: 2,
    allowedChoices:
      "Every task freezes allowedChoices as the first N letters for its N rendered options, derived from the structured choice array length and independent of goldBaseChoiceIndex.",
    orderPolicy: "presentation 0 uses deterministic SHA-256 order; presentation 1 swaps binary options or cyclically rotates multi-option choices so the gold position changes",
    purpose: "measure choice-order robustness separately from English competence score",
    researchBasis: [
      "Wei et al., Findings ACL 2024, Unveiling Selection Biases: Exploring Order and Token Sensitivity in Large Language Models",
      "Alzahrani et al., ACL 2024 benchmark perturbation/answer-order sensitivity evidence"
    ]
  }, null, 2) + "\n",
);

console.log(JSON.stringify({ baseCases, taskInstances: tasks.length }, null, 2));
