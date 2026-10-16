import { countWords } from "../nlp/tokenizer.ts";
import type { CandidateOption } from "../ranking/types.ts";
import type { PartOfSpeech } from "../types.ts";

export const WORD_LAB_SAFE_SOURCES = new Set<CandidateOption["source"]>([
  "phrase-bank",
  "static-bank",
  "deep-bank",
  "contextual-mlm",
]);

const SHORTER_PHRASES: ReadonlyArray<readonly [string, string]> = [
  ["in spite of the fact that", "although"],
  ["due to the fact that", "because"],
  ["for the purpose of", "to"],
  ["at this point in time", "now"],
  ["at the present time", "now"],
  ["in the event that", "if"],
  ["a large number of", "many"],
  ["has the ability to", "can"],
  ["is able to", "can"],
  ["with regard to", "about"],
  ["in close proximity to", "near"],
  ["the reason is that", "because"],
  ["in order to", "to"],
  ["refused to change his mind", "was obstinate"],
];

const THAT_CLAUSE_VERB_FORMS = new Set([
  "argue", "argues", "argued", "assert", "asserts", "asserted", "believe", "believes", "believed",
  "claim", "claims", "claimed", "conclude", "concludes", "concluded", "confirm", "confirms", "confirmed",
  "demonstrate", "demonstrates", "demonstrated", "discover", "discovers", "discovered", "establish", "establishes", "established",
  "explain", "explains", "explained", "find", "finds", "found", "illustrate", "illustrates", "illustrated",
  "imply", "implies", "implied", "indicate", "indicates", "indicated", "mean", "means", "meant",
  "note", "notes", "noted", "observe", "observes", "observed", "prove", "proves", "proved", "proven",
  "report", "reports", "reported", "reveal", "reveals", "revealed", "say", "says", "said", "show", "shows", "showed", "shown",
  "state", "states", "stated", "suggest", "suggests", "suggested",
]);

/** Screen out verb choices that cannot introduce a following that-clause. */
export function wordLabWordFitsContext(
  fullText: string,
  tokenEnd: number,
  partOfSpeech: PartOfSpeech,
  replacement: string,
): boolean {
  if (partOfSpeech !== "verb" || !/^\s+that\b/i.test(fullText.slice(tokenEnd))) return true;
  return THAT_CLAUSE_VERB_FORMS.has(replacement.trim().toLocaleLowerCase());
}

function replaceFirstPhrase(text: string, phrase: string, replacement: string): string | null {
  const start = text.toLocaleLowerCase().indexOf(phrase.toLocaleLowerCase());
  if (start < 0) return null;
  const end = start + phrase.length;
  const matched = text.slice(start, end);
  const adjusted = /^[A-Z]/.test(matched)
    ? replacement.charAt(0).toLocaleUpperCase() + replacement.slice(1)
    : replacement;
  return `${text.slice(0, start)}${adjusted}${text.slice(end)}`;
}

function uniqueShorterVariants(text: string, variants: Array<{ phrase: string; replacement: string }>): string[] {
  const sourceWordCount = countWords(text);
  const seen = new Set<string>();
  const output: string[] = [];

  for (const variant of variants) {
    const candidate = replaceFirstPhrase(text, variant.phrase, variant.replacement);
    if (!candidate || countWords(candidate) >= sourceWordCount) continue;
    const key = candidate.toLocaleLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(candidate);
    if (output.length >= 5) break;
  }

  return output;
}

/** Return only shorter, phrase-level options; no words are silently deleted. */
export function buildCondenseOptions(text: string, phraseCandidates: CandidateOption[] = []): string[] {
  const generated = phraseCandidates
    .filter((option) => WORD_LAB_SAFE_SOURCES.has(option.source))
    .filter((option) => countWords(option.replacement) < countWords(option.original))
    .map((option) => ({ phrase: option.original, replacement: option.replacement }));
  const curated = SHORTER_PHRASES.map(([phrase, replacement]) => ({ phrase, replacement }));
  return uniqueShorterVariants(text, [...generated, ...curated]);
}

/** Return one-word substitutions for a phrase that already appears in the selection. */
export function buildPhraseToOneWordOptions(text: string, phraseCandidates: CandidateOption[] = []): string[] {
  const generated = phraseCandidates
    .filter((option) => WORD_LAB_SAFE_SOURCES.has(option.source))
    .filter((option) => countWords(option.original) > 1 && countWords(option.replacement) === 1)
    .map((option) => ({ phrase: option.original, replacement: option.replacement }));
  const curated = SHORTER_PHRASES
    .filter(([, replacement]) => countWords(replacement) === 1)
    .map(([phrase, replacement]) => ({ phrase, replacement }));
  const seen = new Set<string>();
  const output: string[] = [];

  for (const variant of [...generated, ...curated]) {
    const candidate = replaceFirstPhrase(text, variant.phrase, variant.replacement);
    if (!candidate || candidate === text) continue;
    const key = candidate.toLocaleLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(candidate);
    if (output.length >= 5) break;
  }

  return output;
}
