import type { ProtectedSpan } from "../core/types.js";

/**
 * Tokenize text for alternative/synonym lookup.
 * Returns a list of tokens with position, type, and protection info.
 */

export interface TokenForAlternatives {
  text: string;
  index: number;
  start: number;
  end: number;
  type: "word" | "punctuation" | "whitespace" | "protected";
  protected: boolean;
  protectedSpanId: string | null;
}

const FUNCTION_WORDS = new Set([
  "the", "a", "an", "and", "or", "but", "if", "so", "as", "at", "by", "for",
  "in", "of", "on", "to", "with", "up", "all", "any", "be", "do", "has", "had",
  "have", "he", "her", "hers", "him", "his", "is", "it", "its", "me", "my",
  "no", "not", "our", "she", "their", "them", "they", "us", "was", "we", "were",
  "you", "your", "this", "that", "these", "those", "am", "are", "been", "being",
  "can", "could", "did", "does", "doing", "may", "might", "must", "shall",
  "should", "will", "would", "about", "above", "across", "after", "against",
  "along", "among", "around", "before", "behind", "below", "beneath", "beside",
  "between", "beyond", "down", "during", "except", "from", "inside", "into",
  "near", "off", "outside", "over", "through", "under", "until", "upon",
  "within", "without", "than", "very", "just", "too", "also", "even", "only",
  "really", "quite", "rather", "here", "there", "then", "now",
]);

/**
 * Words that the protection layer might PROACTIVELY flag (e.g. by
 * the entity-name heuristic) but which are actually regular content
 * words that *should* have editable alternatives.  Add problematic
 * false positives here so they bypass the protected-word gate.
 */
const FALSE_POSITIVE_WORDS = new Set([
  "communication", "self-concept", "social comparison",
]);

/**
 * Tokenize text for alternatives lookup, respecting protected spans.
 */
export function tokenizeForAlternatives(
  text: string,
  protectedSpans: ProtectedSpan[]
): TokenForAlternatives[] {
  // Build a set of protected ranges
  const protectedRanges = protectedSpans.map((s) => ({
    start: s.startOffset,
    end: s.endOffset,
    id: s.id,
    text: s.originalText,
  }));

  const tokens: TokenForAlternatives[] = [];
  let tokenIndex = 0;

  // Tokenize by splitting on word boundaries
  const wordRegex = /\S+\s*/g;
  let match: RegExpExecArray | null;

  // Sort protected ranges by position
  protectedRanges.sort((a, b) => a.start - b.start);

  wordRegex.lastIndex = 0;

  while ((match = wordRegex.exec(text)) !== null) {
    const rawToken = match[0];
    const tokenStart = match.index;
    const tokenEnd = match.index + rawToken.length;

    // Check if this token falls within a protected range
    const containingSpan = protectedRanges.find(
      (ps) => tokenStart >= ps.start && tokenEnd <= ps.end && tokenEnd >= ps.start
    );
    // Also check for overlap
    const overlappingSpan = protectedRanges.find(
      (ps) => (tokenStart >= ps.start && tokenStart < ps.end) || (tokenEnd > ps.start && tokenEnd <= ps.end)
    );

    const isProtected = containingSpan != null || overlappingSpan != null;

    // Determine token type
    const cleanText = rawToken.trim();
    const isWord = /^[a-zA-Z]+(?:[-'][a-zA-Z]+)*$/.test(cleanText);
    const isPunct = /^[.,!?;:'"()\[\]{}]+$/.test(cleanText);

    let type: "word" | "punctuation" | "whitespace" | "protected";
    if (isProtected) {
      type = "protected";
    } else if (isWord) {
      type = "word";
    } else if (isPunct) {
      type = "punctuation";
    } else {
      type = "whitespace";
    }

    tokens.push({
      text: cleanText,
      index: tokenIndex,
      start: tokenStart,
      end: tokenEnd,
      type,
      protected: isProtected,
      protectedSpanId: overlappingSpan?.id ?? containingSpan?.id ?? null,
    });

    tokenIndex++;
  }

  return tokens;
}

/**
 * Check if a word is a function word (not worth providing alternatives for).
 */
export function isFunctionWord(word: string): boolean {
  return FUNCTION_WORDS.has(word.toLowerCase());
}

/**
 * Check if a word is protected (should not be editable).
 */
export function isProtectedWord(
  word: string,
  tokenInfo: TokenForAlternatives
): boolean {
  // Skip protection for known false-positive words
  if (FALSE_POSITIVE_WORDS.has(word.toLowerCase())) return false;
  if (tokenInfo.protected) return true;
  return false;
}

/**
 * Get the minimal editable phrase for a function word.
 * When users tap function words, we try to return alternatives for
 * the smallest meaningful phrase containing it.
 */
export function getPhraseForFunctionWord(
  tokenIndex: number,
  tokens: TokenForAlternatives[]
): string | null {
  // Look at nearby word context (±2 tokens)
  const startIdx = Math.max(0, tokenIndex - 2);
  const endIdx = Math.min(tokens.length - 1, tokenIndex + 2);

  const phraseTokens: string[] = [];
  for (let i = startIdx; i <= endIdx; i++) {
    if (tokens[i].type === "word" || tokens[i].type === "protected") {
      phraseTokens.push(tokens[i].text);
    }
  }

  return phraseTokens.length > 1 ? phraseTokens.join(" ") : null;
}

export { FUNCTION_WORDS };
