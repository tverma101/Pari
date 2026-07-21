import { getSentenceForRange } from "@/lib/nlp/sentenceSplit";
import { matchCase, normalizeWord } from "@/lib/nlp/tokenizer";
import type { RewriteToken } from "@/lib/phraseEngine/types";
import type { CandidateOption } from "@/lib/ranking/types";
import type { PartOfSpeech, RewriteMode, StrengthLevel } from "@/lib/types";

import { generateMaskSuggestions, warmRewriteAssistantModels } from "./modelManager";
import {
  getRewriteAssistantDescriptor,
  getRewriteMaskModelIds,
} from "./modelRegistry";

interface EnhancementContext {
  token: RewriteToken;
  sentence: string;
  sentenceStart: number;
  mode: RewriteMode;
  strength: StrengthLevel;
}

const CONTENT_POS = new Set<PartOfSpeech>(["adjective", "adverb", "noun", "verb", "phrase"]);
const MASK_SUGGESTION_TOP_K = 40;

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
  mode: RewriteMode
): CandidateOption {
  return {
    id: `${source}:${normalizeWord(originalText)}:${normalizeWord(replacement).replace(/\s+/g, "-")}`,
    original: originalText,
    replacement,
    label: source === "generator" ? "ai rewrite" : "context",
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

async function collectMaskSuggestions(context: EnhancementContext): Promise<CandidateOption[]> {
  if (context.token.isPhrase) return [];

  const results: CandidateOption[] = [];
  for (const modelId of getRewriteMaskModelIds()) {
    try {
      const descriptor = getRewriteAssistantDescriptor(modelId);
      const masked = maskSentence(context, descriptor.maskToken ?? "[MASK]");
      const suggestions = await generateMaskSuggestions(modelId, masked, MASK_SUGGESTION_TOP_K);

      suggestions.forEach((suggestion) => {
        const replacement = normalizeCandidateText(context.token, cleanGeneratedPiece(suggestion.token));
        if (!isAcceptableReplacement(replacement, context.token.originalText, context.token)) return;
        results.push(toCandidateOption(replacement, "contextual-mlm", context.token.originalText, context.mode));
      });
    } catch {
      // Keep the remaining mask experts active even if one model fails in-browser.
    }
  }

  return results;
}

export async function generateAdvancedAlternatives(
  token: RewriteToken,
  fullText: string,
  mode: RewriteMode,
  strength: StrengthLevel
): Promise<CandidateOption[]> {
  const sentence = getSentenceForRange(fullText, token.originalStart, token.originalEnd);
  const context: EnhancementContext = {
    token,
    sentence: sentence.text,
    sentenceStart: sentence.start,
    mode,
    strength,
  };

  const maskSuggestions = await collectMaskSuggestions(context);
  return dedupeCandidates(maskSuggestions);
}
