/**
 * Normalize punctuation spacing without breaking common meridiem or dotted
 * abbreviations such as "3 a.m.", "e.g.", and "U.S.".
 *
 * The finalizer runs several conservative text passes. Keeping this rule in
 * one place prevents a later pass from undoing an earlier abbreviation fix.
 */
function isMeridiemContinuation(text: string, offset: number): boolean {
  const before = text.slice(0, offset + 1);
  const after = text.slice(offset + 1);
  return /(?:^|\s)(?:a|p)\.$/i.test(before) && /^m(?:\b|[.\s])/i.test(after);
}

function isMeridiemSentenceBoundary(text: string, offset: number): boolean {
  const before = text.slice(0, offset + 1);
  return /\b(?:a|p)\.m\.$/i.test(before);
}

function isDottedAbbreviationContinuation(text: string, offset: number): boolean {
  const before = text.slice(0, offset + 1);
  const after = text.slice(offset + 1);
  // Only suppress spacing for an *internal* abbreviation dot: a short token
  // followed immediately by a one-letter dotted component. The final dot in
  // `e.g.Example` is still repaired to `e.g. Example` because `Example` is
  // not a one-letter dotted component.
  return /\b[A-Za-z]{1,3}\.$/.test(before) && /^[A-Za-z]\./.test(after);
}

export function repairMeridiemAbbreviations(text: string): string {
  // Require a clock immediately before a spaced-out meridiem marker. The old
  // global `A. M.` repair could turn a person's initials (`A. M. Smith`) into
  // `a.m. Smith`, which is a factual corruption rather than grammar cleanup.
  return text.replace(
    /\b(\d{1,2}(?::\d{2})?\s+)([ap])\.\s*m\.?/gi,
    (_match, clock: string, marker: string) => `${clock}${marker.toLowerCase()}.m.`,
  );
}

export function repairPunctuationSpacing(text: string): string {
  const normalized = repairMeridiemAbbreviations(text);
  return normalized.replace(/([,.;!?])(?=[A-Za-z])/g, (match, punctuation: string, offset: number, fullText: string) => {
    if (punctuation === ".") {
      if (isMeridiemContinuation(fullText, offset)) return match;
      if (isDottedAbbreviationContinuation(fullText, offset)) return match;
    }
    return `${punctuation} `;
  });
}

export function capitalizeSentenceStarts(text: string): string {
  return text.replace(/(^|[.!?]\s+)([a-z])/g, (match, prefix: string, letter: string, offset: number, fullText: string) => {
    if (isMeridiemContinuation(fullText, offset) || isMeridiemSentenceBoundary(fullText, offset)) return match;
    return `${prefix}${letter.toUpperCase()}`;
  });
}
