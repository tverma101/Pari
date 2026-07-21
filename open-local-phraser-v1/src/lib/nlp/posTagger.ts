import type { PartOfSpeech } from "@/lib/types";

import { normalizeWord } from "./tokenizer";

const VERB_OVERRIDES = new Set([
  "show",
  "shows",
  "demonstrate",
  "demonstrates",
  "suggest",
  "suggests",
  "prove",
  "proves",
  "help",
  "helps",
  "improve",
  "improves",
  "affect",
  "affects",
  "influence",
  "influences",
]);

const ADJECTIVE_OVERRIDES = new Set([
  "important",
  "simple",
  "formal",
  "clear",
  "challenging",
  "complex",
  "demanding",
  "natural",
  "direct",
  "tricky",
  "arduous",
  "useful",
  "meaningful",
]);

const ADVERB_SUFFIXES = ["ly"];
const ADJECTIVE_SUFFIXES = ["ful", "ive", "ous", "able", "ible", "al"];
const VERB_SUFFIXES = ["ing", "ed", "ize", "ise"];
const NOUN_SUFFIXES = ["tion", "ment", "ness", "ity", "ship"];

export function guessPartOfSpeech(value: string): PartOfSpeech {
  const normalized = normalizeWord(value);

  if (normalized.includes(" ")) return "phrase";
  if (VERB_OVERRIDES.has(normalized)) return "verb";
  if (ADJECTIVE_OVERRIDES.has(normalized)) return "adjective";
  if (ADVERB_SUFFIXES.some((suffix) => normalized.endsWith(suffix))) return "adverb";
  if (VERB_SUFFIXES.some((suffix) => normalized.endsWith(suffix))) return "verb";
  if (ADJECTIVE_SUFFIXES.some((suffix) => normalized.endsWith(suffix))) return "adjective";
  if (NOUN_SUFFIXES.some((suffix) => normalized.endsWith(suffix))) return "noun";
  return "unknown";
}

export function grammarCompatibility(expected: PartOfSpeech, candidate: string): number {
  if (expected === "unknown") return 0.72;
  if (expected === "phrase") return candidate.includes(" ") ? 1 : 0.66;

  const actual = guessPartOfSpeech(candidate);
  if (actual === expected) return 1;
  if (actual === "unknown") return 0.7;
  return 0.52;
}
