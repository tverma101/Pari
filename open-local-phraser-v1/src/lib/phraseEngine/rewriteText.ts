import { guessPartOfSpeech } from "@/lib/nlp/posTagger";
import { countSentences, getSentenceForRange } from "@/lib/nlp/sentenceSplit";
import { countWords, normalizeWord, tokenize } from "@/lib/nlp/tokenizer";
import { rankCandidatesByRule, pickAutomaticCandidate } from "@/lib/ranking/ruleBasedRanker";

import { assignTokenRanges, summarizeTokens } from "./diff";
import { collectFrozenWordTokenIndices, parseFreezeEntries } from "./freezeWords";
import { rewriteChance, seededFloat, strengthLabel } from "./rules";
import { buildCandidateOptions, getSynonymEntry, PHRASE_KEYS } from "./synonymBank";
import type { ManualChoiceMap, RewriteResult, RewriteSettingsInput, RewriteToken } from "./types";
import type { CandidateOption } from "@/lib/ranking/types";

interface WordPosition {
  tokenIndex: number;
  normalized: string;
}

const MANUAL_ONLY_SINGLE_WORDS = new Set([
  "and",
  "may",
  "person",
  "sentence",
  "themselves",
  "tool",
  "when",
  "yourself",
  "oneself",
]);

function buildWordPositions(text: string): WordPosition[] {
  return tokenize(text)
    .map((token, tokenIndex) => {
      if (token.type !== "word") return null;
      return {
        tokenIndex,
        normalized: normalizeWord(token.text),
      };
    })
    .filter((entry): entry is WordPosition => entry !== null);
}

function hasWhitespaceSeparators(rawText: string): boolean {
  return /^\s+$/.test(rawText);
}

function mergeAlternatives(
  baseAlternatives: CandidateOption[],
  extraAlternatives: CandidateOption[],
  originalText: string
): CandidateOption[] {
  if (extraAlternatives.length === 0) return baseAlternatives;

  const seen = new Set(baseAlternatives.map((option) => normalizeWord(option.replacement)));
  const merged = [...baseAlternatives];

  for (const option of extraAlternatives) {
    const key = normalizeWord(option.replacement);
    if (!key || key === normalizeWord(originalText) || seen.has(key)) {
      continue;
    }

    seen.add(key);
    merged.push(option);
  }

  return merged;
}

function wordAfter(text: string, end: number): string | null {
  const match = text.slice(end).match(/^\s*([A-Za-z]+(?:[-'][A-Za-z]+)?)/);
  return match ? normalizeWord(match[1]) : null;
}

function canAutoRewriteSingleWord(originalText: string, fullText: string, selectionEnd: number): boolean {
  const normalized = normalizeWord(originalText);
  if (MANUAL_ONLY_SINGLE_WORDS.has(normalized)) return false;
  if (normalized === "better" && wordAfter(fullText, selectionEnd) === "than") return false;
  return true;
}

function findPhraseMatches(
  text: string,
  frozenTokenIndices: Set<number>
): Map<number, { key: string; length: number }> {
  const rawTokens = tokenize(text);
  const wordPositions = buildWordPositions(text);
  const matches = new Map<number, { key: string; length: number }>();

  for (let index = 0; index < wordPositions.length; index += 1) {
    for (const key of PHRASE_KEYS) {
      const words = key.split(/\s+/);
      if (index + words.length > wordPositions.length) continue;

      let valid = true;
      for (let offset = 0; offset < words.length; offset += 1) {
        const wordPosition = wordPositions[index + offset];
        if (wordPosition.normalized !== words[offset]) {
          valid = false;
          break;
        }

        if (frozenTokenIndices.has(wordPosition.tokenIndex)) {
          valid = false;
          break;
        }

        if (offset > 0) {
          const previousTokenIndex = wordPositions[index + offset - 1].tokenIndex;
          const between = rawTokens
            .slice(previousTokenIndex + 1, wordPosition.tokenIndex)
            .map((token) => token.text)
            .join("");

          if (!hasWhitespaceSeparators(between)) {
            valid = false;
            break;
          }
        }
      }

      if (!valid) continue;

      matches.set(index, { key, length: words.length });
      index += words.length - 1;
      break;
    }
  }

  return matches;
}

export function rewriteText(
  text: string,
  settings: RewriteSettingsInput,
  manualChoices: ManualChoiceMap = {},
  extraAlternatives: Record<string, CandidateOption[]> = {}
): RewriteResult {
  const rawTokens = tokenize(text);
  const wordPositions = rawTokens
    .map((token, tokenIndex) => {
      if (token.type !== "word") return null;
      return {
        tokenIndex,
        normalized: normalizeWord(token.text),
      };
    })
    .filter((entry): entry is WordPosition => entry !== null);

  const frozenTokenIndices = collectFrozenWordTokenIndices(rawTokens, settings.freezeWords);
  const phraseMatches = findPhraseMatches(text, frozenTokenIndices);
  const tokens: RewriteToken[] = [];
  const seedBase = `${settings.mode}|${settings.strength}|${settings.freezeWords}|${text}`;

  let rawIndex = 0;
  let wordIndex = 0;

  while (rawIndex < rawTokens.length) {
    const rawToken = rawTokens[rawIndex];

    if (rawToken.type === "gap") {
      tokens.push({
        id: `gap-${rawIndex}`,
        text: rawToken.text,
        originalText: rawToken.text,
        isWord: false,
        isPhrase: false,
        alternatives: [],
        selectedAlternativeId: null,
        changed: false,
        frozen: false,
        start: 0,
        end: 0,
        partOfSpeech: "unknown",
        source: "text",
        risk: "low",
        warnings: [],
        originalStart: rawToken.start,
        originalEnd: rawToken.end,
      });
      rawIndex += 1;
      continue;
    }

    const wordPositionIndex = wordPositions.findIndex((entry) => entry.tokenIndex === rawIndex);
    const phraseMatch = phraseMatches.get(wordPositionIndex);

    if (phraseMatch) {
      const lastWordPosition = wordPositions[wordPositionIndex + phraseMatch.length - 1];
      const endRawIndex = lastWordPosition.tokenIndex;
      const originalText = rawTokens.slice(rawIndex, endRawIndex + 1).map((token) => token.text).join("");
      const entry = getSynonymEntry(phraseMatch.key);
      const tokenId = `segment-${wordIndex}`;
      const alternatives = mergeAlternatives(
        entry ? buildCandidateOptions(originalText, entry) : [],
        extraAlternatives[tokenId] ?? [],
        originalText
      );
      const hasManualSelection = Object.prototype.hasOwnProperty.call(manualChoices, tokenId);
      const manualSelection = hasManualSelection ? manualChoices[tokenId] : undefined;
      const frozen = false;

      const selectedAlternativeId =
        manualSelection && alternatives.some((option) => option.id === manualSelection)
          ? manualSelection
          : null;
      const sentence = getSentenceForRange(text, rawTokens[rawIndex].start, rawTokens[endRawIndex].end);

      const ranked = rankCandidatesByRule(alternatives, {
        fullText: text,
        sentence: sentence.text,
        selectedText: originalText,
        mode: settings.mode,
        strength: settings.strength <= 24 ? 1 : settings.strength <= 49 ? 2 : settings.strength <= 74 ? 3 : 4,
        freezeWords: parseFreezeEntries(settings.freezeWords),
        partOfSpeech: entry?.pos ?? "phrase",
        selectionStart: rawTokens[rawIndex].start,
        selectionEnd: rawTokens[endRawIndex].end,
        sentenceStart: sentence.start,
      });

      const autoPick =
        !hasManualSelection &&
        !settings.disableAutomaticRewrites &&
        selectedAlternativeId === null &&
        alternatives.length > 0 &&
        seededFloat(`${seedBase}|${tokenId}|${originalText}`) <
          rewriteChance(settings.mode, settings.strength, originalText)
          ? pickAutomaticCandidate(ranked, settings.mode, `${seedBase}|${tokenId}`)
          : null;

      const resolvedOption =
        alternatives.find((option) => option.id === selectedAlternativeId) ?? autoPick ?? null;

      tokens.push({
        id: tokenId,
        text: resolvedOption?.replacement ?? originalText,
        originalText,
        isWord: true,
        isPhrase: true,
        alternatives,
        selectedAlternativeId: resolvedOption?.id ?? null,
        changed: Boolean(resolvedOption),
        frozen,
        start: 0,
        end: 0,
        partOfSpeech: entry?.pos ?? "phrase",
        source: resolvedOption?.source ?? entry?.source ?? "phrase-bank",
        label: resolvedOption?.label,
        risk: resolvedOption?.risk ?? "low",
        warnings: ranked.find((candidate) => candidate.option.id === resolvedOption?.id)?.warnings ?? [],
        originalStart: rawTokens[rawIndex].start,
        originalEnd: rawTokens[endRawIndex].end,
      });

      rawIndex = endRawIndex + 1;
      wordIndex += 1;
      continue;
    }

    const originalText = rawToken.text;
    const tokenId = `segment-${wordIndex}`;
    const frozen = frozenTokenIndices.has(rawIndex);
    const entry = frozen ? undefined : getSynonymEntry(originalText);
    const alternatives = mergeAlternatives(
      frozen || !entry ? [] : buildCandidateOptions(originalText, entry),
      extraAlternatives[tokenId] ?? [],
      originalText
    );
    const hasManualSelection = Object.prototype.hasOwnProperty.call(manualChoices, tokenId);
    const manualSelection = hasManualSelection ? manualChoices[tokenId] : undefined;

    const selectedAlternativeId =
      manualSelection && alternatives.some((option) => option.id === manualSelection)
        ? manualSelection
        : null;
    const sentence = getSentenceForRange(text, rawToken.start, rawToken.end);

    const ranked = rankCandidatesByRule(alternatives, {
      fullText: text,
      sentence: sentence.text,
      selectedText: originalText,
      mode: settings.mode,
      strength: settings.strength <= 24 ? 1 : settings.strength <= 49 ? 2 : settings.strength <= 74 ? 3 : 4,
      freezeWords: parseFreezeEntries(settings.freezeWords),
      partOfSpeech: entry?.pos ?? guessPartOfSpeech(originalText),
      selectionStart: rawToken.start,
      selectionEnd: rawToken.end,
      sentenceStart: sentence.start,
    });

    const autoPick =
      !frozen &&
      !hasManualSelection &&
      !settings.disableAutomaticRewrites &&
      canAutoRewriteSingleWord(originalText, text, rawToken.end) &&
      selectedAlternativeId === null &&
      alternatives.length > 0 &&
      seededFloat(`${seedBase}|${tokenId}|${originalText}`) <
        rewriteChance(settings.mode, settings.strength, originalText)
        ? pickAutomaticCandidate(ranked, settings.mode, `${seedBase}|${tokenId}`)
        : null;

    const resolvedOption =
      alternatives.find((option) => option.id === selectedAlternativeId) ?? autoPick ?? null;

    tokens.push({
      id: tokenId,
      text: resolvedOption?.replacement ?? originalText,
      originalText,
      isWord: true,
      isPhrase: false,
      alternatives,
      selectedAlternativeId: resolvedOption?.id ?? null,
      changed: Boolean(resolvedOption),
      frozen,
      start: 0,
      end: 0,
      partOfSpeech: entry?.pos ?? guessPartOfSpeech(originalText),
      source: resolvedOption?.source ?? entry?.source ?? "text",
      label: resolvedOption?.label,
      risk: resolvedOption?.risk ?? "low",
      warnings: frozen
        ? ["Frozen term"]
        : ranked.find((candidate) => candidate.option.id === resolvedOption?.id)?.warnings ?? [],
      originalStart: rawToken.start,
      originalEnd: rawToken.end,
    });

    rawIndex += 1;
    wordIndex += 1;
  }

  const rangedTokens = assignTokenRanges(tokens);
  const summary = summarizeTokens(rangedTokens);

  return {
    tokens: rangedTokens,
    ...summary,
  };
}

export { countWords, countSentences, parseFreezeEntries, strengthLabel };
