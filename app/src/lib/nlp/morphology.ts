import type { PartOfSpeech } from "@/lib/types";

import { normalizeWord } from "./tokenizer";

export type NounNumber = "singular" | "plural" | "unknown";
export type VerbForm = "base" | "third-person" | "past" | "gerund" | "unknown";
export type AdjectiveDegree = "positive" | "comparative" | "superlative" | "unknown";

const IRREGULAR_PLURALS = new Set([
  "children",
  "feet",
  "geese",
  "men",
  "mice",
  "people",
  "teeth",
  "women",
]);

const INVARIANT_NOUNS = new Set([
  "aircraft",
  "deer",
  "fish",
  "moose",
  "offspring",
  "series",
  "sheep",
  "species",
]);

// Common singular nouns whose spelling ends in s. Keeping this list lexical
// is safer than treating every trailing s as plurality; the rule itself is
// domain-independent and applies wherever these words occur.
const SINGULAR_S_NOUNS = new Set([
  "analysis",
  "basis",
  "business",
  "class",
  "crisis",
  "diagnosis",
  "economics",
  "ethics",
  "focus",
  "gas",
  "mathematics",
  "news",
  "physics",
  "process",
  "progress",
  "status",
  "thesis",
]);

const IRREGULAR_PAST_FORMS = new Set([
  "became",
  "began",
  "bought",
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
  "heard",
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

const IRREGULAR_PARTICIPLES = new Set([
  "been",
  "begun",
  "built",
  "done",
  "drawn",
  "found",
  "given",
  "gone",
  "had",
  "heard",
  "kept",
  "known",
  "made",
  "read",
  "said",
  "seen",
  "shown",
  "spoken",
  "taken",
  "thought",
  "told",
  "understood",
  "written",
]);

const BASE_VERBS_ENDING_ED = new Set(["bleed", "breed", "feed", "need", "seed", "speed"]);
const COMPARATIVE_EXCEPTIONS = new Set(["former", "inner", "other", "outer", "proper", "upper"]);
const SUPERLATIVE_EXCEPTIONS = new Set(["earnest", "honest", "modest"]);

function lexicalWords(value: string): string[] {
  return (value.match(/[A-Za-z]+(?:[-'][A-Za-z]+)*/g) ?? []).map((word) => normalizeWord(word));
}

function firstContentWord(value: string): string | null {
  const words = lexicalWords(value);
  if (!words.length) return null;
  let index = 0;
  while (index < words.length && /^(?:to|not|never)$/.test(words[index])) index += 1;
  return words[index] ?? null;
}

function nounHeadWord(value: string): string | null {
  const words = lexicalWords(value);
  if (!words.length) return null;
  return words[words.length - 1] ?? null;
}

export function detectNounNumber(value: string): NounNumber {
  const word = nounHeadWord(value);
  if (!word) return "unknown";
  if (IRREGULAR_PLURALS.has(word)) return "plural";
  if (INVARIANT_NOUNS.has(word)) return "unknown";
  if (SINGULAR_S_NOUNS.has(word)) return "singular";
  if (/ies$/.test(word) && word.length > 4) return "plural";
  if (/(?:ches|shes|xes|zes|ses)$/.test(word) && word.length > 4) return "plural";
  if (word.endsWith("s") && !/(?:ss|us|is|as)$/.test(word)) return "plural";
  return "singular";
}

export function detectVerbForm(value: string): VerbForm {
  const word = firstContentWord(value);
  if (!word) return "unknown";
  if (/^(?:is|has|does)$/.test(word)) return "third-person";
  if (/^(?:am|are|be|have|do)$/.test(word)) return "base";
  if (/^(?:was|were)$/.test(word)) return "past";
  if (IRREGULAR_PAST_FORMS.has(word) || IRREGULAR_PARTICIPLES.has(word)) return "past";
  if (word.endsWith("ing") && word.length > 4) return "gerund";
  if (word.endsWith("ed") && word.length > 3 && !BASE_VERBS_ENDING_ED.has(word)) return "past";
  if (word.endsWith("s") && !/(?:ss|us|is|as)$/.test(word)) return "third-person";
  return "base";
}

export function detectAdjectiveDegree(value: string): AdjectiveDegree {
  const words = lexicalWords(value);
  if (!words.length) return "unknown";
  if (/^(?:more|less)$/.test(words[0]) && words.length > 1) return "comparative";
  if (/^(?:most|least)$/.test(words[0]) && words.length > 1) return "superlative";

  const word = words[0];
  if (/^(?:better|worse|further|farther)$/.test(word)) return "comparative";
  if (/^(?:best|worst|furthest|farthest)$/.test(word)) return "superlative";
  if (word.endsWith("est") && word.length > 5 && !SUPERLATIVE_EXCEPTIONS.has(word)) return "superlative";
  if (word.endsWith("er") && word.length > 4 && !COMPARATIVE_EXCEPTIONS.has(word)) return "comparative";
  return "positive";
}

/**
 * Surface-form compatibility for deterministic lexical substitution.
 *
 * This deliberately returns a soft score rather than a binary verdict: English
 * morphology is ambiguous without a parser (for example "read" and invariant
 * plurals), so uncertain cases should be ranked lower rather than forbidden.
 */
export function morphologyCompatibility(
  original: string,
  replacement: string,
  partOfSpeech: PartOfSpeech,
): number {
  if (partOfSpeech === "noun") {
    const source = detectNounNumber(original);
    const candidate = detectNounNumber(replacement);
    if (source === "unknown" || candidate === "unknown") return 0.82;
    return source === candidate ? 1 : 0.38;
  }

  if (partOfSpeech === "verb") {
    const source = detectVerbForm(original);
    const candidate = detectVerbForm(replacement);
    if (source === "unknown" || candidate === "unknown") return 0.8;
    return source === candidate ? 1 : 0.34;
  }

  if (partOfSpeech === "adjective") {
    const source = detectAdjectiveDegree(original);
    const candidate = detectAdjectiveDegree(replacement);
    if (source === "unknown" || candidate === "unknown") return 0.84;
    return source === candidate ? 1 : 0.44;
  }

  return 0.86;
}
