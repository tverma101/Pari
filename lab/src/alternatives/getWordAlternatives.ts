import type { TokenAlternative, ProtectedSpan, PreferenceProfile, AlternativesResult } from "../core/types.js";
import { tokenizeForAlternatives, isFunctionWord, isProtectedWord, FUNCTION_WORDS } from "./tokenizeForAlternatives.js";
import { getBankAlternatives } from "./synonymSources.js";
import { computeNaturalnessPenalty } from "../scoring/naturalnessPenalty.js";

/**
 * Get contextual word alternatives for a token at a given index.
 *
 * This is the backend version of "tap on a word and see synonyms."
 *
 * @param sentence - The full sentence or paragraph
 * @param tokenIndex - Index of the token to get alternatives for
 * @param protectedSpans - Any protected spans in the text
 * @param options - Additional options
 * @returns AlternativesResult with ranked alternatives
 */
export function getWordAlternatives(
  sentence: string,
  tokenIndex: number,
  protectedSpans: ProtectedSpan[] = [],
  options: {
    preferenceProfile?: PreferenceProfile | null;
    minAlternatives?: number;
  } = {}
): AlternativesResult {
  const { preferenceProfile, minAlternatives = 30 } = options;

  // Tokenize the sentence
  const tokens = tokenizeForAlternatives(sentence, protectedSpans);
  const tokenInfo = tokens.find((t) => t.index === tokenIndex);

  if (!tokenInfo) {
    return {
      token: "",
      tokenIndex,
      editable: false,
      protected: false,
      partOfSpeech: "unknown",
      alternatives: [],
    };
  }

  const word = tokenInfo.text;
  const tokenIsProtected = tokenInfo.protected || isProtectedWord(word, tokenInfo);
  const tokenIsFunction = isFunctionWord(word);

  // Protected tokens are not editable
  if (tokenIsProtected) {
    return {
      token: word,
      tokenIndex,
      editable: false,
      protected: true,
      partOfSpeech: guessPartOfSpeech(word),
      alternatives: [],
    };
  }

  // Function words: return empty alternatives
  if (tokenIsFunction) {
    // Try to find a phrase alternative
    const phrase = getPhraseForFunctionWord(sentence, tokenIndex, tokens);
    if (phrase && phrase.split(/\s+/).length > 1) {
      // Return alternatives for the phrase instead
      const phraseAlts = getBankAlternatives(phrase);
      return {
        token: word,
        tokenIndex,
        editable: false,
        protected: false,
        partOfSpeech: "function_word",
        alternatives: phraseAlts.slice(0, minAlternatives).map((alt) => ({
          ...alt,
          notes: `Phrase-level alternative for "${phrase}" — ${alt.notes}`,
        })),
      };
    }

    return {
      token: word,
      tokenIndex,
      editable: false,
      protected: false,
      partOfSpeech: "function_word",
      alternatives: [], // No useful alternatives for function words alone
    };
  }

  // Get alternatives from the synonym bank
  const bankAlts = getBankAlternatives(word);

  // If we have fewer than minAlternatives from the bank, try to generate more
  let allAlternatives = [...bankAlts];

  if (allAlternatives.length < minAlternatives) {
    allAlternatives = expandAlternatives(word, allAlternatives, minAlternatives);
  }

  // Rank and filter alternatives
  const ranked = rankAlternatives(allAlternatives, word, sentence, preferenceProfile);

  // Slice to minAlternatives (we may have expanded beyond)
  const finalAlts = ranked.slice(0, Math.max(minAlternatives, ranked.length));

  // If we still have very few alternatives, generate some generic grammar/near-synonym fillers
  const filled = fillAlternativesIfNeeded(word, finalAlts, minAlternatives);

  return {
    token: word,
    tokenIndex,
    editable: true,
    protected: false,
    partOfSpeech: guessPartOfSpeech(word),
    alternatives: filled,
  };
}

/**
 * Expand beyond the core bank by generating contextual alternatives.
 */
function expandAlternatives(
  word: string,
  existing: TokenAlternative[],
  target: number
): TokenAlternative[] {
  const expanded = [...existing];
  const existingSet = new Set(expanded.map((a) => a.text.toLowerCase()));
  const lower = word.toLowerCase();

  // Generic alternative generators for common patterns
  const genericPatterns: Record<string, Array<{ text: string; type: TokenAlternative["type"] }>> = {
    "ly": [
      { text: `less ${lower.replace(/ly$/, "")}`, type: "near_synonym" },
    ],
    "ing": [
      { text: lower.replace(/ing$/, "e"), type: "near_synonym" },
      { text: lower.replace(/ing$/, "ation"), type: "near_synonym" },
    ],
  };

  // Check for common suffixes
  for (const [suffix, patterns] of Object.entries(genericPatterns)) {
    if (lower.endsWith(suffix)) {
      for (const p of patterns) {
        if (!existingSet.has(p.text.toLowerCase())) {
          expanded.push({
            text: p.text,
            type: p.type,
            contextSafe: false,
            semanticScore: 0.3,
            naturalnessScore: 0.4,
            professorPenalty: 0.05,
            notes: "Generated alternative (verify context fit)",
          });
          existingSet.add(p.text.toLowerCase());
        }
      }
    }
  }

  // Add "more/less" modifier patterns for adjectives
  const adjPatterns = ["more", "less", "much more", "even more", "somewhat"];
  for (const mod of adjPatterns) {
    const candidate = `${mod} ${lower}`;
    if (!existingSet.has(candidate) && expanded.length < target) {
      expanded.push({
        text: candidate,
        type: "phrase_rewrite",
        contextSafe: true,
        semanticScore: 0.4,
        naturalnessScore: 0.5,
        professorPenalty: 0.02,
        notes: `Modifier-based alternative (${mod})`,
      });
      existingSet.add(candidate);
    }
  }

  return expanded;
}

/**
 * Fill with "not_recommended" alternatives if we can't reach the target count.
 * Honest behavior: don't fake 30 true synonyms.
 */
function fillAlternativesIfNeeded(
  word: string,
  alternatives: TokenAlternative[],
  target: number
): TokenAlternative[] {
  if (alternatives.length >= target) return alternatives;

  const existingTexts = new Set(alternatives.map((a) => a.text.toLowerCase()));
  const fillers: TokenAlternative[] = [];
  const lower = word.toLowerCase();

  // Add contextual fillers
  const genericFillers = [
    { text: lower, type: "not_recommended" as const, notes: "Same as original — not a rewrite" },
    { text: `the ${lower}`, type: "not_recommended" as const, notes: "Article prefix — not a replacement" },
  ];

  for (const f of genericFillers) {
    if (!existingTexts.has(f.text.toLowerCase())) {
      fillers.push({
        text: f.text,
        type: f.type,
        contextSafe: false,
        semanticScore: 0.1,
        naturalnessScore: 0.3,
        professorPenalty: 0.1,
        notes: f.notes,
      });
      existingTexts.add(f.text.toLowerCase());
    }
  }

  return [...alternatives, ...fillers];
}

/**
 * Rank alternatives by relevance to the context.
 */
function rankAlternatives(
  alternatives: TokenAlternative[],
  originalWord: string,
  context: string,
  preferenceProfile?: PreferenceProfile | null
): TokenAlternative[] {
  return alternatives
    .map((alt) => {
      let score = alt.semanticScore * 0.4 + alt.naturalnessScore * 0.3;

      // Boost simpler and true synonyms
      if (alt.type === "true_synonym") score += 0.15;
      if (alt.type === "simpler_word") score += 0.1;
      if (alt.type === "near_synonym") score += 0.05;
      if (alt.type === "not_recommended") score -= 0.2;

      // Penalize not-context-safe
      if (!alt.contextSafe) score -= 0.2;

      // Preference profile bonuses
      if (preferenceProfile) {
        const lower = alt.text.toLowerCase();
        const profile = preferenceProfile;

        // Prefer preferred replacements
        const isPreferred = Object.values(profile.preferredReplacements).some((replacements) =>
          replacements.some((r) => r.toLowerCase() === lower)
        );
        if (isPreferred) score += 0.1;

        // Penalize disliked words
        if (profile.softDislikedWords.some((w) => lower.includes(w))) score -= 0.15;
      }

      // Context fit check (simple word-level)
      const altWords = alt.text.split(/\s+/);
      const contextLower = context.toLowerCase();
      const inContext = altWords.some((w) => contextLower.includes(w));
      if (inContext) score -= 0.05; // Penalize words already in context

      return { alt, score };
    })
    .sort((a, b) => b.score - a.score)
    .map((item) => item.alt);
}

/**
 * Guess part of speech for a word (simple heuristic).
 */
function guessPartOfSpeech(word: string): string {
  const lower = word.toLowerCase();

  // Known function words
  if (FUNCTION_WORDS.has(lower)) {
    if (["the", "a", "an"].includes(lower)) return "determiner";
    if (["and", "or", "but", "so"].includes(lower)) return "conjunction";
    if (["in", "on", "at", "to", "for", "of", "by", "with", "from"].includes(lower)) return "preposition";
    if (["is", "are", "was", "were", "be", "been", "being", "have", "has", "had"].includes(lower)) return "auxiliary_verb";
    return "function_word";
  }

  // Suffix-based heuristics
  if (lower.endsWith("ly")) return "adverb";
  if (lower.endsWith("ing") || lower.endsWith("ed")) return "verb";
  if (lower.endsWith("tion") || lower.endsWith("sion") || lower.endsWith("ment") || lower.endsWith("ness")) return "noun";
  if (lower.endsWith("able") || lower.endsWith("ible") || lower.endsWith("ful") || lower.endsWith("ous") || lower.endsWith("ive")) return "adjective";

  return "unknown";
}

/**
 * Get the minimal editable phrase surrounding a function word.
 */
function getPhraseForFunctionWord(
  sentence: string,
  tokenIndex: number,
  tokens: { index: number; text: string; type: string }[]
): string | null {
  const wordIdx = tokens.findIndex((t) => t.index === tokenIndex);
  if (wordIdx === -1) return null;

  const startIdx = Math.max(0, wordIdx - 2);
  const endIdx = Math.min(tokens.length - 1, wordIdx + 2);

  const phraseWords: string[] = [];
  for (let i = startIdx; i <= endIdx; i++) {
    if (tokens[i].type === "word") {
      phraseWords.push(tokens[i].text);
    }
  }

  return phraseWords.length > 1 ? phraseWords.join(" ") : null;
}

export type { AlternativesResult, TokenAlternative } from "../core/types.js";
