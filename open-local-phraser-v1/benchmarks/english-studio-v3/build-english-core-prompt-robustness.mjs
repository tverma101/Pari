#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const seed = JSON.parse(fs.readFileSync(path.join(here, "english-core-shadow.seed.json"), "utf8"));
const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

// TACL 2024 multi-prompt evaluation work shows that model rankings can move under
// intent-preserving instruction paraphrases. This lane therefore keeps the item,
// options, and gold answer fixed while varying only task wording.
const PROMPT_VARIANTS = ["canonical", "terse", "alternate"];

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

function shuffled(row, choices) {
  return permutation(choices.length, row.id).map((i) => choices[i]);
}

function options(choices) {
  return choices.map((x, i) => `${letters[i]}. ${x}`).join("\n");
}

function choose(prefix, choices, variant) {
  if (variant === "canonical") return `${prefix}\n${options(choices)}\nAnswer only with the letter.`;
  if (variant === "terse") return `${prefix}\n${options(choices)}\nChoose one option. Reply with its letter only.`;
  return `${prefix}\n${options(choices)}\nWhich option is correct? Give only the option letter.`;
}

function relationQuestion(row, variant) {
  const choices = shuffled(row, ["preserved", "changed"]);
  const prefix = variant === "alternate"
    ? `Original: ${row.source}\nRewrite: ${row.candidate}\nIs the original relation and meaning kept, or changed?`
    : `Source: ${row.source}\nCandidate: ${row.candidate}\nDoes the candidate preserve the source relation/meaning?`;
  return choose(prefix, choices, variant);
}

function renderForced(row, variant) {
  switch (row.task) {
    case "same_sense": {
      const prefix = variant === "alternate"
        ? `Word: ${row.target}\nContext A: ${row.sentenceA}\nContext B: ${row.sentenceB}\nIs the word used with the same sense in both contexts?`
        : `Target word: ${row.target}\nSentence 1: ${row.sentenceA}\nSentence 2: ${row.sentenceB}\nDoes the target have the same meaning in both sentences?`;
      return choose(prefix, shuffled(row, ["same", "different"]), variant);
    }
    case "best_substitute": {
      const prefix = variant === "alternate"
        ? `Context: ${row.sentence}\nReplace: ${row.target}\nSelect the replacement that best keeps this exact contextual meaning and remains natural English.`
        : `Sentence: ${row.sentence}\nTarget text: ${row.target}\nWhich replacement best preserves the target meaning and sounds natural in this exact sentence?`;
      return choose(prefix, shuffled(row, row.choices), variant);
    }
    case "minimal_pair": {
      const prefix = variant === "alternate"
        ? `Complete this sentence with the option that forms the most natural standard-English expression:\n${row.sentence}`
        : `Choose the word that makes the most natural standard-English expression.\nSentence: ${row.sentence}`;
      return choose(prefix, shuffled(row, row.choices), variant);
    }
    case "acceptability_pair": {
      const prefix = variant === "alternate"
        ? "Choose the sentence that is more acceptable in standard written English."
        : "Which sentence is more acceptable in standard written English?";
      return choose(prefix, shuffled(row, [row.sentenceA, row.sentenceB]), variant);
    }
    case "same_meaning": {
      const prefix = variant === "alternate"
        ? `Text A: ${row.sentenceA}\nText B: ${row.sentenceB}\nDo A and B express the same meaning?`
        : `Sentence 1: ${row.sentenceA}\nSentence 2: ${row.sentenceB}\nDo these sentences preserve the same meaning?`;
      return choose(prefix, shuffled(row, ["same", "different"]), variant);
    }
    case "closer_register":
    case "closer_meaning_and_register": {
      const prefix = variant === "alternate"
        ? `Original: ${row.source}\nSelect the rewrite that best keeps the original meaning, strength, and style/register.`
        : `Source: ${row.source}\nWhich option best preserves the source meaning, intensity, and register?`;
      return choose(prefix, shuffled(row, row.choices), variant);
    }
    case "more_natural":
      return choose(
        variant === "alternate" ? "Select the expression that sounds more natural in standard English." : "Which option is more natural standard English?",
        shuffled(row, row.choices),
        variant,
      );
    case "relation_preservation":
      return relationQuestion(row, variant);
    case "relation_label": {
      const prefix = variant === "alternate"
        ? `Text: ${row.sentence}\nWhat relation does the text express?`
        : `Sentence: ${row.sentence}\nWhich discourse relation is expressed?`;
      return choose(prefix, shuffled(row, row.choices), variant);
    }
    case "sentence_order": {
      const choices = shuffled(row, row.choices.map((x) => x.map((n) => n + 1).join("-")));
      const prefix = variant === "alternate"
        ? `Sentences:\n${row.sentences.map((s, i) => `${i + 1}. ${s}`).join("\n")}\nSelect the ordering that forms the most coherent sequence.`
        : `Sentences:\n${row.sentences.map((s, i) => `${i + 1}. ${s}`).join("\n")}\nWhich ordering is most coherent?`;
      return choose(prefix, choices, variant);
    }
    default:
      return null;
  }
}

function renderGenerative(row, variant) {
  if (row.task === "generate_span_alternatives") {
    if (variant === "canonical") return `Sentence: ${row.sentence}\nSelected text: ${row.selection}\nGive ${row.count} materially useful replacements for the selected text that fit this exact sentence. Candidate length may change. Requirements: ${row.requirements.join("; ")}. Return only the candidates, one per line.`;
    if (variant === "terse") return `In this sentence, replace only "${row.selection}" with ${row.count} useful context-fitting alternatives. Alternatives may be shorter or longer. Keep meaning/register. One candidate per line.\nSentence: ${row.sentence}`;
    return `Context: ${row.sentence}\nTarget span: ${row.selection}\nList ${row.count} natural ways to express that same span in this context. Preserve the intended meaning and style; length may vary. Output only the alternatives.`;
  }
  if (row.task === "rewrite_sentence") {
    if (variant === "canonical") return `Rewrite this sentence in ${row.count} materially different natural ways. Requirements: ${row.requirements.join("; ")}.\nSentence: ${row.sentence}`;
    if (variant === "terse") return `Give ${row.count} natural rewrites of this sentence. Keep the same meaning and register, but vary the structure.\n${row.sentence}`;
    return `Produce ${row.count} distinct English alternatives for the sentence below. Preserve all claims and the original voice; avoid unnecessary formality.\n${row.sentence}`;
  }
  if (row.task === "rewrite_paragraph") {
    if (variant === "canonical") return `Rewrite this paragraph as a useful editable alternative. Requirements: ${row.requirements.join("; ")}.\nParagraph: ${row.text}`;
    if (variant === "terse") return `Rewrite the paragraph naturally while preserving every claim and its register. Do not add information.\n${row.text}`;
    return `Create one alternative version of this paragraph for further editing. Keep the facts, logic, first-person stance, and level of formality unchanged unless the wording itself needs to move.\n${row.text}`;
  }
  if (row.task === "split_join") {
    if (variant === "canonical") return `Rewrite the text using the requested split/join behavior. Requirements: ${row.requirements.join("; ")}.\nText: ${row.text}`;
    if (variant === "terse") return `Join or split these sentences as requested while preserving every claim and the original register.\n${row.text}`;
    return `Restructure the sentence boundaries naturally without changing meaning, negation, or style.\n${row.text}`;
  }
  return null;
}

const tasks = [];
for (const row of seed.cases) {
  for (let i = 0; i < PROMPT_VARIANTS.length; i += 1) {
    const variant = PROMPT_VARIANTS[i];
    const generative = row.dimension === "generative_expression";
    const prompt = generative ? renderGenerative(row, variant) : renderForced(row, variant);
    if (!prompt) throw new Error(`Unsupported task ${row.task} (${row.id})`);
    tasks.push({
      id: `${row.id}::p${i}`,
      baseId: row.id,
      promptVariant: variant,
      dimension: row.dimension,
      task: row.task,
      phenomenon: row.phenomenon ?? null,
      generative,
      prompt,
    });
  }
}

fs.writeFileSync(path.join(here, "english-core-prompt-robustness.jsonl"), tasks.map((x) => JSON.stringify(x)).join("\n") + "\n");
fs.writeFileSync(path.join(here, "english-core-prompt-robustness.manifest.json"), JSON.stringify({
  version: 1,
  source: "english-core-shadow.seed.json",
  promptVariants: PROMPT_VARIANTS,
  baseCases: seed.cases.length,
  taskInstances: tasks.length,
  isolationRule: "Within a base case, item content, answer choices, and deterministic choice order stay fixed; only instruction wording changes.",
  interpretation: "Report mean, worst-prompt, prompt spread, answer consistency, and all-prompts-correct. Do not choose the best prompt after seeing model results.",
  researchBasis: [
    "Mizrahi et al., TACL 2024, State of What Art? A Call for Multi-Prompt LLM Evaluation",
    "Zhuo et al., Findings EMNLP 2024, ProSA",
    "Chatterjee et al., Findings EMNLP 2024, POSIX"
  ]
}, null, 2) + "\n");

console.log(JSON.stringify({ baseCases: seed.cases.length, variants: PROMPT_VARIANTS.length, taskInstances: tasks.length }, null, 2));
