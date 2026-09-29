import type { PartOfSpeech } from "@/lib/types";

import { normalizeWord } from "./tokenizer";

const VERB_OVERRIDES = new Set([
  "use",
  "uses",
  "send",
  "sends",
  "connect",
  "connects",
  "review",
  "reviews",
  "find",
  "finds",
  "understand",
  "understands",
  "make",
  "makes",
  "give",
  "gives",
  "share",
  "shares",
  "deliver",
  "delivers",
  "transmit",
  "transmits",
  "forward",
  "forwards",
  "provide",
  "provides",
  "communicate",
  "communicates",
  "engage",
  "engages",
  "interact",
  "interacts",
  "relate",
  "relates",
  "contribute",
  "contributes",
  "asked",
  "inquire",
  "inquires",
  "explain",
  "explains",
  "organize",
  "organizes",
  "revise",
  "revises",
  "worked",
  "strengthen",
  "strengthens",
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
  "aids",
  "assists",
  "supports",
  "guides",
  "improve",
  "improves",
  "affect",
  "affects",
  "influence",
  "influences",
]);

const IRREGULAR_VERB_FORMS = new Set([
  "brought",
  "built",
  "came",
  "did",
  "drew",
  "felt",
  "found",
  "gave",
  "got",
  "had",
  "kept",
  "knew",
  "made",
  "ran",
  "said",
  "saw",
  "spoke",
  "taught",
  "told",
  "took",
  "thought",
  "understood",
  "went",
  "wrote",
]);

const NOUN_OVERRIDES = new Set([
  "communication",
  "system",
  "systems",
  "app",
  "apps",
  "user",
  "users",
  "way",
  "ways",
  "method",
  "methods",
  "perspective",
  "perspectives",
  "argument",
  "arguments",
  "researcher",
  "researchers",
  "editor",
  "editors",
  "writer",
  "writers",
  "model",
  "models",
  "evidence",
  "server",
  "servers",
  "class",
  "classes",
  "team",
  "teams",
  "tool",
  "tools",
  "application",
  "applications",
  "platform",
  "platforms",
  "assistant",
  "assistants",
  "aid",
  "skill",
  "skills",
  "draft",
  "drafts",
  "document",
  "documents",
  "content",
  "feedback",
  "paragraph",
  "paragraphs",
  "topic",
  "topics",
  "idea",
  "ideas",
  "meaning",
  "sentence",
  "sentences",
  "wording",
  "device",
  "devices",
  "software",
  "example",
  "examples",
  "result",
  "results",
  "suggestion",
  "suggestions",
  "process",
  "approach",
  "advice",
  "ability",
  "abilities",
  "strength",
  "strengths",
  "suggestion",
  "suggestions",
  "result",
  "results",
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
  "strong",
  "concise",
  "faster",
  "readable",
]);

const ADVERB_SUFFIXES = ["ly"];
const ADJECTIVE_SUFFIXES = ["ful", "ive", "ous", "able", "ible", "al"];
const VERB_SUFFIXES = ["ing", "ed", "ize", "ise"];
const NOUN_SUFFIXES = ["tion", "ment", "ness", "ity", "ship"];

export function guessPartOfSpeech(value: string): PartOfSpeech {
  const normalized = normalizeWord(value);

  if (normalized.includes(" ")) return "phrase";
  if (VERB_OVERRIDES.has(normalized)) return "verb";
  if (IRREGULAR_VERB_FORMS.has(normalized)) return "verb";
  if (NOUN_OVERRIDES.has(normalized)) return "noun";
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

  // A phrasal verb such as "drew on" is still a verb even though the whole
  // replacement contains spaces. Classifying the complete string as a
  // phrase made the ranker prefer single-word formal synonyms instead.
  const actual = candidate.includes(" ")
    ? guessPartOfSpeech(candidate.split(/\s+/)[0])
    : guessPartOfSpeech(candidate);
  if (actual === expected) return 1;
  if (actual === "unknown") return 0.7;
  return 0.52;
}
