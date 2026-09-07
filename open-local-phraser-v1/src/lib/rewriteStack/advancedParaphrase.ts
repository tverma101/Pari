import { getSentenceForRange } from "@/lib/nlp/sentenceSplit";
import { matchCase, normalizeWord } from "@/lib/nlp/tokenizer";
import {
  buildCandidateOptions,
  getSynonymEntry,
  inflectFallbackReplacement,
} from "@/lib/phraseEngine/synonymBank";
import type { RewriteToken } from "@/lib/phraseEngine/types";
import { rankCandidatesByEmbedding } from "@/lib/ranking/embeddingRanker";
import type { CandidateOption, RankingContext } from "@/lib/ranking/types";
import type { PartOfSpeech, RewriteMode, StrengthLevel } from "@/lib/types";

import {
  generateMaskSuggestions,
  type LocalModelFailure,
  warmRewriteAssistantModels,
} from "./modelManager";
import {
  getRewriteAssistantDescriptor,
  getRewriteMaskModelIds,
} from "./modelRegistry";
import wordNetLexicon from "./wordnetLexicon.json";

interface EnhancementContext {
  token: RewriteToken;
  sentence: string;
  sentenceStart: number;
  mode: RewriteMode;
  strength: StrengthLevel;
}

export interface AdvancedAlternativeOptions {
  onModelFailure?: (failure: LocalModelFailure) => void;
}

const CONTENT_POS = new Set<PartOfSpeech>(["adjective", "adverb", "noun", "verb", "phrase"]);
const MASK_SUGGESTION_TOP_K = 40;
const CONTEXTUAL_RANK_MODEL = "Xenova/paraphrase-MiniLM-L6-v2" as const;
const CONTEXTUAL_PRIORITY_COUNT = 12;
const SEMANTIC_DRIFT_MARGIN = 0.08;

type WordNetPartOfSpeech = "noun" | "verb" | "adjective" | "adverb";
type WordNetEntry = Partial<Record<WordNetPartOfSpeech, string[]>> & {
  thesaurus?: string[];
  related?: string[];
};
type WordNetLexicon = { entries: Record<string, WordNetEntry> };
const WORDNET_LEXICON = wordNetLexicon as WordNetLexicon;

function wordNetBaseTerms(term: string): string[] {
  const normalized = normalizeWord(term);
  const terms = [normalized];

  if (normalized.endsWith("ies") && normalized.length > 4) terms.push(`${normalized.slice(0, -3)}y`);
  if (normalized.endsWith("es") && normalized.length > 4) terms.push(normalized.slice(0, -2));
  if (normalized.endsWith("s") && normalized.length > 3) terms.push(normalized.slice(0, -1));
  if (normalized.endsWith("ves") && normalized.length > 4) {
    const stem = normalized.slice(0, -3);
    terms.push(`${stem}f`, `${stem}fe`, `${stem}ve`);
  }
  if (normalized.endsWith("ing") && normalized.length > 5) {
    const stem = normalized.slice(0, -3);
    terms.push(stem, `${stem}e`);
  }
  if (normalized.endsWith("ed") && normalized.length > 4) {
    const stem = normalized.slice(0, -2);
    terms.push(stem, `${stem}e`);
  }
  if (normalized.endsWith("er") && normalized.length > 4) {
    const stem = normalized.slice(0, -2);
    terms.push(stem, `${stem}e`);
  }
  if (normalized.endsWith("est") && normalized.length > 5) {
    const stem = normalized.slice(0, -3);
    terms.push(stem, `${stem}e`);
  }

  return [...new Set(terms.filter(Boolean))];
}

function wordNetPartOfSpeech(value: PartOfSpeech): WordNetPartOfSpeech | null {
  if (value === "noun" || value === "verb" || value === "adjective" || value === "adverb") return value;
  return null;
}

function inferUnknownWordNetPartOfSpeech(context: EnhancementContext): WordNetPartOfSpeech | null {
  const normalized = normalizeWord(context.token.originalText);
  if (normalized.endsWith("ing") || normalized.endsWith("ed")) return "verb";

  const localStart = Math.max(0, context.token.originalStart - context.sentenceStart);
  const localEnd = Math.max(localStart, context.token.originalEnd - context.sentenceStart);
  const before = context.sentence.slice(0, localStart);
  const after = context.sentence.slice(localEnd);

  if (/\b(?:a|an|the|this|that|these|those|my|your|our|their|some|many|several|each|every)\s+$/i.test(before)) {
    return "noun";
  }
  if (/^\s+(?:is|are|was|were|be|being|been)\b/i.test(after)) return "noun";
  return null;
}

function wordNetOptionsForContext(
  context: EnhancementContext,
  entry: WordNetEntry,
  baseTerm: string
): CandidateOption[] {
  const preferredPos = wordNetPartOfSpeech(context.token.partOfSpeech) ?? inferUnknownWordNetPartOfSpeech(context);
  const parts: WordNetPartOfSpeech[] = preferredPos
    ? [preferredPos]
    : ["noun", "adjective", "adverb"];

  return parts.flatMap((partOfSpeech) => (entry[partOfSpeech] ?? []).map((candidate) => {
    const replacement = inflectFallbackReplacement(
      context.token.originalText,
      baseTerm,
      candidate,
      partOfSpeech
    );
    return toCandidateOption(replacement, "wordnet", context.token.originalText, context.mode);
  }));
}

function replacementRisk(value: string, original: string): "low" | "medium" {
  const normalizedValue = normalizeWord(value);
  const normalizedOriginal = normalizeWord(original);
  if (normalizedValue.length > normalizedOriginal.length + 8) return "medium";
  if (/\b(always|never|guarantee|guarantees|prove|proves)\b/i.test(normalizedValue)) return "medium";
  return "low";
}

function toCandidateOption(
  replacement: string,
  source: CandidateOption["source"],
  originalText: string,
  mode: RewriteMode,
  label?: string
): CandidateOption {
  return {
    id: `${source}:${normalizeWord(originalText)}:${normalizeWord(replacement).replace(/\s+/g, "-")}`,
    original: originalText,
    replacement,
    label: label ?? (source === "generator" ? "ai rewrite" : source === "thesaurus" ? "thesaurus" : "context"),
    source,
    risk: replacementRisk(replacement, originalText),
    modePreference: [mode],
  };
}

function cleanGeneratedPiece(value: string): string {
  return value
    .replace(/^[\s"'`]+|[\s"'`]+$/g, "")
    .replace(/^\d+[\).\s-]+/, "")
    .replace(/^[-*•]+\s*/, "")
    .replace(/\s+/g, " ")
    .trim();
}

function isAcceptableReplacement(
  replacement: string,
  originalText: string,
  token: RewriteToken
): boolean {
  if (!replacement) return false;
  if (normalizeWord(replacement) === normalizeWord(originalText)) return false;
  if (replacement.includes("[MASK]") || replacement.includes("<mask>")) return false;
  if (/^[^A-Za-z]+$/.test(replacement)) return false;
  if (!token.isPhrase && replacement.split(/\s+/).length > 3) return false;
  if (token.isPhrase && replacement.split(/\s+/).length > 8) return false;
  if (replacement.length > Math.max(originalText.length * 2.5, 36)) return false;
  const replacementWords = replacement.toLowerCase().split(/\s+/);
  if (replacementWords.some((word, index) => index > 0 && word === replacementWords[index - 1])) return false;
  if (/\b(?:a|an|the)\s+(?:a|an|the)\b/i.test(replacement)) return false;
  return true;
}

function normalizeCandidateText(token: RewriteToken, replacement: string): string {
  return token.isPhrase ? replacement : matchCase(token.originalText, replacement.toLowerCase());
}

function dedupeCandidates(options: CandidateOption[]): CandidateOption[] {
  const seen = new Set<string>();
  return options.filter((option) => {
    const key = normalizeWord(option.replacement);
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function maskSentence(context: EnhancementContext, maskToken: string): string {
  const localStart = Math.max(0, context.token.originalStart - context.sentenceStart);
  const localEnd = Math.max(localStart, context.token.originalEnd - context.sentenceStart);
  return context.sentence.slice(0, localStart) + maskToken + context.sentence.slice(localEnd);
}

/**
 * ConCat-style lexical substitution input: retain the untouched sentence as a
 * meaning anchor, then ask the masked LM to fill the target in a second copy.
 * This is intentionally local and keeps exactly one mask token in the input.
 */
function contextualMaskInput(
  context: EnhancementContext,
  modelId: string,
  maskToken: string
): string {
  const masked = maskSentence(context, maskToken);
  const separator = modelId.includes("roberta") ? "</s></s>" : "[SEP]";
  return `${context.sentence} ${separator} ${masked}`;
}

function rankingContext(context: EnhancementContext): RankingContext {
  return {
    fullText: context.sentence,
    sentence: context.sentence,
    selectedText: context.token.originalText,
    mode: context.mode,
    strength: context.strength,
    freezeWords: [],
    partOfSpeech: context.token.partOfSpeech,
    selectionStart: context.token.originalStart,
    selectionEnd: context.token.originalEnd,
    sentenceStart: context.sentenceStart,
  };
}

async function semanticallyPrioritizeCandidates(
  candidates: CandidateOption[],
  context: EnhancementContext
): Promise<CandidateOption[]> {
  if (candidates.length === 0) return [];

  try {
    const ranked = await rankCandidatesByEmbedding(
      candidates,
      rankingContext(context),
      CONTEXTUAL_RANK_MODEL
    );
    const bestSemanticScore = ranked.reduce(
      (best, result) => Math.max(best, result.semanticScore ?? 0),
      0
    );

    return ranked.map((result, index) => {
      const semanticScore = result.semanticScore ?? bestSemanticScore;
      const semanticDrift = bestSemanticScore > 0 && bestSemanticScore - semanticScore > SEMANTIC_DRIFT_MARGIN;
      const shouldPromoteContextual =
        result.option.source === "contextual-mlm" &&
        index < CONTEXTUAL_PRIORITY_COUNT &&
        !semanticDrift;

      return {
        ...result.option,
        label: shouldPromoteContextual ? "natural context" : result.option.label,
        risk: semanticDrift && (result.option.risk ?? "low") === "low"
          ? "medium"
          : result.option.risk,
      };
    });
  } catch {
    // Contextual suggestions are an editing convenience, so semantic ranking is
    // deliberately fail-open to the existing deterministic/rule-ranked list.
    return candidates;
  }
}

export async function warmAdvancedParaphraseStack(): Promise<void> {
  await warmRewriteAssistantModels(getRewriteMaskModelIds());
}

export async function warmContextualSuggestionStack(): Promise<void> {
  await warmRewriteAssistantModels(getRewriteMaskModelIds());
}

export async function prepareInputForParaphrase(
  text: string
): Promise<{ preparedText: string; changed: boolean }> {
  return {
    preparedText: text,
    changed: false,
  };
}

export function selectTokensForEnhancement(tokens: RewriteToken[], limit = 10): RewriteToken[] {
  return [...tokens]
    .filter((token) => {
      if (!token.isWord || token.frozen) return false;
      if (!CONTENT_POS.has(token.partOfSpeech)) return false;
      if (normalizeWord(token.originalText).length < 4 && !token.isPhrase) return false;
      return true;
    })
    .sort((left: RewriteToken, right: RewriteToken) => {
      const leftScore =
        (left.isPhrase ? 5 : 0) +
        (left.alternatives.length > 0 ? 3 : 0) +
        Math.min(left.originalText.length, 12) / 12;
      const rightScore =
        (right.isPhrase ? 5 : 0) +
        (right.alternatives.length > 0 ? 3 : 0) +
        Math.min(right.originalText.length, 12) / 12;
      return rightScore - leftScore;
    })
    .slice(0, limit);
}

async function collectMaskSuggestions(
  context: EnhancementContext,
  options: AdvancedAlternativeOptions = {}
): Promise<CandidateOption[]> {
  if (context.token.isPhrase) return [];

  const results: CandidateOption[] = [];
  for (const modelId of getRewriteMaskModelIds()) {
    const descriptor = getRewriteAssistantDescriptor(modelId);
    try {
      const maskedInput = contextualMaskInput(
        context,
        modelId,
        descriptor.maskToken ?? "[MASK]"
      );
      const suggestions = await generateMaskSuggestions(modelId, maskedInput, MASK_SUGGESTION_TOP_K);

      suggestions.forEach((suggestion) => {
        const replacement = normalizeCandidateText(context.token, cleanGeneratedPiece(suggestion.token));
        if (!isAcceptableReplacement(replacement, context.token.originalText, context.token)) return;
        results.push(toCandidateOption(replacement, "contextual-mlm", context.token.originalText, context.mode));
      });
    } catch (error) {
      options.onModelFailure?.({
        modelId,
        label: descriptor.label,
        message: error instanceof Error ? error.message : String(error),
        kind: error instanceof Error && /bundled .* files are incomplete/i.test(error.message)
          ? "missing-assets"
          : "load-failed",
      });
      // Keep the deterministic local suggestions active even if one model fails
      // in the browser. The caller can now explain that fallback to the user.
    }
  }

  return results;
}

function collectLexicalSuggestions(context: EnhancementContext): CandidateOption[] {
  const entry = getSynonymEntry(context.token.originalText);
  if (!entry) return [];

  return buildCandidateOptions(context.token.originalText, entry);
}

async function collectWordNetSuggestions(context: EnhancementContext): Promise<CandidateOption[]> {
  if (context.token.isPhrase) return [];

  const suggestions: CandidateOption[] = [];
  for (const baseTerm of wordNetBaseTerms(context.token.originalText)) {
    const entry = WORDNET_LEXICON.entries[baseTerm];
    if (!entry) continue;

    const options = wordNetOptionsForContext(context, entry, baseTerm)
      .filter((option) => isAcceptableReplacement(option.replacement, context.token.originalText, context.token));
    suggestions.push(...options);
  }

  return suggestions;
}

function collectThesaurusSuggestions(context: EnhancementContext): CandidateOption[] {
  if (context.token.isPhrase) return [];

  const suggestions: CandidateOption[] = [];
  const inferredPartOfSpeech = wordNetPartOfSpeech(context.token.partOfSpeech)
    ?? inferUnknownWordNetPartOfSpeech(context)
    ?? "noun";

  for (const baseTerm of wordNetBaseTerms(context.token.originalText)) {
    const entry = WORDNET_LEXICON.entries[baseTerm];
    const candidates = [
      ...(entry?.thesaurus ?? []).map((candidate) => ({ candidate, label: "thesaurus" })),
      ...(entry?.related ?? []).map((candidate) => ({ candidate, label: "related" })),
    ];
    for (const { candidate, label } of candidates) {
      const replacement = normalizeCandidateText(
        context.token,
        inflectFallbackReplacement(
          context.token.originalText,
          baseTerm,
          cleanGeneratedPiece(candidate),
          inferredPartOfSpeech
        )
      );
      if (!isAcceptableReplacement(replacement, context.token.originalText, context.token)) continue;
      suggestions.push(toCandidateOption(replacement, "thesaurus", context.token.originalText, context.mode, label));
    }
  }

  if (suggestions.length < 40) {
    suggestions.push(...collectCompoundSuggestions(context));
  }

  return suggestions;
}

function collectCompoundSuggestions(context: EnhancementContext): CandidateOption[] {
  const normalized = normalizeWord(context.token.originalText);
  if (normalized.length < 8 || context.token.isPhrase) return [];

  const suggestions: CandidateOption[] = [];
  for (let splitAt = 3; splitAt <= normalized.length - 3; splitAt += 1) {
    const left = normalized.slice(0, splitAt);
    const right = normalized.slice(splitAt);
    const leftEntry = WORDNET_LEXICON.entries[left];
    const rightEntry = WORDNET_LEXICON.entries[right];
    if (!leftEntry || !rightEntry) continue;

    const leftOptions = [
      left,
      ...(leftEntry.thesaurus ?? []).slice(0, 48),
      ...(leftEntry.noun ?? []).slice(0, 16),
    ];
    const rightOptions = [
      right,
      ...(rightEntry.thesaurus ?? []).slice(0, 48),
      ...(rightEntry.noun ?? []).slice(0, 16),
    ];

    for (const replacement of [
      ...leftOptions.slice(1).map((option) => `${option} ${right}`),
      ...rightOptions.slice(1).map((option) => `${left} ${option}`),
    ]) {
      const normalizedReplacement = normalizeCandidateText(context.token, cleanGeneratedPiece(replacement));
      if (!isAcceptableReplacement(normalizedReplacement, context.token.originalText, context.token)) continue;
      suggestions.push(toCandidateOption(normalizedReplacement, "thesaurus", context.token.originalText, context.mode, "related"));
    }

    if (suggestions.length >= 64) break;
  }

  return suggestions;
}

export async function generateAdvancedAlternatives(
  token: RewriteToken,
  fullText: string,
  mode: RewriteMode,
  strength: StrengthLevel,
  options: AdvancedAlternativeOptions = {}
): Promise<CandidateOption[]> {
  const sentence = getSentenceForRange(fullText, token.originalStart, token.originalEnd);
  const context: EnhancementContext = {
    token,
    sentence: sentence.text,
    sentenceStart: sentence.start,
    mode,
    strength,
  };

  // The mask experts improve ranking when their ONNX assets are available,
  // but the inline tool must remain useful without them. Start with the
  // deterministic local bank, then add any model-generated candidates.
  const lexicalSuggestions = collectLexicalSuggestions(context);
  const [wordNetSuggestions, thesaurusSuggestions, maskSuggestions] = await Promise.all([
    collectWordNetSuggestions(context),
    Promise.resolve(collectThesaurusSuggestions(context)),
    collectMaskSuggestions(context, options),
  ]);
  const candidates = dedupeCandidates([
    ...lexicalSuggestions,
    ...wordNetSuggestions,
    ...thesaurusSuggestions,
    ...maskSuggestions,
  ]);

  return semanticallyPrioritizeCandidates(candidates, context);
}