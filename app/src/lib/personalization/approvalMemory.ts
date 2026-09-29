import type { CandidateOption, RankingResult } from "@/lib/ranking/types";
import { normalizeWord, tokenize } from "@/lib/nlp/tokenizer";

export type EditEventType =
  | "synonym-replacement"
  | "typed-replacement"
  | "insertion"
  | "deletion"
  | "pasted-revision"
  | "word-revert"
  | "sentence-rephrase"
  | "sentence-revert"
  | "paragraph-revert";

export type EditEventSource = "typed" | "synonym" | "paste" | "revert" | "sentence_rephrase";

export interface EditEvent {
  id: string;
  approvedExampleId?: string;
  sequence: number;
  type: EditEventType;
  originalFragment: string;
  replacementFragment: string;
  sentenceIndex?: number;
  tokenIndex?: number;
  source: EditEventSource;
  relativeTimestamp: number;
}

export interface ApprovedExample {
  id: string;
  createdAt: string;
  originalText: string;
  finalText: string;
  originalHash: string;
  finalHash: string;
  protectedSpansSnapshot: Array<{
    id: string;
    kind: string;
    text: string;
    start: number;
    end: number;
  }>;
  groupedEditSummary: EditEvent[];
  appVersion: string;
  schemaVersion: number;
}

export interface PreferenceCounter {
  [replacement: string]: number;
}

export interface PreferenceMemory {
  schemaVersion: number;
  approvedReplacements: Record<string, PreferenceCounter>;
  revertedReplacements: Record<string, PreferenceCounter>;
  phrasePreferences: PreferenceCounter;
  avoidedPhrases: PreferenceCounter;
  punctuation: PreferenceCounter;
  contractions: PreferenceCounter;
  sentenceLength: { total: number; count: number };
  paragraphLength: { total: number; count: number };
  sentenceStructure: PreferenceCounter;
  lastUpdatedAt: string | null;
}

export function createEmptyPreferenceMemory(): PreferenceMemory {
  return {
    schemaVersion: 1,
    approvedReplacements: {},
    revertedReplacements: {},
    phrasePreferences: {},
    avoidedPhrases: {},
    punctuation: {},
    contractions: {},
    sentenceLength: { total: 0, count: 0 },
    paragraphLength: { total: 0, count: 0 },
    sentenceStructure: {},
    lastUpdatedAt: null,
  };
}

function increment(bucket: PreferenceCounter, key: string, amount = 1): void {
  const normalized = key.trim().toLowerCase();
  if (!normalized) return;
  bucket[normalized] = (bucket[normalized] ?? 0) + amount;
}

function normalizeMemoryPhrase(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, " ");
}

function cloneMemory(memory: PreferenceMemory): PreferenceMemory {
  return {
    ...memory,
    approvedReplacements: Object.fromEntries(
      Object.entries(memory.approvedReplacements).map(([key, value]) => [key, { ...value }])
    ),
    revertedReplacements: Object.fromEntries(
      Object.entries(memory.revertedReplacements).map(([key, value]) => [key, { ...value }])
    ),
    phrasePreferences: { ...memory.phrasePreferences },
    avoidedPhrases: { ...memory.avoidedPhrases },
    punctuation: { ...memory.punctuation },
    contractions: { ...memory.contractions },
    sentenceStructure: { ...memory.sentenceStructure },
    sentenceLength: { ...memory.sentenceLength },
    paragraphLength: { ...memory.paragraphLength },
  };
}

function countWords(text: string): number {
  return tokenize(text).filter((token) => token.type === "word").length;
}

function countSentences(text: string): number {
  return Math.max(1, text.split(/[.!?]+(?:\s|$)/).filter((part) => part.trim()).length);
}

function collectPunctuation(text: string): PreferenceCounter {
  const punctuation: PreferenceCounter = {};
  for (const mark of text.match(/[,:;!?]/g) ?? []) increment(punctuation, mark);
  return punctuation;
}

function collectContractions(text: string): PreferenceCounter {
  const contractions: PreferenceCounter = {};
  for (const contraction of text.match(/\b[A-Za-z]+['’][A-Za-z]+\b/g) ?? []) {
    increment(contractions, contraction);
  }
  return contractions;
}

export function learnFromApproval(
  current: PreferenceMemory,
  example: Pick<ApprovedExample, "originalText" | "finalText" | "groupedEditSummary">
): PreferenceMemory {
  const next = cloneMemory(current);
  const now = new Date().toISOString();
  const originalWords = countWords(example.originalText);
  const finalWords = countWords(example.finalText);

  next.lastUpdatedAt = now;
  next.sentenceLength.total += finalWords / countSentences(example.finalText);
  next.sentenceLength.count += 1;
  next.paragraphLength.total += finalWords;
  next.paragraphLength.count += 1;

  for (const [punctuation, amount] of Object.entries(collectPunctuation(example.finalText))) {
    increment(next.punctuation, punctuation, amount);
  }
  for (const [contraction, amount] of Object.entries(collectContractions(example.finalText))) {
    increment(next.contractions, contraction, amount);
  }

  const structure = `${countSentences(example.originalText)}:${countSentences(example.finalText)}`;
  increment(next.sentenceStructure, structure);
  increment(next.sentenceStructure, finalWords < originalWords ? "shorter" : finalWords > originalWords ? "longer" : "similar");

  for (const event of example.groupedEditSummary) {
    const original = normalizeMemoryPhrase(event.originalFragment);
    const replacement = normalizeMemoryPhrase(event.replacementFragment);
    if (!original && !replacement) continue;

    if (
      event.type === "synonym-replacement" ||
      event.type === "typed-replacement" ||
      event.type === "pasted-revision"
    ) {
      const bucket = next.approvedReplacements[original] ?? {};
      increment(bucket, replacement);
      next.approvedReplacements[original] = bucket;
      if (replacement) increment(next.phrasePreferences, replacement);
    }

    if (event.type === "sentence-revert" || event.type === "paragraph-revert") {
      const bucket = next.revertedReplacements[original] ?? {};
      increment(bucket, replacement || original);
      next.revertedReplacements[original] = bucket;
      if (original) increment(next.avoidedPhrases, original);
    }
  }

  return next;
}

export function rankCandidatesByMemory(
  results: RankingResult[],
  originalText: string,
  memory: PreferenceMemory
): RankingResult[] {
  const preferred = memory.approvedReplacements[normalizeWord(originalText)] ?? {};
  const avoided = memory.revertedReplacements[normalizeWord(originalText)] ?? {};

  return [...results].sort((left, right) => {
    const leftPreference = preferred[normalizeWord(left.option.replacement)] ?? 0;
    const rightPreference = preferred[normalizeWord(right.option.replacement)] ?? 0;
    const leftAvoidance = avoided[normalizeWord(left.option.replacement)] ?? 0;
    const rightAvoidance = avoided[normalizeWord(right.option.replacement)] ?? 0;
    const preferenceDelta = rightPreference - leftPreference;
    if (preferenceDelta !== 0) return preferenceDelta;
    const avoidanceDelta = leftAvoidance - rightAvoidance;
    if (avoidanceDelta !== 0) return avoidanceDelta;
    return right.score - left.score;
  });
}

function contentWords(text: string): Set<string> {
  return new Set(
    tokenize(text)
      .filter((token) => token.type === "word")
      .map((token) => normalizeWord(token.text))
      .filter((word) => word.length > 2)
  );
}

function similarity(left: Set<string>, right: Set<string>): number {
  if (left.size === 0 || right.size === 0) return 0;
  let overlap = 0;
  for (const word of left) if (right.has(word)) overlap += 1;
  return overlap / Math.max(1, Math.min(left.size, right.size));
}

export function retrieveRelevantExamples(
  input: string,
  examples: ApprovedExample[],
  limit = 5
): ApprovedExample[] {
  const inputWords = contentWords(input);
  return examples
    .map((example) => ({ example, score: similarity(inputWords, contentWords(example.originalText)) }))
    .filter((entry) => entry.score >= 0.18)
    .sort((left, right) => right.score - left.score || right.example.createdAt.localeCompare(left.example.createdAt))
    .slice(0, limit)
    .map((entry) => entry.example);
}

export function preferredCandidate(
  options: CandidateOption[],
  originalText: string,
  memory: PreferenceMemory
): CandidateOption | null {
  const ranked = rankCandidatesByMemory(
    options.map((option, index) => ({
      option,
      score: options.length - index,
      risk: option.risk ?? "low",
      warnings: [],
    })),
    originalText,
    memory
  );
  return ranked[0]?.option ?? null;
}
